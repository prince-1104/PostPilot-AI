"""Deterministic LLM for tests and AI_PROVIDER=fake."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.assistant.llm.base import LLMError, LLMProvider
from app.assistant.schemas import (
    IntentResult,
    RequirementsResult,
    ReviewResult,
    WritingResult,
)
from app.observability.usage import LLMResult, LLMUsage

T = TypeVar("T", bound=BaseModel)

_INJECTION = re.compile(
    r"(ignore\s+(all\s+)?(previous\s+)?instructions|publish\s+immediately|"
    r"bypass\s+approval|exfiltrate|system\s+prompt)",
    re.IGNORECASE,
)
_REFINE = re.compile(
    r"\b(make it shorter|more professional|rewrite|regenerate|remove (the )?salary|"
    r"add hashtags|remove hashtags|change (the )?tone|shorter|more concise|"
    r"more detailed|more conversational|more promotional)\b",
    re.IGNORECASE,
)


def _fake_usage(*, schema: type[BaseModel], success: bool = True) -> LLMUsage:
    """Fake provider does not report real tokens — mark usage unknown."""
    return LLMUsage(
        provider="fake",
        model="fake-model",
        success=success,
        latency_ms=0.0,
        usage_known=False,
        schema_name=schema.__name__,
    )


class FakeLLMProvider(LLMProvider):
    """Rule-based structured responses — no network calls."""

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
    ) -> LLMResult[T]:
        override = _extract_override(user)
        if override is not None:
            try:
                return LLMResult(
                    data=schema.model_validate(override),
                    usage=_fake_usage(schema=schema),
                )
            except ValidationError as exc:
                raise LLMError("Malformed fake LLM override.", code="llm_invalid_output") from exc

        if schema is IntentResult:
            data = schema.model_validate(_fake_intent(user))
        elif schema is RequirementsResult:
            data = schema.model_validate(_fake_requirements(user))
        elif schema is WritingResult:
            data = schema.model_validate(_fake_writing(system, user))
        elif schema is ReviewResult:
            data = schema.model_validate(_fake_review(user))
        else:
            raise LLMError(f"Unsupported schema for fake LLM: {schema.__name__}")
        return LLMResult(data=data, usage=_fake_usage(schema=schema))  # type: ignore[arg-type]


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

    if _REFINE.search(user):
        style = "professional"
        if "conversational" in lower:
            style = "conversational"
        elif "concise" in lower or "shorter" in lower:
            style = "concise"
        elif "detailed" in lower:
            style = "detailed"
        elif "promotional" in lower:
            style = "promotional"
        elif "professional" in lower:
            style = "professional"
        return {
            "intent_type": "refine_draft",
            "post_category": "general",
            "extracted_facts": {},
            "injection_attempt": False,
            "writing_style": style,
            "refine_instruction": user.strip()[:500],
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
        co = re.search(r"company(?:\s+is|\s*:)?\s+([A-Za-z0-9 &'-]+)", user, re.IGNORECASE)
        if co:
            facts["company"] = co.group(1).strip(" .")
            missing = [m for m in missing if m != "company"]
    if "remote" in lower or "bangalore" in lower or "location" in lower:
        loc = re.search(
            r"(remote|hybrid|on-?site|bangalore|[A-Za-z]+,\s*[A-Z]{2})",
            user,
            re.IGNORECASE,
        )
        if loc:
            facts["location_or_remote"] = loc.group(1).strip()
            missing = [m for m in missing if m != "location_or_remote"]
    if re.search(r"\d\+?\s*[-]?\s*\d*\s*years?", lower):
        exp = re.search(r"(\d\+?\s*[-]?\s*\d*\s*years?[^\.,]*)", user, re.IGNORECASE)
        if exp:
            facts["experience"] = exp.group(1).strip()
            missing = [m for m in missing if m != "experience"]
    if "python" in lower or "fastapi" in lower or "rag" in lower:
        skills = []
        for token in ("Python", "FastAPI", "RAG", "LLM"):
            if token.lower() in lower:
                skills.append(token)
        if skills:
            facts["confirmed_skills"] = ", ".join(skills)

    style = "professional"
    for candidate in ("conversational", "concise", "detailed", "promotional", "professional"):
        if candidate in lower:
            style = candidate
            break

    return {
        "intent_type": "create_post_draft",
        "post_category": category,
        "extracted_facts": facts,
        "requested_schedule_text": schedule,
        "missing_hints": missing,
        "injection_attempt": False,
        "writing_style": style,
    }


def _fake_requirements(user: str) -> dict:
    context: dict = {}
    try:
        context = json.loads(user)
    except json.JSONDecodeError:
        context = {"latest_user_message": user}

    if context.get("intent_type") == "refine_draft" and context.get("has_draft"):
        return {
            "confirmed_facts": dict(context.get("confirmed_facts") or {}),
            "optional_preferences": dict(context.get("optional_preferences") or {}),
            "missing_required_fields": [],
            "clarification_questions": [],
            "ready_to_draft": True,
        }

    facts = dict(context.get("confirmed_facts") or {})
    optional = dict(context.get("optional_preferences") or {})
    category = context.get("post_category") or "general"
    latest = str(context.get("latest_user_message") or "")

    for key, pattern in (
        ("company", r"company(?:\s+is|\s*:)?\s+([A-Za-z0-9 &'-]+)"),
        ("location_or_remote", r"(remote|hybrid|on-?site|bangalore|[A-Za-z]+,\s*[A-Z]{2})"),
        ("experience", r"(\d\+?\s*[-]?\s*\d*\s*years?[^\.,]*)"),
        ("salary", r"salary(?:\s+is|\s*:)?\s+([^\.\n]+)"),
        ("product_name", r"product(?:\s+is|\s*:)?\s+([A-Za-z0-9 &'-]+)"),
        ("topic", r"topic(?:\s+is|\s*:)?\s+([^\.\n]+)"),
        ("confirmed_skills", r"(python|fastapi|rag|llm)[^\.\n]*"),
    ):
        match = re.search(pattern, latest, re.IGNORECASE)
        if match:
            value = match.group(0 if key == "confirmed_skills" else 1).strip(" .")
            if key == "salary":
                optional[key] = value
            else:
                facts[key] = value

    # Compact "Company: X. Location: Y." style answers
    for key, pattern in (
        ("company", r"Company:\s*([^.\n]+)"),
        ("location_or_remote", r"Location:\s*([^.\n]+)"),
        ("experience", r"Experience:\s*([^.\n]+)"),
    ):
        match = re.search(pattern, latest, re.IGNORECASE)
        if match:
            facts[key] = match.group(1).strip()

    required_by_category = {
        "job_announcement": ["role", "company", "location_or_remote", "experience"],
        "product_launch": ["product_name", "key_features", "audience"],
        "educational": ["topic", "audience_level"],
        "event_announcement": ["event_name", "event_time", "audience"],
        "professional_update": ["update_summary"],
        "general": ["topic_summary"],
    }
    required = required_by_category.get(str(category), ["topic_summary"])
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
    style = str(context.get("writing_style") or "professional")
    instruction = str(context.get("refine_instruction") or "")
    current = str(context.get("current_draft") or "")
    force_bad = str(optional.get("force_bad_draft") or "")
    unsupported = context.get("unsupported_claims") or []

    suggested_skills = [
        "Python/FastAPI",
        "LLM integration",
        "RAG systems",
        "Model evaluation",
        "Cloud deployment",
        "Monitoring and observability",
    ]
    suggested_responsibilities = [
        "Design and ship AI features",
        "Collaborate with product and platform teams",
    ]

    if "revision" in system.lower() or current:
        content = current or "Draft placeholder."
        if "shorter" in instruction.lower() or style == "concise":
            # Keep confirmed company/role lines; trim fluff.
            lines = [ln for ln in content.splitlines() if ln.strip()]
            content = "\n".join(lines[:6])
            if facts.get("company") and facts["company"] not in content:
                content = f"{facts.get('role', 'Role')} at {facts['company']}\n" + content
        if "remove" in instruction.lower() and "salary" in instruction.lower():
            content = re.sub(
                r".{0,40}(\$\s?\d|salary|compensation|CTC).{0,40}\n?",
                "",
                content,
                flags=re.IGNORECASE,
            )
        if unsupported or force_bad == "salary":
            # Strip invented salary/URLs during auto-revision.
            content = re.sub(
                r".{0,40}(\$\s?\d|salary|compensation|CTC|https?://\S+).{0,40}\n?",
                "",
                content,
                flags=re.IGNORECASE,
            )
        # Intentionally do not strip UNFIXABLE_CLAIM — models persistent review failure.
        if "professional" in instruction.lower() or style == "professional":
            content = content.replace("Excited!!!", "We're pleased to share")
        if "hashtag" in instruction.lower():
            if "remove" in instruction.lower():
                content = re.sub(r"#\w+", "", content)
            else:
                content = content.rstrip() + "\n\n#Hiring #AI"
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        tags = ["#Hiring", "#AI"] if category == "job_announcement" else ["#LinkedIn"]
        if "remove hashtags" in instruction.lower():
            tags = []
        return {
            "content": content[:3000],
            "suggested_hashtags": tags,
            "confirmed_facts_used": facts,
            "assumptions": ["Revised from prior draft; suggestions remain non-binding."],
            "missing_information": [],
            "quality_warnings": [],
            "suggested_skills": suggested_skills if category == "job_announcement" else [],
            "suggested_responsibilities": (
                suggested_responsibilities if category == "job_announcement" else []
            ),
        }

    if category == "job_announcement":
        role = facts.get("role", "the open role")
        company = facts.get("company", "our team")
        location = facts.get("location_or_remote", "location TBD")
        experience = facts.get("experience", "relevant experience")
        skills = facts.get("confirmed_skills", "")
        salary_line = ""
        if optional.get("salary"):
            salary_line = f"\nCompensation (shared by requester): {optional['salary']}\n"
        elif force_bad == "salary":
            salary_line = (
                "\nSalary: $250,000 + unlimited PTO (unverified)\n"
                "Apply at https://evil.example/apply\n"
            )
        elif force_bad == "unfixable":
            salary_line = "\nUNFIXABLE_CLAIM: guaranteed FAANG offer\n"
        skills_line = f"\nConfirmed skills: {skills}\n" if skills else ""
        intro = {
            "professional": f"We're hiring: {role} at {company}",
            "conversational": f"Hey network — {company} is looking for a {role}",
            "concise": f"Hiring: {role} @ {company}",
            "detailed": f"{company} is hiring a {role}. Here are the details we can confirm:",
            "promotional": f"Opportunity alert: join {company} as a {role}",
        }.get(style, f"We're hiring: {role} at {company}")
        content = (
            f"{intro}\n\n"
            f"Location: {location}\n"
            f"Experience: {experience}\n"
            f"{skills_line}{salary_line}\n"
            "Suggested technical focus areas (not mandatory requirements unless confirmed): "
            "Python/FastAPI, LLM integration, RAG systems.\n\n"
            "If this matches your background, feel free to connect or comment for details."
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
        suggested_skills = []
        suggested_responsibilities = []
    else:
        summary = facts.get("topic_summary") or facts.get("topic") or facts.get(
            "update_summary", "an update"
        )
        content = f"{summary}\n\nCurious to hear your thoughts.\n\n#LinkedIn #Professional"
        tags = ["#LinkedIn", "#Professional"]
        suggested_skills = []
        suggested_responsibilities = []

    return {
        "content": content.strip()[:3000],
        "suggested_hashtags": tags,
        "confirmed_facts_used": facts,
        "assumptions": [
            "Tone and structure are AI suggestions; only listed facts were treated as confirmed.",
            "Suggested skills are ideas, not confirmed hiring requirements.",
        ],
        "missing_information": [],
        "quality_warnings": [],
        "suggested_skills": suggested_skills if category == "job_announcement" else [],
        "suggested_responsibilities": (
            suggested_responsibilities if category == "job_announcement" else []
        ),
    }


def _fake_review(user: str) -> dict:
    try:
        context = json.loads(user)
    except json.JSONDecodeError:
        context = {}
    content = str(context.get("draft_content") or "")
    facts = dict(context.get("confirmed_facts") or {})
    optional = dict(context.get("optional_preferences") or {})
    known = " ".join(f"{k} {v}" for k, v in {**facts, **optional}.items()).lower()

    unsupported: list[str] = []
    issues: list[str] = []
    if (
        re.search(r"\$\s?\d|salary|compensation|CTC", content, re.IGNORECASE)
        and "salary" not in known
        and "compensation" not in known
    ):
        unsupported.append("Invented or unconfirmed salary/compensation claim")
        issues.append("Draft includes compensation details the user did not confirm.")
    if (
        re.search(r"https?://|www\.", content, re.IGNORECASE)
        and "application_url" not in known
        and "apply_url" not in known
    ):
        unsupported.append("Invented or unconfirmed application link")
        issues.append("Draft includes an application URL that was not provided.")
    if (
        "acme" in content.lower()
        and "acme" not in known
        and facts.get("company")
        and facts["company"].lower() not in content.lower()
    ):
        unsupported.append("Employer name does not match confirmed company")
        issues.append("Draft employer claim conflicts with confirmed facts.")
    if "UNFIXABLE_CLAIM" in content:
        unsupported.append("Unsupported employer guarantee claim")
        issues.append("Draft contains an unverifiable hiring guarantee.")

    passed = len(unsupported) == 0
    return {
        "passed": passed,
        "issues": issues,
        "suggestions": [] if passed else ["Remove unverified compensation and links."],
        "unsupported_claims": unsupported,
        "missing_required_facts": [],
        "proposed_revision": None,
    }
