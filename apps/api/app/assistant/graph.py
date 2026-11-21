"""LangGraph StateGraph for Phase 5A/5B content drafting (no schedule/publish)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langgraph.graph import END, START, StateGraph

from app.assistant.llm.base import LLMError, LLMProvider
from app.assistant.prompts import (
    INTENT_SYSTEM,
    REQUIREMENTS_SYSTEM,
    REVIEW_SYSTEM,
    REVISION_SYSTEM,
    WRITING_SYSTEM,
)
from app.assistant.schedule_parse import parse_schedule_expression, to_utc
from app.assistant.schemas import (
    GraphSnapshot,
    IntentResult,
    RequirementsResult,
    ReviewResult,
    WritingResult,
    WritingStyle,
)
from app.core.config import Settings
from app.observability.otel import node_span
from app.observability.usage import LLMUsage


@dataclass
class TurnTelemetry:
    """Side-channel collector so LangGraph state merges cannot drop traces."""

    usages: list[LLMUsage] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    turn_id: str = field(default_factory=lambda: str(uuid4()))

_SALARY_CLAIM = re.compile(
    r"(\$\s?\d|\bINR\b|\bUSD\b|\bsalary\b|\bcompensation\b|\bCTC\b|\bbenefits?\s+include\b)",
    re.IGNORECASE,
)
_URL_CLAIM = re.compile(r"https?://|www\.", re.IGNORECASE)
_PUBLISH_CLAIM = re.compile(
    r"(has been published|scheduled successfully|posted to linkedin|already live on linkedin)",
    re.IGNORECASE,
)


class AgentState(TypedDict, total=False):
    thread_id: str
    user_id: str
    last_user_message: str
    timezone: str | None
    intent_type: str | None
    post_category: str | None
    confirmed_facts: dict[str, str]
    optional_preferences: dict[str, str]
    missing_required_fields: list[str]
    clarification_questions: list[str]
    requested_schedule_text: str | None
    proposed_scheduled_at: str | None
    draft_content: str | None
    suggested_hashtags: list[str]
    suggested_skills: list[str]
    suggested_responsibilities: list[str]
    assumptions: list[str]
    writing_style: str
    refine_instruction: str | None
    review_passed: bool | None
    review_issues: list[str]
    review_suggestions: list[str]
    unsupported_claims: list[str]
    auto_revision_count: int
    user_regen_count: int
    llm_calls_this_turn: int
    force_path: str | None  # "writing" | "revise" | None
    current_stage: str
    validation_errors: list[str]
    assistant_reply: str | None
    response_state: str
    injection_attempt: bool
    starts_new_topic: bool
    schedule_reference_at: str | None


def _parse_optional_iso(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def empty_state(*, thread_id: UUID, user_id: UUID, timezone: str | None = None) -> AgentState:
    return {
        "thread_id": str(thread_id),
        "user_id": str(user_id),
        "timezone": timezone,
        "confirmed_facts": {},
        "optional_preferences": {},
        "missing_required_fields": [],
        "clarification_questions": [],
        "suggested_hashtags": [],
        "suggested_skills": [],
        "suggested_responsibilities": [],
        "assumptions": [],
        "validation_errors": [],
        "review_issues": [],
        "review_suggestions": [],
        "unsupported_claims": [],
        "writing_style": "professional",
        "auto_revision_count": 0,
        "user_regen_count": 0,
        "llm_calls_this_turn": 0,
        "current_stage": "intent",
        "response_state": "generating",
        "injection_attempt": False,
        "starts_new_topic": False,
        "schedule_reference_at": None,
    }


def snapshot_from_state(state: AgentState) -> GraphSnapshot:
    proposed = state.get("proposed_scheduled_at")
    style = state.get("writing_style") or "professional"
    if style not in {"professional", "conversational", "concise", "detailed", "promotional"}:
        style = "professional"
    return GraphSnapshot(
        thread_id=state["thread_id"],
        user_id=state["user_id"],
        intent_type=state.get("intent_type"),  # type: ignore[arg-type]
        post_category=state.get("post_category"),  # type: ignore[arg-type]
        confirmed_facts=dict(state.get("confirmed_facts") or {}),
        optional_preferences=dict(state.get("optional_preferences") or {}),
        missing_required_fields=list(state.get("missing_required_fields") or []),
        clarification_questions=list(state.get("clarification_questions") or []),
        requested_schedule_text=state.get("requested_schedule_text"),
        proposed_scheduled_at=None if not proposed else datetime.fromisoformat(proposed),
        timezone=state.get("timezone"),
        draft_content=state.get("draft_content"),
        suggested_hashtags=list(state.get("suggested_hashtags") or []),
        suggested_skills=list(state.get("suggested_skills") or []),
        suggested_responsibilities=list(state.get("suggested_responsibilities") or []),
        assumptions=list(state.get("assumptions") or []),
        writing_style=style,  # type: ignore[arg-type]
        refine_instruction=state.get("refine_instruction"),
        review_passed=state.get("review_passed"),
        review_issues=list(state.get("review_issues") or []),
        review_suggestions=list(state.get("review_suggestions") or []),
        unsupported_claims=list(state.get("unsupported_claims") or []),
        auto_revision_count=int(state.get("auto_revision_count") or 0),
        user_regen_count=int(state.get("user_regen_count") or 0),
        llm_calls_this_turn=int(state.get("llm_calls_this_turn") or 0),
        current_stage=state.get("current_stage") or "intent",  # type: ignore[arg-type]
        validation_errors=list(state.get("validation_errors") or []),
        last_user_message=state.get("last_user_message"),
        assistant_reply=state.get("assistant_reply"),
        response_state=state.get("response_state") or "generating",  # type: ignore[arg-type]
        injection_attempt=bool(state.get("injection_attempt")),
        starts_new_topic=bool(state.get("starts_new_topic")),
        schedule_reference_at=_parse_optional_iso(state.get("schedule_reference_at")),
    )


def state_from_snapshot(snapshot: GraphSnapshot | dict[str, Any]) -> AgentState:
    data = (
        snapshot
        if isinstance(snapshot, GraphSnapshot)
        else GraphSnapshot.model_validate(snapshot)
    )
    proposed = data.proposed_scheduled_at.isoformat() if data.proposed_scheduled_at else None
    return {
        "thread_id": data.thread_id,
        "user_id": data.user_id,
        "timezone": data.timezone,
        "intent_type": data.intent_type,
        "post_category": data.post_category,
        "confirmed_facts": dict(data.confirmed_facts),
        "optional_preferences": dict(data.optional_preferences),
        "missing_required_fields": list(data.missing_required_fields),
        "clarification_questions": list(data.clarification_questions),
        "requested_schedule_text": data.requested_schedule_text,
        "proposed_scheduled_at": proposed,
        "draft_content": data.draft_content,
        "suggested_hashtags": list(data.suggested_hashtags),
        "suggested_skills": list(data.suggested_skills),
        "suggested_responsibilities": list(data.suggested_responsibilities),
        "assumptions": list(data.assumptions),
        "writing_style": data.writing_style,
        "refine_instruction": data.refine_instruction,
        "review_passed": data.review_passed,
        "review_issues": list(data.review_issues),
        "review_suggestions": list(data.review_suggestions),
        "unsupported_claims": list(data.unsupported_claims),
        "auto_revision_count": data.auto_revision_count,
        "user_regen_count": data.user_regen_count,
        "llm_calls_this_turn": 0,  # reset each HTTP turn
        "current_stage": data.current_stage,
        "validation_errors": list(data.validation_errors),
        "last_user_message": data.last_user_message,
        "assistant_reply": data.assistant_reply,
        "response_state": data.response_state,
        "injection_attempt": data.injection_attempt,
        "starts_new_topic": bool(data.starts_new_topic),
        "schedule_reference_at": (
            data.schedule_reference_at.isoformat() if data.schedule_reference_at else None
        ),
    }


def _known_value_blob(state: AgentState) -> str:
    facts = dict(state.get("confirmed_facts") or {})
    optional = dict(state.get("optional_preferences") or {})
    return " ".join(f"{k} {v}" for k, v in {**facts, **optional}.items()).lower()


def heuristic_unsupported_claims(state: AgentState) -> list[str]:
    """Deterministic claim checks (advisory input to review / hard flags)."""
    content = state.get("draft_content") or ""
    known = _known_value_blob(state)
    claims: list[str] = []
    if _SALARY_CLAIM.search(content) and "salary" not in known and "compensation" not in known:
        claims.append("Invented or unconfirmed salary/compensation claim")
    if _URL_CLAIM.search(content) and "application_url" not in known and "apply_url" not in known:
        claims.append("Invented or unconfirmed application link")
    if _PUBLISH_CLAIM.search(content):
        claims.append("Draft claims the post was already published or scheduled")
    if "UNFIXABLE_CLAIM" in content:
        claims.append("Unsupported employer guarantee claim")
    return claims


async def _llm_call(
    llm: LLMProvider,
    settings: Settings,
    state: AgentState,
    telemetry: TurnTelemetry,
    *,
    system: str,
    user: str,
    schema: type,
    node_name: str,
) -> Any:
    calls = int(state.get("llm_calls_this_turn") or 0)
    if calls >= settings.ai_max_llm_calls_per_turn:
        raise LLMError(
            "This turn exceeded the AI request budget. Please send a shorter follow-up.",
            code="llm_budget_exceeded",
        )
    state["llm_calls_this_turn"] = calls + 1
    started = datetime.now(UTC)
    t0 = time.perf_counter()
    timeout = settings.ai_node_timeout_seconds
    try:
        with node_span(
            f"assistant.node.{node_name}",
            attributes={
                "thread_id": state.get("thread_id"),
                "trace_id": telemetry.trace_id,
                "schema": schema.__name__,
            },
        ):
            result = await asyncio.wait_for(
                llm.complete_structured(system=system, user=user, schema=schema),
                timeout=timeout,
            )
    except TimeoutError as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        telemetry.traces.append(
            {
                "node_name": node_name,
                "status": "timeout",
                "started_at": started.isoformat(),
                "ended_at": datetime.now(UTC).isoformat(),
                "duration_ms": duration_ms,
                "error_category": "llm_node_timeout",
                "schema_name": schema.__name__,
            }
        )
        raise LLMError(
            "An AI step took too long and was stopped. Please try again.",
            code="llm_node_timeout",
        ) from exc
    except LLMError as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        telemetry.traces.append(
            {
                "node_name": node_name,
                "status": "error",
                "started_at": started.isoformat(),
                "ended_at": datetime.now(UTC).isoformat(),
                "duration_ms": duration_ms,
                "error_category": exc.code,
                "schema_name": schema.__name__,
            }
        )
        raise

    usage = LLMUsage(
        provider=result.usage.provider,
        model=result.usage.model,
        success=result.usage.success,
        latency_ms=result.usage.latency_ms,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cached_input_tokens=result.usage.cached_input_tokens,
        total_tokens=result.usage.total_tokens,
        provider_request_id=result.usage.provider_request_id,
        error_category=result.usage.error_category,
        usage_known=result.usage.usage_known,
        node_name=node_name,
        schema_name=schema.__name__,
    )
    telemetry.usages.append(usage)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    telemetry.traces.append(
        {
            "node_name": node_name,
            "status": "ok",
            "started_at": started.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "duration_ms": duration_ms,
            "provider": usage.provider,
            "model": usage.model,
            "schema_name": schema.__name__,
            "usage_index": len(telemetry.usages) - 1,
        }
    )
    return result.data


def build_assistant_graph(
    llm: LLMProvider,
    settings: Settings,
    *,
    entry: str = "intent",
    telemetry: TurnTelemetry | None = None,
):
    """Compile explicit graph: intent → requirements → write → review ⇄ revise → validate."""
    tel = telemetry or TurnTelemetry()

    async def intent_node(state: AgentState) -> AgentState:
        message = state.get("last_user_message") or ""
        result: IntentResult = await _llm_call(
            llm,
            settings,
            state,
            tel,
            system=INTENT_SYSTEM,
            user=message,
            schema=IntentResult,
            node_name="intent",
        )
        style: WritingStyle = result.writing_style or state.get("writing_style") or "professional"  # type: ignore[assignment]
        post_category = result.post_category
        prior_category = state.get("post_category")
        create_intents = {"create_post_draft", "create_scheduled_post"}
        starts_new = bool(result.starts_new_topic)
        job_to_other = prior_category == "job_announcement" and post_category in {
            "educational",
            "general",
            "product_launch",
            "event_announcement",
            "professional_update",
        }
        topic_pivot = bool(
            result.extracted_facts_map.get("topic")
            or result.extracted_facts_map.get("topic_summary")
        ) and prior_category == "job_announcement" and post_category in {
            "educational",
            "general",
        }
        if result.intent_type in create_intents and (
            not prior_category
            or (post_category != prior_category and post_category != "general")
            or job_to_other
            or topic_pivot
        ):
            starts_new = True
        if result.intent_type in {"refine_draft", "clarify"}:
            starts_new = False
            # Preserve established category on same-topic follow-ups classified as general.
            if prior_category and post_category == "general":
                post_category = prior_category

        if starts_new:
            facts = dict(result.extracted_facts_map)
            # Drop prior draft prefs on topic switch, but keep force_* test/debug hooks.
            prior_optional = dict(state.get("optional_preferences") or {})
            optional = {
                key: value
                for key, value in prior_optional.items()
                if key.startswith("force_")
            }
            draft_reset: AgentState = {
                "draft_content": None,
                "suggested_hashtags": [],
                "suggested_skills": [],
                "suggested_responsibilities": [],
                "assumptions": [],
                "review_passed": None,
                "review_issues": [],
                "review_suggestions": [],
                "unsupported_claims": [],
                "missing_required_fields": [],
                "clarification_questions": [],
                "refine_instruction": None,
                "proposed_scheduled_at": None,
                "validation_errors": [],
            }
        else:
            facts = dict(state.get("confirmed_facts") or {})
            facts.update(result.extracted_facts_map)
            optional = dict(state.get("optional_preferences") or {})
            draft_reset = {}

        schedule_text = result.requested_schedule_text
        if starts_new:
            # Do not inherit an old job schedule when pivoting topics.
            pass
        elif not schedule_text:
            schedule_text = state.get("requested_schedule_text")
        # Catch shorthand the model may omit ("after 2mints") so scheduling still works.
        if not schedule_text:
            msg = state.get("last_user_message") or ""
            if re.search(
                r"\b(?:after|in)\s+\d+\s*(?:minutes?|mins?|mints?|m|hours?|hrs?|h|days?|d)\b",
                msg,
                re.IGNORECASE,
            ):
                schedule_text = msg.strip()

        if (
            post_category in {"educational", "general"}
            and "topic" not in facts
            and "topic_summary" not in facts
        ):
            topic_seed = (state.get("last_user_message") or "").strip()
            topic_seed = re.sub(
                r"\b(?:after|in)\s+\d+\s*(?:minutes?|mins?|mints?|m|hours?|hrs?|h|days?|d)\b",
                "",
                topic_seed,
                flags=re.IGNORECASE,
            ).strip(" .")
            if topic_seed:
                facts["topic"] = topic_seed[:240]

        updates: AgentState = {
            "intent_type": result.intent_type,
            "post_category": post_category,
            "confirmed_facts": facts,
            "optional_preferences": optional,
            "requested_schedule_text": schedule_text,
            "writing_style": style,
            "refine_instruction": (
                result.refine_instruction
                if result.intent_type == "refine_draft"
                else (None if starts_new else state.get("refine_instruction"))
            ),
            "current_stage": "requirements",
            "injection_attempt": bool(result.injection_attempt),
            "starts_new_topic": starts_new,
            "response_state": "generating",
            "llm_calls_this_turn": state.get("llm_calls_this_turn") or 0,
            "auto_revision_count": 0,
            "validation_errors": [],
            **draft_reset,
        }
        if result.injection_attempt:
            updates.update(
                {
                    "current_stage": "error",
                    "response_state": "error",
                    "assistant_reply": (
                        "I can help draft LinkedIn content, but I cannot ignore safety "
                        "rules, publish posts, or bypass approvals. Tell me what content "
                        "you'd like to draft."
                    ),
                    "validation_errors": ["prompt_injection_blocked"],
                    "clarification_questions": [],
                }
            )
        return updates

    async def requirements_node(state: AgentState) -> AgentState:
        if state.get("injection_attempt") or state.get("current_stage") == "error":
            return {}

        # Refining an existing draft: keep conversation context; skip re-asking essentials.
        if state.get("intent_type") == "refine_draft" and state.get("draft_content"):
            return {
                "current_stage": "revising",
                "response_state": "generating",
                "assistant_reply": "Updating your draft with the requested changes…",
                "missing_required_fields": [],
                "clarification_questions": [],
                "validation_errors": [],
            }

        category_hint = state.get("post_category") or "general"
        facts_in = dict(state.get("confirmed_facts") or {})
        # Fast path: educational/general with a topic already from intent — skip an
        # extra LLM round-trip so the draft reaches the user sooner.
        if category_hint in {"educational", "general"} and (
            facts_in.get("topic") or facts_in.get("topic_summary")
        ):
            result = RequirementsResult.model_validate(
                {
                    "confirmed_facts": facts_in,
                    "optional_preferences": dict(state.get("optional_preferences") or {}),
                    "missing_required_fields": [],
                    "clarification_questions": [],
                    "ready_to_draft": True,
                }
            )
        else:
            payload = {
                "post_category": state.get("post_category"),
                "confirmed_facts": facts_in,
                "optional_preferences": state.get("optional_preferences") or {},
                "latest_user_message": state.get("last_user_message") or "",
                "requested_schedule_text": state.get("requested_schedule_text"),
                "intent_type": state.get("intent_type"),
                "has_draft": bool(state.get("draft_content")),
                "starts_new_topic": bool(state.get("starts_new_topic")),
            }
            result = await _llm_call(
                llm,
                settings,
                state,
                tel,
                system=REQUIREMENTS_SYSTEM,
                user=json.dumps(payload),
                schema=RequirementsResult,
                node_name="requirements",
            )
        reference_raw = state.get("schedule_reference_at")
        reference_now = None
        if reference_raw:
            try:
                reference_now = datetime.fromisoformat(reference_raw)
            except ValueError:
                reference_now = None
        schedule = parse_schedule_expression(
            state.get("requested_schedule_text"),
            timezone_name=state.get("timezone"),
            now=reference_now,
        )
        proposed_iso = (
            to_utc(schedule.proposed_scheduled_at).isoformat()
            if schedule.proposed_scheduled_at
            else (None if state.get("starts_new_topic") else state.get("proposed_scheduled_at"))
        )
        questions = list(result.clarification_questions)
        missing = list(result.missing_required_fields)
        facts = dict(result.confirmed_facts_map)
        category = state.get("post_category") or "general"
        # Educational / general posts: topic from the user message is enough.
        if category in {"educational", "general"}:
            latest = (state.get("last_user_message") or "").strip()
            if "topic" not in facts and "topic_summary" not in facts and latest:
                facts["topic"] = latest[:240]
            missing = [
                m
                for m in missing
                if m
                not in {
                    "audience_level",
                    "audience",
                    "company",
                    "location_or_remote",
                    "experience",
                    "salary",
                    "role",
                }
                and m not in facts
            ]
            if ("topic" in facts or "topic_summary" in facts) and not any(
                m in {"topic", "topic_summary"} for m in missing
            ):
                missing = [m for m in missing if m not in {"topic", "topic_summary"}]
                questions = []
        if (
            schedule.ambiguous
            and state.get("requested_schedule_text")
            and schedule.reason
            and schedule.reason not in questions
        ):
            questions.append(schedule.reason)

        ready = (result.ready_to_draft or category in {"educational", "general"}) and not missing
        if category in {"educational", "general"} and (
            "topic" in facts or "topic_summary" in facts
        ):
            missing = []
            # Keep only schedule ambiguity questions; drop job-style clarifications.
            schedule_only = (
                [schedule.reason]
                if (
                    schedule.ambiguous
                    and state.get("requested_schedule_text")
                    and schedule.reason
                )
                else []
            )
            questions = schedule_only
            ready = not schedule_only

        if ready:
            reply = "I have enough detail to draft a LinkedIn post. Generating a draft now…"
            stage = "writing"
            response_state = "generating"
        else:
            bullets = "\n".join(f"- {q}" for q in questions[:3])
            reply = (
                "I can draft that — a few details will make it accurate:\n"
                f"{bullets}\n\n"
                "(Draft only — nothing will be scheduled or published yet.)"
            )
            stage = "awaiting_user"
            response_state = "needs_information"

        return {
            "confirmed_facts": facts,
            "optional_preferences": result.optional_preferences_map,
            "missing_required_fields": missing,
            "clarification_questions": questions[:3],
            "proposed_scheduled_at": proposed_iso,
            "current_stage": stage,
            "response_state": response_state,
            "assistant_reply": reply,
            "validation_errors": [],
            "llm_calls_this_turn": state.get("llm_calls_this_turn") or 0,
        }

    async def writing_node(state: AgentState) -> AgentState:
        payload = {
            "post_category": state.get("post_category"),
            "confirmed_facts": state.get("confirmed_facts") or {},
            "optional_preferences": state.get("optional_preferences") or {},
            "writing_style": state.get("writing_style") or "professional",
        }
        result: WritingResult = await _llm_call(
            llm,
            settings,
            state,
            tel,
            system=WRITING_SYSTEM,
            user=json.dumps(payload),
            schema=WritingResult,
            node_name="writing",
        )
        # Never let model-suggested skills become confirmed facts.
        confirmed = dict(state.get("confirmed_facts") or {})
        for key, value in result.confirmed_facts_used_map.items():
            if key.startswith("suggested_"):
                continue
            if key in confirmed or key in (state.get("optional_preferences") or {}):
                confirmed[key] = value
        return {
            "draft_content": result.content,
            "suggested_hashtags": result.suggested_hashtags,
            "suggested_skills": result.suggested_skills,
            "suggested_responsibilities": result.suggested_responsibilities,
            "assumptions": result.assumptions,
            "confirmed_facts": confirmed,
            "current_stage": "reviewing",
            "response_state": "generating",
            "llm_calls_this_turn": state.get("llm_calls_this_turn") or 0,
        }

    async def revise_node(state: AgentState) -> AgentState:
        auto = int(state.get("auto_revision_count") or 0)
        coming_from_failed_review = state.get("review_passed") is False
        payload = {
            "post_category": state.get("post_category"),
            "confirmed_facts": state.get("confirmed_facts") or {},
            "optional_preferences": state.get("optional_preferences") or {},
            "writing_style": state.get("writing_style") or "professional",
            "refine_instruction": state.get("refine_instruction")
            or state.get("last_user_message"),
            "current_draft": state.get("draft_content") or "",
            "review_issues": state.get("review_issues") or [],
            "unsupported_claims": state.get("unsupported_claims") or [],
            "suggested_hashtags": state.get("suggested_hashtags") or [],
        }
        result: WritingResult = await _llm_call(
            llm,
            settings,
            state,
            tel,
            system=REVISION_SYSTEM,
            user=json.dumps(payload),
            schema=WritingResult,
            node_name="revise",
        )
        confirmed = dict(state.get("confirmed_facts") or {})
        updates: AgentState = {
            "draft_content": result.content,
            "suggested_hashtags": (
                result.suggested_hashtags or state.get("suggested_hashtags") or []
            ),
            "suggested_skills": result.suggested_skills
            or state.get("suggested_skills")
            or [],
            "suggested_responsibilities": result.suggested_responsibilities
            or state.get("suggested_responsibilities")
            or [],
            "assumptions": result.assumptions or state.get("assumptions") or [],
            "confirmed_facts": confirmed,
            "current_stage": "reviewing",
            "response_state": "generating",
            "llm_calls_this_turn": state.get("llm_calls_this_turn") or 0,
        }
        if coming_from_failed_review:
            updates["auto_revision_count"] = auto + 1
        return updates

    async def review_node(state: AgentState) -> AgentState:
        payload = {
            "post_category": state.get("post_category"),
            "confirmed_facts": state.get("confirmed_facts") or {},
            "optional_preferences": state.get("optional_preferences") or {},
            "draft_content": state.get("draft_content") or "",
            "suggested_hashtags": state.get("suggested_hashtags") or [],
            "suggested_skills": state.get("suggested_skills") or [],
            "assumptions": state.get("assumptions") or [],
        }
        result: ReviewResult = await _llm_call(
            llm,
            settings,
            state,
            tel,
            system=REVIEW_SYSTEM,
            user=json.dumps(payload),
            schema=ReviewResult,
            node_name="review",
        )
        heuristic = heuristic_unsupported_claims(state)
        unsupported = list(dict.fromkeys([*result.unsupported_claims, *heuristic]))
        issues = list(dict.fromkeys([*result.issues, *heuristic]))
        passed = bool(result.passed) and not heuristic
        # Annotate latest review trace with pass/fail + revision count.
        if tel.traces and tel.traces[-1].get("node_name") == "review":
            tel.traces[-1]["review_passed"] = passed
            tel.traces[-1]["revision_count"] = int(state.get("auto_revision_count") or 0)
        return {
            "review_passed": passed,
            "review_issues": issues,
            "review_suggestions": list(result.suggestions),
            "unsupported_claims": unsupported,
            "current_stage": "revising" if not passed else "validating",
            "response_state": "generating",
            "llm_calls_this_turn": state.get("llm_calls_this_turn") or 0,
        }

    async def validator_node(state: AgentState) -> AgentState:
        errors: list[str] = []
        content = (state.get("draft_content") or "").strip()
        max_len = settings.post_content_max_length
        if not content:
            errors.append("Draft content is empty.")
        if len(content) > max_len:
            errors.append(f"Draft exceeds {max_len} characters.")
        if _PUBLISH_CLAIM.search(content):
            errors.append("Draft must not claim the post was already published or scheduled.")
        if state.get("user_id") is None or state.get("thread_id") is None:
            errors.append("Missing ownership identifiers.")

        review_issues = list(state.get("review_issues") or [])
        unsupported = list(state.get("unsupported_claims") or [])
        review_failed_persistently = (
            state.get("review_passed") is False
            and int(state.get("auto_revision_count") or 0) >= 1
        )

        if errors and not content:
            return {
                "validation_errors": errors,
                "current_stage": "error",
                "response_state": "error",
                "assistant_reply": (
                    "I could not produce a valid draft. " + " ".join(errors)
                ),
            }

        hashtags = state.get("suggested_hashtags") or []
        tag_line = ("\n\n" + " ".join(hashtags)) if hashtags else ""
        skills = state.get("suggested_skills") or []
        skill_note = ""
        if skills:
            skill_note = (
                "\n\nSuggested skills (not confirmed requirements): "
                + ", ".join(skills[:8])
            )

        warnings: list[str] = []
        if review_failed_persistently or unsupported:
            warnings.extend(unsupported or review_issues)
        warnings.extend(errors)

        reply_parts = [
            "Here's a draft LinkedIn post (not scheduled):\n\n",
            f"{content}{tag_line}{skill_note}",
        ]
        if warnings:
            reply_parts.append(
                "\n\nReview notes (advisory — please verify before using):\n"
                + "\n".join(f"- {w}" for w in warnings[:6])
            )
        if state.get("review_suggestions"):
            reply_parts.append(
                "\n\nSuggestions:\n"
                + "\n".join(f"- {s}" for s in (state.get("review_suggestions") or [])[:4])
            )
        proposed = state.get("proposed_scheduled_at")
        zone_name = state.get("timezone")
        if proposed and zone_name:
            try:
                proposed_dt = datetime.fromisoformat(proposed)
                if proposed_dt.tzinfo is None:
                    proposed_dt = proposed_dt.replace(tzinfo=UTC)
                local_dt = proposed_dt.astimezone(ZoneInfo(zone_name))
                time_label = local_dt.strftime("%I:%M %p").lstrip("0")
                ref_raw = state.get("schedule_reference_at")
                same_day = False
                if ref_raw:
                    try:
                        ref_dt = datetime.fromisoformat(str(ref_raw))
                        if ref_dt.tzinfo is None:
                            ref_dt = ref_dt.replace(tzinfo=UTC)
                        same_day = (
                            ref_dt.astimezone(ZoneInfo(zone_name)).date() == local_dt.date()
                        )
                    except (ValueError, ZoneInfoNotFoundError, TypeError):
                        same_day = False
                if same_day:
                    local_label = f"today at {time_label}"
                else:
                    local_label = local_dt.strftime("%b %d, %Y, %I:%M %p").lstrip("0")
                reply_parts.append(
                    f"\n\nProposed schedule (preview only): {local_label} ({zone_name}). "
                    "Use Approve & Schedule to confirm — chat never publishes by itself."
                )
            except (ValueError, ZoneInfoNotFoundError, TypeError):
                reply_parts.append(
                    "\n\nA proposed schedule was detected. Use Approve & Schedule to confirm "
                    "the exact time — chat never publishes by itself."
                )
        reply_parts.append(
            "\n\nYou can rewrite, change tone, or edit this text. "
            "Nothing is scheduled or published from this assistant."
        )

        return {
            "validation_errors": warnings,
            "current_stage": "draft_ready",
            "response_state": "draft_ready",
            "assistant_reply": "".join(reply_parts),
            "review_passed": bool(state.get("review_passed")) and not unsupported,
        }

    def after_intent(state: AgentState) -> Literal["requirements", "end"]:
        if state.get("injection_attempt") or state.get("current_stage") == "error":
            return "end"
        return "requirements"

    def after_requirements(state: AgentState) -> Literal["writing", "revise", "end"]:
        stage = state.get("current_stage")
        if stage == "revising":
            return "revise"
        if stage == "writing":
            return "writing"
        return "end"

    def after_review(state: AgentState) -> Literal["revise", "validator"]:
        if state.get("review_passed"):
            return "validator"
        if int(state.get("auto_revision_count") or 0) < 1:
            return "revise"
        return "validator"

    graph = StateGraph(AgentState)
    graph.add_node("intent", intent_node)
    graph.add_node("requirements", requirements_node)
    graph.add_node("writing", writing_node)
    graph.add_node("revise", revise_node)
    graph.add_node("review", review_node)
    graph.add_node("validator", validator_node)

    if entry == "writing":
        graph.add_edge(START, "writing")
    elif entry == "revise":
        graph.add_edge(START, "revise")
    else:
        graph.add_edge(START, "intent")
        graph.add_conditional_edges(
            "intent",
            after_intent,
            {"requirements": "requirements", "end": END},
        )
        graph.add_conditional_edges(
            "requirements",
            after_requirements,
            {"writing": "writing", "revise": "revise", "end": END},
        )

    graph.add_edge("writing", "review")
    graph.add_edge("revise", "review")
    graph.add_conditional_edges(
        "review",
        after_review,
        {"revise": "revise", "validator": "validator"},
    )
    graph.add_edge("validator", END)
    return graph.compile()


async def run_assistant_turn(
    *,
    llm: LLMProvider,
    settings: Settings,
    state: AgentState,
    entry: str = "intent",
    request_received_at: datetime | None = None,
) -> tuple[AgentState, TurnTelemetry]:
    """Execute one user turn through the compiled graph and merge final state."""
    working: AgentState = dict(state)  # type: ignore[assignment]
    working["llm_calls_this_turn"] = 0
    # Relative schedules ("after 5 minutes") resolve from this server timestamp.
    reference = request_received_at or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    working["schedule_reference_at"] = reference.isoformat()
    if entry in {"writing", "revise"}:
        working["auto_revision_count"] = 0
    telemetry = TurnTelemetry()
    try:
        graph = build_assistant_graph(llm, settings, entry=entry, telemetry=telemetry)
        result = await graph.ainvoke(working)
        return result, telemetry  # type: ignore[return-value]
    except LLMError as exc:
        merged = dict(working)
        # Preserve prior draft / facts on provider failure — do not wipe graph memory.
        merged.update(
            {
                "current_stage": "error",
                "response_state": "error" if exc.code != "llm_unavailable" else "unavailable",
                "assistant_reply": exc.message,
                "validation_errors": [exc.code],
            }
        )
        return merged, telemetry  # type: ignore[return-value]
