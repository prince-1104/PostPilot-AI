"""Persist usage + traces without failing the user-facing assistant turn."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.observability import AgentNodeTrace, LLMUsageEvent, ModelPricingVersion
from app.observability.pricing import catalog_entries, estimate_cost
from app.observability.usage import LLMUsage

logger = structlog.get_logger(__name__)


class ObservabilityRecorder:
    """Best-effort append-only recorder. Failures are logged, never raised to callers."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_pricing_seeded(self) -> None:
        try:
            async with self._session_factory() as session:
                for price in catalog_entries():
                    session.add(
                        ModelPricingVersion(
                            id=uuid4(),
                            pricing_version=price.pricing_version,
                            model=price.model,
                            provider="openai",
                            currency=price.currency,
                            input_per_million=price.input_per_million,
                            cached_input_per_million=price.cached_input_per_million,
                            output_per_million=price.output_per_million,
                            effective_date=price.effective_date,
                            source=price.source,
                        )
                    )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
        except Exception:
            logger.warning("observability.pricing_seed_failed", exc_info=True)

    async def record_llm_usage(
        self,
        *,
        usage: LLMUsage,
        user_id: UUID,
        thread_id: UUID | None,
        trace_id: UUID,
        turn_id: UUID | None,
        idempotency_key: str,
        requested_at: datetime | None = None,
    ) -> UUID | None:
        cost = estimate_cost(
            model=usage.model,
            input_tokens=usage.input_tokens if usage.usage_known else None,
            output_tokens=usage.output_tokens if usage.usage_known else None,
            cached_input_tokens=usage.cached_input_tokens if usage.usage_known else None,
        )
        event_id = uuid4()
        try:
            async with self._session_factory() as session:
                session.add(
                    LLMUsageEvent(
                        id=event_id,
                        idempotency_key=idempotency_key[:128],
                        trace_id=trace_id,
                        turn_id=turn_id,
                        user_id=user_id,
                        thread_id=thread_id,
                        node_name=usage.node_name or "unknown",
                        schema_name=usage.schema_name,
                        provider=usage.provider,
                        model=usage.model,
                        success=usage.success,
                        error_category=usage.error_category,
                        usage_known=usage.usage_known,
                        input_tokens=usage.input_tokens if usage.usage_known else None,
                        output_tokens=usage.output_tokens if usage.usage_known else None,
                        cached_input_tokens=(
                            usage.cached_input_tokens if usage.usage_known else None
                        ),
                        total_tokens=usage.total_tokens if usage.usage_known else None,
                        provider_request_id=usage.provider_request_id,
                        latency_ms=int(usage.latency_ms),
                        estimated_cost=cost.amount if cost.available else None,
                        cost_currency=cost.currency if cost.available else None,
                        pricing_version=cost.pricing_version if cost.available else None,
                        cost_available=cost.available,
                        requested_at=requested_at or datetime.now(UTC),
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    logger.info(
                        "observability.usage_duplicate",
                        idempotency_key=idempotency_key[:32],
                    )
                    return None
            return event_id
        except Exception:
            logger.warning(
                "observability.usage_persist_failed",
                trace_id=str(trace_id),
                exc_info=True,
            )
            return None

    async def record_node_trace(
        self,
        *,
        user_id: UUID,
        thread_id: UUID | None,
        trace_id: UUID,
        turn_id: UUID | None,
        node_name: str,
        status: str,
        started_at: datetime,
        ended_at: datetime,
        duration_ms: int,
        idempotency_key: str,
        provider: str | None = None,
        model: str | None = None,
        usage_event_id: UUID | None = None,
        error_category: str | None = None,
        review_passed: bool | None = None,
        revision_count: int | None = None,
        meta: dict | None = None,
    ) -> None:
        safe_meta = _sanitize_meta(meta or {})
        try:
            async with self._session_factory() as session:
                session.add(
                    AgentNodeTrace(
                        id=uuid4(),
                        idempotency_key=idempotency_key[:128],
                        trace_id=trace_id,
                        turn_id=turn_id,
                        user_id=user_id,
                        thread_id=thread_id,
                        node_name=node_name,
                        status=status,
                        provider=provider,
                        model=model,
                        usage_event_id=usage_event_id,
                        duration_ms=duration_ms,
                        error_category=error_category,
                        review_passed=review_passed,
                        revision_count=revision_count,
                        meta=safe_meta,
                        started_at=started_at,
                        ended_at=ended_at,
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
        except Exception:
            logger.warning(
                "observability.trace_persist_failed",
                trace_id=str(trace_id),
                node_name=node_name,
                exc_info=True,
            )


_BLOCKED_META_KEYS = frozenset(
    {
        "prompt",
        "system",
        "user",
        "content",
        "message",
        "api_key",
        "token",
        "authorization",
        "password",
        "secret",
    }
)


def _sanitize_meta(meta: dict) -> dict:
    out: dict = {}
    for key, value in meta.items():
        lowered = str(key).lower()
        if any(b in lowered for b in _BLOCKED_META_KEYS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > 200:
                out[key] = value[:200]
            else:
                out[key] = value
        elif isinstance(value, list) and all(isinstance(x, (str, int)) for x in value[:20]):
            out[key] = value[:20]
    return out
