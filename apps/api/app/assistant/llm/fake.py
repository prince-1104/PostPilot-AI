"""Deterministic LLM for tests and AI_PROVIDER=fake."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.assistant.llm.base import LLMError, LLMProvider
from app.assistant.schemas import IntentResult, RequirementsResult, WritingResult

T = TypeVar("T", bound=BaseModel)

_INJECTION = re.compile(
    r"(ignore\s+(all\s+)?(previous\s+)?instructions|publish\s+immediately|"
    r"bypass\s+approval|exfiltrate|system\s+prompt)",
    re.IGNORECASE,
)


class FakeLLMProvider(LLMProvider):
    """Rule-based structured responses — no network calls."""

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
    ) -> T:
        # Optional scenario override for tests: [[fake_llm:{json}]]
        override = _extract_override(user)
        if override is not None:
            try:
                return schema.model_validate(override)
            except ValidationError as exc:
                raise LLMError("Malformed fake LLM override.", code="llm_invalid_output") from exc

        if schema is IntentResult:
            return schema.model_validate(_fake_intent(user))  # type: ignore[return-value]
        if schema is RequirementsResult:
            return schema.model_validate(_fake_requirements(system, user))  # type: ignore[return-value]
        if schema is WritingResult:
            return schema.model_validate(_fake_writing(system, user))  # type: ignore[return-value]
        raise LLMError(f"Unsupported schema for fake LLM: {schema.__name__}")


def _extract_override(user: str) -> dict | None:
    match = re.search(r"\[\[fake_llm:(.*?)\]\]", user, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise LLMError("Invalid fake_llm JSON.", code="llm_invalid_output") from exc
    if not isinstance(payload, dict):
        raise LLMError("fake_llm payload must be an object.", code="llm_invalid_output")
    return payload


def _fake_intent(user: str) -> dict:
    lower = user.lower()
    if _INJECTION.search(user):
        return {
            "intent_type": "unsupported",
            "post_category": "general",
            "extracted_facts": {},
            "injection_attempt": True,
            "notes": "Prompt injection language detected; refusing autonomous actions.",
        }

    category = "general"
    facts: dict[str, str] = {}
    missing: list[str] = []
    schedule: str | None = None

    if "job" in lower or "hiring" in lower or "engineer" in lower:
        category = "job_announcement"
        role_match = re.search(
            r"(?:for|role|position|hiring(?:\s+an?)?)\s+([A-Za-z0-9 /+#-]+?)"
            r"(?:\s+at\s+\d|\s+at\s+(?:our|the)\b|\s+on\s|,|\.|$)",
            user,
            re.IGNORECASE,
        )
        if role_match:
            facts["role"] = role_match.group(1).strip()
        elif "ai engineer" in lower:
            facts["role"] = "AI Engineer"
        elif re.search(r"\b([A-Za-z]+(?:\s+[A-Za-z]+)?\s+Engineer)\b", user):
            eng = re.search(r"\b([A-Za-z]+(?:\s+[A-Za-z]+)?\s+Engineer)\b", user)
            if eng:
                facts["role"] = eng.group(1).strip()
        missing.extend(["company", "location_or_remote", "experience"])
        missing = [m for m in missing if m not in facts]
    elif "product" in lower or "launch" in lower:
        category = "product_launch"
        missing.extend(["product_name", "key_features", "audience"])
    elif "learn" in lower or "educat" in lower or "tip" in lower:
        category = "educational"
        missing.extend(["topic", "audience_level"])
    elif "event" in lower or "webinar" in lower or "meetup" in lower:
        category = "event_announcement"
        missing.extend(["event_name", "event_time", "audience"])
    elif "update" in lower or "joined" in lower or "promoted" in lower:
        category = "professional_update"
        missing.append("update_summary")

    time_match = re.search(
        r"(today|tomorrow|next\s+\w+day|november\s+\d{1,2}|[\d]{1,2}\s*(?:am|pm)|"
        r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        user,
        re.IGNORECASE,
    )
    if time_match or re.search(r"\d{1,2}\s*(?:am|pm)", lower):
        schedule = user.strip()

    if "company" in lower:
        co = re.search(r"company(?:\s+is|\s*:)?\s+([A-Za-z0-9 .&'-]+)", user, re.IGNORECASE)
        if co:
            facts["company"] = co.group(1).strip(" .")
            missing = [m for m in missing if m != "company"]
    if "remote" in lower:
        facts["location_or_remote"] = "Remote"
        missing = [m for m in missing if m != "location_or_remote"]
    if re.search(r"\d\+?\s*years?", lower):
        exp = re.search(r"(\d\+?\s*years?[^\.,]*)", user, re.IGNORECASE)
        if exp:
            facts["experience"] = exp.group(1).strip()
            missing = [m for m in missing if m != "experience"]

    return {
        "intent_type": "create_post_draft",
        "post_category": category,
        "extracted_facts": facts,
        "requested_schedule_text": schedule,
        "missing_hints": missing,
        "injection_attempt": False,
    }


def _fake_requirements(system: str, user: str) -> dict:
    # Context is embedded in the user payload as JSON when the graph calls us.
    context: dict = {}
    try:
        context = json.loads(user)
    except json.JSONDecodeError:
        context = {"latest_user_message": user}

    facts = dict(context.get("confirmed_facts") or {})
    optional = dict(context.get("optional_preferences") or {})
    category = context.get("post_category") or "general"
    latest = str(context.get("latest_user_message") or "")

    # Merge new answers from free text.
    for key, pattern in (
        ("company", r"company(?:\s+is|\s*:)?\s+([A-Za-z0-9 .&'-]+)"),
        ("location_or_remote", r"(remote|hybrid|on-?site|[A-Za-z]+,\s*[A-Z]{2})"),
        ("experience", r"(\d\+?\s*years?[^\.,]*)"),
        ("salary", r"salary(?:\s+is|\s*:)?\s+([^\.\n]+)"),
        ("product_name", r"product(?:\s+is|\s*:)?\s+([A-Za-z0-9 .&'-]+)"),
        ("topic", r"topic(?:\s+is|\s*:)?\s+([^\.\n]+)"),
    ):
        match = re.search(pattern, latest, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .")
            if key == "salary":
                optional[key] = value
            else:
                facts[key] = value

    required_by_category = {
        "job_announcement": ["role", "company", "location_or_remote", "experience"],
        "product_launch": ["product_name", "key_features", "audience"],
        "educational": ["topic", "audience_level"],
        "event_announcement": ["event_name", "event_time", "audience"],
        "professional_update": ["update_summary"],
        "general": ["topic_summary"],
    }
    required = required_by_category.get(str(category), ["topic_summary"])
    # Seed role from prior intent facts if present.
    for k, v in (context.get("confirmed_facts") or {}).items():
        facts.setdefault(k, v)

    if category == "general" and latest and "topic_summary" not in facts:
        facts["topic_summary"] = latest[:240]

    missing = [field for field in required if field not in facts or not str(facts[field]).strip()]
    questions_map = {
        "company": "Which company is hiring for this role?",
        "location_or_remote": "Is the role remote, hybrid, or on-site (and where)?",
        "experience": "What experience level is required?",
        "role": "What is the exact job title?",
        "product_name": "What is the product name?",
        "key_features": "What are the key features or benefits to highlight?",
        "audience": "Who is the primary audience?",
        "topic": "What topic should the post cover?",
        "audience_level": "What level is the audience (beginner, intermediate, advanced)?",
        "event_name": "What is the event name?",
        "event_time": "When does the event take place?",
        "update_summary": "What professional update should we announce?",
        "topic_summary": "What should this LinkedIn post be about?",
    }
    questions = [questions_map[m] for m in missing if m in questions_map][:3]
    return {
        "confirmed_facts": facts,
        "optional_preferences": optional,
        "missing_required_fields": missing,
        "clarification_questions": questions,
        "ready_to_draft": len(missing) == 0,
    }


def _fake_writing(system: str, user: str) -> dict:
    try:
        context = json.loads(user)
    except json.JSONDecodeError:
        context = {}
    facts = dict(context.get("confirmed_facts") or {})
    category = context.get("post_category") or "general"
    optional = dict(context.get("optional_preferences") or {})

    if category == "job_announcement":
        role = facts.get("role", "the open role")
        company = facts.get("company", "our team")
        location = facts.get("location_or_remote", "location TBD")
        experience = facts.get("experience", "relevant experience")
        salary_line = (
            f"\nCompensation (shared by requester): {optional['salary']}\n"
            if optional.get("salary")
            else ""
        )
        content = (
            f"We're hiring: {role} at {company}\n\n"
            f"Location: {location}\n"
            f"Experience: {experience}\n"
            f"{salary_line}\n"
            "If this matches your background, feel free to connect or comment for details.\n\n"
            "#Hiring #Jobs #LinkedIn"
        )
        tags = ["#Hiring", "#Jobs", "#Careers"]
        if "ai" in role.lower():
            tags.append("#AI")
    elif category == "product_launch":
        name = facts.get("product_name", "our product")
        features = facts.get("key_features", "new capabilities")
        audience = facts.get("audience", "professionals")
        content = (
            f"Excited to share {name}.\n\n"
            f"Highlights: {features}\n"
            f"Built for: {audience}\n\n"
            "#ProductLaunch #Innovation"
        )
        tags = ["#ProductLaunch", "#Innovation"]
    else:
        summary = facts.get("topic_summary") or facts.get("topic") or facts.get(
            "update_summary", "an update"
        )
        content = f"{summary}\n\nCurious to hear your thoughts.\n\n#LinkedIn #Professional"
        tags = ["#LinkedIn", "#Professional"]

    content = content.strip()[:3000]
    return {
        "content": content,
        "suggested_hashtags": tags,
        "confirmed_facts_used": facts,
        "assumptions": [
            "Tone and structure are AI suggestions; only listed facts were treated as confirmed."
        ],
        "missing_information": [],
        "quality_warnings": [],
    }
