"""Celery tasks: dispatch, execute, recover."""

from __future__ import annotations

import os
import socket
from uuid import UUID

import structlog

from app.services.publishing.dispatcher import DispatchService
from app.services.publishing.executor import run_publish_pipeline
from app.services.publishing.recovery import RecoveryService
from app.workers.celery_app import celery_app, ensure_celery_configured
from app.workers.runtime import (
    configure_worker_logging,
    get_publisher,
    get_worker_settings,
    run_async,
)

# Configure logging once at import (worker/beat set APP_ENV), before tasks run.
configure_worker_logging()

logger = structlog.get_logger(__name__)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _enqueue_publish(post_id: UUID) -> str | None:
    ensure_celery_configured()
    async_result = execute_publish.delay(str(post_id))
    return async_result.id


@celery_app.task(name="app.workers.tasks.dispatch_due_posts", bind=True)
def dispatch_due_posts(self) -> dict[str, int]:
    ensure_celery_configured()
    settings = get_worker_settings()

    async def _run(session):
        return await DispatchService(
            session, settings=settings, enqueue=_enqueue_publish
        ).dispatch_due()

    result = run_async(_run)
    logger.info("publish.task.dispatch_complete", **result, worker_id=_worker_id())
    return result


@celery_app.task(
    name="app.workers.tasks.execute_publish",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def execute_publish(self, post_id: str) -> str:
    ensure_celery_configured()
    settings = get_worker_settings()
    publisher = get_publisher()
    worker_id = _worker_id()
    task_id = self.request.id

    async def _run(session):
        return await run_publish_pipeline(
            session,
            settings=settings,
            publisher=publisher,
            post_id=UUID(post_id),
            worker_id=worker_id,
            celery_task_id=task_id,
        )

    outcome = run_async(_run)
    logger.info(
        "publish.task.execute_complete",
        post_id=post_id,
        outcome=outcome,
        worker_id=worker_id,
        celery_task_id=task_id,
    )
    return outcome


@celery_app.task(name="app.workers.tasks.recover_stale_leases", bind=True)
def recover_stale_leases(self) -> dict[str, int]:
    ensure_celery_configured()
    settings = get_worker_settings()

    async def _run(session):
        return await RecoveryService(session, settings=settings).recover_expired_leases()

    result = run_async(_run)
    logger.info("publish.task.recovery_complete", **result, worker_id=_worker_id())
    return result
