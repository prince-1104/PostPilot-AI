"""LangGraph StateGraph for Phase 5A/5B content drafting (no schedule/publish)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal, TypedDict
from uuid import UUID

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
    llm_calls_this_turn: int
    force_path: str | None  # "writing" | "revise" | None
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
        "suggested_skills": [],
        "suggested_responsibilities": [],
        "assumptions": [],
        "validation_errors": [],
        "review_issues": [],
        "review_suggestions": [],
        "unsupported_claims": [],
        "writing_style": "professional",
        "auto_revision_count": 0,
        "llm_calls_this_turn": 0,
        "current_stage": "intent",
        "response_state": "generating",
        "injection_attempt": False,
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
        llm_calls_this_turn=int(state.get("llm_calls_this_turn") or 0),
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
        "llm_calls_this_turn": 0,  # reset each HTTP turn
        "current_stage": data.current_stage,
        "validation_errors": list(data.validation_errors),
        "last_user_message": data.last_user_message,
        "assistant_reply": data.assistant_reply,
        "response_state": data.response_state,
        "injection_attempt": data.injection_attempt,
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
    *,
    system: str,
    user: str,
    schema: type,
) -> Any:
    calls = int(state.get("llm_calls_this_turn") or 0)
    if calls >= settings.ai_max_llm_calls_per_turn:
        raise LLMError(
            "This turn exceeded the AI request budget. Please send a shorter follow-up.",
            code="llm_budget_exceeded",
        )
    state["llm_calls_this_turn"] = calls + 1
    return await llm.complete_structured(system=system, user=user, schema=schema)


def build_assistant_graph(llm: LLMProvider, settings: Settings, *, entry: str = "intent"):
    """Compile explicit graph: intent → requirements → write → review ⇄ revise → validate."""

    async def intent_node(state: AgentState) -> AgentState:
        message = state.get("last_user_message") or ""
        result: IntentResult = await _llm_call(
            llm,
            settings,
            state,
            system=INTENT_SYSTEM,
            user=message,
            schema=IntentResult,
        )
        facts = dict(state.get("confirmed_facts") or {})
        facts.update(result.extracted_facts_map)
        style: WritingStyle = result.writing_style or state.get("writing_style") or "professional"  # type: ignore[assignment]
        # Preserve an established category on follow-ups that classify as "general".
        post_category = result.post_category
        if (
            state.get("post_category")
            and post_category == "general"
            and result.intent_type not in {"unsupported"}
        ):
            post_category = state.get("post_category")
        updates: AgentState = {
            "intent_type": result.intent_type,
            "post_category": post_category,
            "confirmed_facts": facts,
            "requested_schedule_text": result.requested_schedule_text
            or state.get("requested_schedule_text"),
            "writing_style": style,
            "refine_instruction": result.refine_instruction or state.get("refine_instruction"),
            "current_stage": "requirements",
            "injection_attempt": result.injection_attempt,
            "response_state": "generating",
            "llm_calls_this_turn": state.get("llm_calls_this_turn") or 0,
            "auto_revision_count": 0,
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

        # Refining an existing draft: keep conversation context; skip re-asking essentials.
        if state.get("intent_type") == "refine_draft" and state.get("draft_content"):
            return {
                "current_stage": "revising",
                "response_state": "generating",
                "assistant_reply": "Updating your draft with the requested changes…",
                "missing_required_fields": [],
                "clarification_questions": [],
            }

        payload = {
            "post_category": state.get("post_category"),
            "confirmed_facts": state.get("confirmed_facts") or {},
            "optional_preferences": state.get("optional_preferences") or {},
            "latest_user_message": state.get("last_user_message") or "",
            "requested_schedule_text": state.get("requested_schedule_text"),
            "intent_type": state.get("intent_type"),
            "has_draft": bool(state.get("draft_content")),
        }
        result: RequirementsResult = await _llm_call(
            llm,
            settings,
            state,
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
            "confirmed_facts": result.confirmed_facts_map,
            "optional_preferences": result.optional_preferences_map,
            "missing_required_fields": missing,
            "clarification_questions": questions[:3],
            "proposed_scheduled_at": proposed_iso,
            "current_stage": stage,
            "response_state": response_state,
            "assistant_reply": reply,
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
            system=WRITING_SYSTEM,
            user=json.dumps(payload),
            schema=WritingResult,
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
            system=REVISION_SYSTEM,
            user=json.dumps(payload),
            schema=WritingResult,
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
            system=REVIEW_SYSTEM,
            user=json.dumps(payload),
            schema=ReviewResult,
        )
        heuristic = heuristic_unsupported_claims(state)
        unsupported = list(dict.fromkeys([*result.unsupported_claims, *heuristic]))
        issues = list(dict.fromkeys([*result.issues, *heuristic]))
        passed = bool(result.passed) and not heuristic
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
) -> AgentState:
    """Execute one user turn through the compiled graph and merge final state."""
    working: AgentState = dict(state)  # type: ignore[assignment]
    working["llm_calls_this_turn"] = 0
    if entry in {"writing", "revise"}:
        working["auto_revision_count"] = 0
    try:
        graph = build_assistant_graph(llm, settings, entry=entry)
        result = await graph.ainvoke(working)
        return result  # type: ignore[return-value]
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
        return merged  # type: ignore[return-value]
