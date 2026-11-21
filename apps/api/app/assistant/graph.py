"""LangGraph StateGraph for Phase 5A content drafting (no schedule/publish side effects)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.assistant.llm.base import LLMError, LLMProvider
from app.assistant.prompts import INTENT_SYSTEM, REQUIREMENTS_SYSTEM, WRITING_SYSTEM
from app.assistant.schedule_parse import parse_schedule_expression, to_utc
from app.assistant.schemas import (
    GraphSnapshot,
    IntentResult,
    RequirementsResult,
    WritingResult,
)
from app.core.config import Settings


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
    proposed_scheduled_at: str | None  # ISO UTC
    draft_content: str | None
    suggested_hashtags: list[str]
    assumptions: list[str]
    current_stage: str
    validation_errors: list[str]
    assistant_reply: str | None
    response_state: str
    injection_attempt: bool


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
        "assumptions": [],
        "validation_errors": [],
        "current_stage": "intent",
        "response_state": "generating",
        "injection_attempt": False,
    }


def snapshot_from_state(state: AgentState) -> GraphSnapshot:
    proposed = state.get("proposed_scheduled_at")
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
        assumptions=list(state.get("assumptions") or []),
        current_stage=state.get("current_stage") or "intent",  # type: ignore[arg-type]
        validation_errors=list(state.get("validation_errors") or []),
        last_user_message=state.get("last_user_message"),
        assistant_reply=state.get("assistant_reply"),
        response_state=state.get("response_state") or "generating",  # type: ignore[arg-type]
        injection_attempt=bool(state.get("injection_attempt")),
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
        "assumptions": list(data.assumptions),
        "current_stage": data.current_stage,
        "validation_errors": list(data.validation_errors),
        "last_user_message": data.last_user_message,
        "assistant_reply": data.assistant_reply,
        "response_state": data.response_state,
        "injection_attempt": data.injection_attempt,
    }


def build_assistant_graph(llm: LLMProvider, settings: Settings):
    """Compile an explicit branching graph: intent → requirements → (ask | write → validate)."""

    async def intent_node(state: AgentState) -> AgentState:
        message = state.get("last_user_message") or ""
        result = await llm.complete_structured(
            system=INTENT_SYSTEM,
            user=message,
            schema=IntentResult,
        )
        facts = dict(state.get("confirmed_facts") or {})
        facts.update({k: v for k, v in result.extracted_facts.items() if v})
        updates: AgentState = {
            "intent_type": result.intent_type,
            "post_category": result.post_category,
            "confirmed_facts": facts,
            "requested_schedule_text": result.requested_schedule_text
            or state.get("requested_schedule_text"),
            "current_stage": "requirements",
            "injection_attempt": result.injection_attempt,
            "response_state": "generating",
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
                }
            )
        return updates

    async def requirements_node(state: AgentState) -> AgentState:
        if state.get("injection_attempt") or state.get("current_stage") == "error":
            return {}
        payload = {
            "post_category": state.get("post_category"),
            "confirmed_facts": state.get("confirmed_facts") or {},
            "optional_preferences": state.get("optional_preferences") or {},
            "latest_user_message": state.get("last_user_message") or "",
            "requested_schedule_text": state.get("requested_schedule_text"),
        }
        result = await llm.complete_structured(
            system=REQUIREMENTS_SYSTEM,
            user=json.dumps(payload),
            schema=RequirementsResult,
        )
        schedule = parse_schedule_expression(
            state.get("requested_schedule_text"),
            timezone_name=state.get("timezone"),
        )
        proposed_iso = (
            to_utc(schedule.proposed_scheduled_at).isoformat()
            if schedule.proposed_scheduled_at
            else state.get("proposed_scheduled_at")
        )
        questions = list(result.clarification_questions)
        missing = list(result.missing_required_fields)
        # Schedule ambiguity does not block drafting; proposed time stays null.
        if (
            schedule.ambiguous
            and state.get("requested_schedule_text")
            and schedule.reason
            and schedule.reason not in questions
        ):
            questions.append(schedule.reason)

        if result.ready_to_draft and not missing:
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
            "confirmed_facts": result.confirmed_facts,
            "optional_preferences": result.optional_preferences,
            "missing_required_fields": missing,
            "clarification_questions": questions[:3],
            "proposed_scheduled_at": proposed_iso,
            "current_stage": stage,
            "response_state": response_state,
            "assistant_reply": reply,
        }

    async def writing_node(state: AgentState) -> AgentState:
        payload = {
            "post_category": state.get("post_category"),
            "confirmed_facts": state.get("confirmed_facts") or {},
            "optional_preferences": state.get("optional_preferences") or {},
        }
        result = await llm.complete_structured(
            system=WRITING_SYSTEM,
            user=json.dumps(payload),
            schema=WritingResult,
        )
        return {
            "draft_content": result.content,
            "suggested_hashtags": result.suggested_hashtags,
            "assumptions": result.assumptions,
            "confirmed_facts": {
                **(state.get("confirmed_facts") or {}),
                **result.confirmed_facts_used,
            },
            "current_stage": "validating",
            "response_state": "generating",
        }

    async def validator_node(state: AgentState) -> AgentState:
        errors: list[str] = []
        content = (state.get("draft_content") or "").strip()
        max_len = settings.post_content_max_length
        if not content:
            errors.append("Draft content is empty.")
        if len(content) > max_len:
            errors.append(f"Draft exceeds {max_len} characters.")
        # Hard boundary: graph must never claim publish/schedule execution.
        banned = ("has been published", "scheduled successfully", "posted to linkedin")
        lower = content.lower()
        if any(token in lower for token in banned):
            errors.append("Draft must not claim the post was already published or scheduled.")
        if state.get("user_id") is None or state.get("thread_id") is None:
            errors.append("Missing ownership identifiers.")

        if errors:
            return {
                "validation_errors": errors,
                "current_stage": "error",
                "response_state": "error",
                "assistant_reply": (
                    "I generated a draft but it failed validation. "
                    + " ".join(errors)
                    + " Please adjust the details and try again."
                ),
            }

        hashtags = state.get("suggested_hashtags") or []
        tag_line = (" " + " ".join(hashtags)) if hashtags else ""
        reply = (
            "Here's a draft LinkedIn post (not scheduled):\n\n"
            f"{content}{tag_line}\n\n"
            "You can edit this text. Phase 5A does not schedule or publish — "
            "use the normal Posts flow when you're ready."
        )
        return {
            "validation_errors": [],
            "current_stage": "draft_ready",
            "response_state": "draft_ready",
            "assistant_reply": reply,
        }

    def after_requirements(state: AgentState) -> Literal["writing", "end"]:
        if state.get("current_stage") == "writing":
            return "writing"
        return "end"

    def after_intent(state: AgentState) -> Literal["requirements", "end"]:
        if state.get("injection_attempt") or state.get("current_stage") == "error":
            return "end"
        return "requirements"

    graph = StateGraph(AgentState)
    graph.add_node("intent", intent_node)
    graph.add_node("requirements", requirements_node)
    graph.add_node("writing", writing_node)
    graph.add_node("validator", validator_node)

    graph.add_edge(START, "intent")
    graph.add_conditional_edges(
        "intent",
        after_intent,
        {"requirements": "requirements", "end": END},
    )
    graph.add_conditional_edges(
        "requirements",
        after_requirements,
        {"writing": "writing", "end": END},
    )
    graph.add_edge("writing", "validator")
    graph.add_edge("validator", END)
    return graph.compile()


async def run_assistant_turn(
    *,
    llm: LLMProvider,
    settings: Settings,
    state: AgentState,
) -> AgentState:
    """Execute one user turn through the compiled graph and merge final state."""
    try:
        graph = build_assistant_graph(llm, settings)
        result = await graph.ainvoke(state)
        return result  # type: ignore[return-value]
    except LLMError as exc:
        merged = dict(state)
        merged.update(
            {
                "current_stage": "error",
                "response_state": "error" if exc.code != "llm_unavailable" else "unavailable",
                "assistant_reply": exc.message,
                "validation_errors": [exc.code],
            }
        )
        return merged  # type: ignore[return-value]
