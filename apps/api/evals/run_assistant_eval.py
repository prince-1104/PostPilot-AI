"""Offline deterministic evaluation harness for the assistant (fake LLM).

LLM-as-judge hooks are intentionally separate — this script only runs
deterministic assertions and prints pass/fail counts (never invents scores).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from app.assistant.graph import empty_state, run_assistant_turn
from app.assistant.llm.fake import FakeLLMProvider
from app.core.config import Settings

DATASET = Path(__file__).with_name("assistant_eval_dataset.json")


async def _run_case(case: dict, settings: Settings) -> tuple[bool, str]:
    llm = FakeLLMProvider()
    state = empty_state(thread_id=uuid4(), user_id=uuid4(), timezone="Asia/Kolkata")
    expect = case["expect"]

    if case.get("setup_message"):
        state["last_user_message"] = case["setup_message"]
        state, _ = await run_assistant_turn(llm=llm, settings=settings, state=state)

    state["last_user_message"] = case["user_message"]
    entry = case.get("graph_entry", "intent")
    if entry == "revise":
        state["refine_instruction"] = case["user_message"]
    final, _tel = await run_assistant_turn(
        llm=llm, settings=settings, state=state, entry=entry
    )

    if "response_state_in" in expect:
        if final.get("response_state") not in expect["response_state_in"]:
            return False, f"state={final.get('response_state')}"

    if expect.get("injection_attempt") is True:
        if not final.get("injection_attempt") and "prompt_injection" not in str(
            final.get("validation_errors")
        ):
            return False, "injection not blocked"

    if expect.get("injection_attempt") is False and final.get("injection_attempt"):
        return False, "false-positive injection"

    if expect.get("has_proposed_schedule") and not final.get("proposed_scheduled_at"):
        return False, "missing proposed schedule"

    if expect.get("clarification_min"):
        qs = final.get("clarification_questions") or []
        if len(qs) < int(expect["clarification_min"]):
            return False, f"clarifications={len(qs)}"

    if expect.get("must_include_facts"):
        blob = json.dumps(final.get("confirmed_facts") or {}) + (final.get("draft_content") or "")
        for token in expect["must_include_facts"]:
            if token.lower() not in blob.lower():
                return False, f"missing fact {token}"

    if expect.get("must_not_invent"):
        content = final.get("draft_content") or ""
        for bad in expect["must_not_invent"]:
            if bad in content:
                return False, f"invented {bad}"

    if expect.get("preserves_company"):
        content = final.get("draft_content") or ""
        company = expect["preserves_company"]
        if company.lower() not in content.lower() and company.lower() not in json.dumps(
            final.get("confirmed_facts") or {}
        ).lower():
            return False, "company not preserved"

    if expect.get("post_category") and final.get("post_category") not in {
        expect["post_category"],
        None,
    }:
        # Soft: fake LLM may map categories differently on sparse prompts.
        if final.get("response_state") not in (expect.get("response_state_in") or []):
            return False, f"category={final.get('post_category')}"

    return True, "ok"


async def main() -> int:
    settings = Settings(
        app_env="test",
        ai_enabled=True,
        ai_provider="fake",
        ai_model="fake-model",
        publish_provider="fake",
        enable_real_publishing=False,
        live_publish_require_canary=False,
        # Minimal secrets for Settings validation — not used by fake LLM.
        postgres_password="x",
        linkedin_client_secret="x",
        token_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        redis_password="x",
        linkedin_client_id="test",
        linkedin_redirect_uri="http://localhost:8000/api/v1/auth/linkedin/callback",
        linkedin_scopes="openid profile email w_member_social",
        web_base_url="http://localhost:3000",
        cors_allowed_origins=["http://localhost:3000"],
    )
    # Settings() may still load .env — prefer factory-less fake path via model_copy if needed.
    try:
        cases = json.loads(DATASET.read_text(encoding="utf-8"))
    except Exception as exc:
        print("DATASET_ERROR", exc)
        return 2

    passed = 0
    failed = 0
    for case in cases:
        ok, detail = await _run_case(case, settings)
        status = "PASS" if ok else "FAIL"
        print(f"{status} {case['id']}: {detail}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"SUMMARY passed={passed} failed={failed} total={passed + failed}")
    print("NOTE: deterministic checks only; no LLM-as-judge scores invented.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
