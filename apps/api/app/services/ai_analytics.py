"""Admin AI analytics queries (real DB aggregates only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import mean
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, UnprocessableError
from app.models import AgentDraft, AgentDraftScheduleOp, AgentMessage, AgentThread, User
from app.models.enums import AgentDraftScheduleOpState, AgentDraftStatus
from app.models.observability import AgentNodeTrace, LLMUsageEvent
from app.schemas.ai_analytics import AiAnalyticsSummary, ThreadInspectionResponse


def resolve_window(
    *,
    preset: str | None,
    from_time: datetime | None,
    to_time: datetime | None,
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    if from_time is not None or to_time is not None:
        start = from_time or (now - timedelta(days=7))
        end = to_time or now
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end < start:
            raise UnprocessableError("to_time must be after from_time.")
        return start, end

    mapping = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    delta = mapping.get(preset or "7d", timedelta(days=7))
    return now - delta, now


class AiAnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def summary(
        self,
        *,
        from_time: datetime,
        to_time: datetime,
    ) -> AiAnalyticsSummary:
        usage_rows = (
            await self._db.execute(
                select(LLMUsageEvent).where(
                    LLMUsageEvent.requested_at >= from_time,
                    LLMUsageEvent.requested_at <= to_time,
                )
            )
        ).scalars().all()

        total = len(usage_rows)
        successful = sum(1 for r in usage_rows if r.success)
        failed = total - successful
        known = [r for r in usage_rows if r.usage_known]
        unknown = total - len(known)

        def _sum_tokens(attr: str) -> int | None:
            if not known:
                return None
            return int(sum(getattr(r, attr) or 0 for r in known))

        cost_rows = [r for r in usage_rows if r.cost_available and r.estimated_cost is not None]
        total_cost = (
            sum((r.estimated_cost for r in cost_rows), Decimal("0")) if cost_rows else None
        )

        latencies = [r.latency_ms for r in usage_rows]
        avg_latency = float(mean(latencies)) if latencies else None
        p95 = _percentile(latencies, 95) if latencies else None

        by_model: dict[str, dict] = {}
        for row in usage_rows:
            key = f"{row.provider}/{row.model}"
            bucket = by_model.setdefault(
                key,
                {
                    "provider": row.provider,
                    "model": row.model,
                    "requests": 0,
                    "estimated_cost": Decimal("0"),
                    "cost_available": False,
                },
            )
            bucket["requests"] += 1
            if row.cost_available and row.estimated_cost is not None:
                bucket["estimated_cost"] += row.estimated_cost
                bucket["cost_available"] = True

        cost_per_user: dict[str, dict] = {}
        cost_per_thread: dict[str, dict] = {}
        for row in usage_rows:
            if not row.cost_available or row.estimated_cost is None:
                continue
            u = cost_per_user.setdefault(
                str(row.user_id),
                {"user_id": str(row.user_id), "estimated_cost": Decimal("0"), "requests": 0},
            )
            u["estimated_cost"] += row.estimated_cost
            u["requests"] += 1
            if row.thread_id:
                t = cost_per_thread.setdefault(
                    str(row.thread_id),
                    {
                        "thread_id": str(row.thread_id),
                        "user_id": str(row.user_id),
                        "estimated_cost": Decimal("0"),
                        "requests": 0,
                    },
                )
                t["estimated_cost"] += row.estimated_cost
                t["requests"] += 1

        review_traces = (
            await self._db.execute(
                select(AgentNodeTrace).where(
                    AgentNodeTrace.node_name == "review",
                    AgentNodeTrace.started_at >= from_time,
                    AgentNodeTrace.started_at <= to_time,
                )
            )
        ).scalars().all()
        review_count = len(review_traces)
        review_failures = sum(1 for t in review_traces if t.review_passed is False)
        revise_rows = (
            await self._db.execute(
                select(AgentNodeTrace).where(
                    AgentNodeTrace.node_name == "revise",
                    AgentNodeTrace.started_at >= from_time,
                    AgentNodeTrace.started_at <= to_time,
                )
            )
        ).scalars().all()
        automatic_revision_traces = len(revise_rows)

        drafts_generated = (
            await self._db.execute(
                select(func.count())
                .select_from(AgentDraft)
                .where(
                    AgentDraft.created_at >= from_time,
                    AgentDraft.created_at <= to_time,
                    AgentDraft.status == AgentDraftStatus.DRAFT.value,
                )
            )
        ).scalar_one()

        scheduled = (
            await self._db.execute(
                select(func.count())
                .select_from(AgentDraftScheduleOp)
                .where(
                    AgentDraftScheduleOp.confirmed_at >= from_time,
                    AgentDraftScheduleOp.confirmed_at <= to_time,
                    AgentDraftScheduleOp.state == AgentDraftScheduleOpState.CONFIRMED.value,
                )
            )
        ).scalar_one()

        return AiAnalyticsSummary(
            from_time=from_time,
            to_time=to_time,
            total_llm_requests=total,
            successful_llm_requests=successful,
            failed_llm_requests=failed,
            total_input_tokens=_sum_tokens("input_tokens"),
            total_output_tokens=_sum_tokens("output_tokens"),
            total_cached_input_tokens=_sum_tokens("cached_input_tokens"),
            usage_known_requests=len(known),
            usage_unknown_requests=unknown,
            total_estimated_cost=total_cost,
            cost_available_requests=len(cost_rows),
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95,
            review_traces=review_count,
            review_failures=review_failures,
            review_failure_rate=(
                (review_failures / review_count) if review_count else None
            ),
            automatic_revision_traces=automatic_revision_traces,
            drafts_generated=int(drafts_generated or 0),
            approved_ai_drafts_scheduled=int(scheduled or 0),
            requests_by_model=[
                {
                    **v,
                    "estimated_cost": float(v["estimated_cost"]) if v["cost_available"] else None,
                }
                for v in sorted(by_model.values(), key=lambda x: x["requests"], reverse=True)
            ],
            cost_per_user=[
                {**v, "estimated_cost": float(v["estimated_cost"])}
                for v in sorted(
                    cost_per_user.values(), key=lambda x: x["estimated_cost"], reverse=True
                )[:50]
            ],
            cost_per_conversation=[
                {**v, "estimated_cost": float(v["estimated_cost"])}
                for v in sorted(
                    cost_per_thread.values(), key=lambda x: x["estimated_cost"], reverse=True
                )[:50]
            ],
        )

    async def inspect_thread(self, *, thread_id: UUID) -> ThreadInspectionResponse:
        thread = (
            await self._db.execute(select(AgentThread).where(AgentThread.id == thread_id))
        ).scalar_one_or_none()
        if thread is None:
            raise NotFoundError("Thread not found.")

        message_count = (
            await self._db.execute(
                select(func.count())
                .select_from(AgentMessage)
                .where(AgentMessage.thread_id == thread_id)
            )
        ).scalar_one()

        draft = (
            await self._db.execute(
                select(AgentDraft)
                .where(AgentDraft.thread_id == thread_id)
                .order_by(AgentDraft.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        ops: list[AgentDraftScheduleOp] = []
        if draft is not None:
            ops = list(
                (
                    await self._db.execute(
                        select(AgentDraftScheduleOp).where(
                            AgentDraftScheduleOp.draft_id == draft.id
                        )
                    )
                ).scalars().all()
            )

        traces = (
            await self._db.execute(
                select(AgentNodeTrace)
                .where(AgentNodeTrace.thread_id == thread_id)
                .order_by(AgentNodeTrace.started_at.asc())
            )
        ).scalars().all()

        usages = (
            await self._db.execute(
                select(LLMUsageEvent)
                .where(LLMUsageEvent.thread_id == thread_id)
                .order_by(LLMUsageEvent.requested_at.asc())
            )
        ).scalars().all()

        return ThreadInspectionResponse(
            thread_id=thread.id,
            user_id=thread.user_id,
            title=thread.title,
            status=thread.status,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            message_count=int(message_count or 0),
            draft_version=draft.version if draft else None,
            draft_status=draft.status if draft else None,
            scheduled_post_id=draft.scheduled_post_id if draft else None,
            schedule_ops=[
                {
                    "id": str(op.id),
                    "state": op.state,
                    "draft_version": op.draft_version,
                    "scheduled_post_id": (
                        str(op.scheduled_post_id) if op.scheduled_post_id else None
                    ),
                    "confirmed_at": (
                        op.confirmed_at.isoformat() if op.confirmed_at else None
                    ),
                }
                for op in ops
            ],
            traces=[
                {
                    "id": str(t.id),
                    "trace_id": str(t.trace_id),
                    "node_name": t.node_name,
                    "status": t.status,
                    "duration_ms": t.duration_ms,
                    "provider": t.provider,
                    "model": t.model,
                    "error_category": t.error_category,
                    "review_passed": t.review_passed,
                    "revision_count": t.revision_count,
                    "started_at": t.started_at.isoformat(),
                    "ended_at": t.ended_at.isoformat(),
                    "meta": t.meta,
                }
                for t in traces
            ],
            usage_events=[
                {
                    "id": str(u.id),
                    "trace_id": str(u.trace_id),
                    "node_name": u.node_name,
                    "provider": u.provider,
                    "model": u.model,
                    "success": u.success,
                    "usage_known": u.usage_known,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cached_input_tokens": u.cached_input_tokens,
                    "total_tokens": u.total_tokens,
                    "latency_ms": u.latency_ms,
                    "estimated_cost": (
                        float(u.estimated_cost) if u.estimated_cost is not None else None
                    ),
                    "pricing_version": u.pricing_version,
                    "cost_available": u.cost_available,
                    "requested_at": u.requested_at.isoformat(),
                }
                for u in usages
            ],
        )


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def user_is_admin(user: User, *, admin_user_ids: list[str], admin_emails: list[str]) -> bool:
    uid = str(user.id).lower()
    if uid in {x.lower() for x in admin_user_ids}:
        return True
    email = (user.email or "").strip().lower()
    return bool(email and email in {x.lower() for x in admin_emails})
