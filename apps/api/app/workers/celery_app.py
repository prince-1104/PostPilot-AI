"""Celery application for PostPilot background publishing."""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import schedule

from app.core.config import Settings, get_settings

celery_app = Celery("postpilot")
celery_app.conf.imports = ("app.workers.tasks",)

_configured = False


def configure_celery(settings: Settings | None = None) -> Celery:
    """Apply broker, queues, limits, and beat schedule from Settings."""
    global _configured
    s = settings or get_settings()
    celery_app.conf.update(
        broker_url=s.celery_broker_url,
        result_backend=None,
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_concurrency=s.celery_worker_concurrency,
        task_soft_time_limit=s.celery_task_soft_time_limit_seconds,
        task_time_limit=s.celery_task_time_limit_seconds,
        broker_connection_retry_on_startup=s.celery_broker_connection_retry_on_startup,
        broker_connection_max_retries=s.celery_broker_connection_max_retries,
        task_default_queue=s.celery_queue_publish,
        task_queues={
            s.celery_queue_publish: {
                "exchange": s.celery_queue_publish,
                "routing_key": s.celery_queue_publish,
            }
        },
        task_routes={
            "app.workers.tasks.dispatch_due_posts": {"queue": s.celery_queue_publish},
            "app.workers.tasks.execute_publish": {"queue": s.celery_queue_publish},
            "app.workers.tasks.recover_stale_leases": {"queue": s.celery_queue_publish},
        },
        task_annotations={
            "app.workers.tasks.execute_publish": {"max_retries": 0},
        },
        beat_schedule={
            "dispatch-due-posts": {
                "task": "app.workers.tasks.dispatch_due_posts",
                "schedule": schedule(run_every=s.publish_dispatcher_interval_seconds),
            },
            "recover-stale-leases": {
                "task": "app.workers.tasks.recover_stale_leases",
                "schedule": schedule(run_every=s.publish_recovery_interval_seconds),
            },
        },
        timezone="UTC",
        enable_utc=True,
        worker_hijack_root_logger=False,
        # Writable for the non-root container user (see Compose beat --schedule).
        beat_schedule_filename="/tmp/celerybeat-schedule",
    )
    _configured = True
    return celery_app


def ensure_celery_configured() -> Celery:
    if not _configured:
        configure_celery()
    return celery_app


# Worker/beat containers always set APP_ENV. Unit tests clear it during isolation so
# import-time configuration is skipped; tasks call ensure_celery_configured() instead.
if os.environ.get("APP_ENV"):
    configure_celery()
