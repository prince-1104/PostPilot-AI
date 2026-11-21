# Agentic Content Studio (Phase 5A / 5B)

Conversational AI assistant that **drafts** LinkedIn posts. It does **not** schedule,
approve, or publish. Phase 5C will connect drafts to `PostService`.

## Architecture

```text
Browser (floating widget)
        |
        v
FastAPI /api/v1/assistant/*
        |
        v
AssistantService  ---- owns ----> agent_threads / agent_messages / agent_drafts
        |
        v
LangGraph StateGraph
  Intent -> Requirements -> (await user | Writing | Revise)
                                |
                             Review ⇄ Revise (max 1 auto)
                                |
                            Validator -> Draft Ready
        |
        v
LLMProvider (OpenAI | Fake)
```

Single source of truth for conversation: PostgreSQL tables. LangGraph working state is
stored in `agent_threads.graph_state` (JSONB). There is no separate LangGraph checkpoint
table.

## LangGraph state machine

```text
START
  -> intent
       |-- injection/error -> END
       +-- ok -> requirements
                    |-- missing essentials -> awaiting_user -> END
                    |-- refine existing draft -> revise -> review
                    +-- ready -> writing -> review
                                            |-- fail & auto_revision_count < 1 -> revise -> review
                                            +-- pass or persistent fail -> validator -> draft_ready -> END
```

Typed transitions only. At most one automatic revision after review failure.
No autonomous tool loops. No LinkedIn tools.

## Agent responsibilities

| Node | Role |
|------|------|
| Intent | Classify category, extract facts, detect injection, note schedule/tone/refine |
| Requirements | Merge facts, ask 1–3 missing essentials, keep salary optional |
| Writing | Produce draft from confirmed facts; label suggested skills separately |
| Review | Advisory check for unsupported claims, tone, hashtags, contradictions |
| Revise | One bounded auto-fix or user-driven rewrite; preserve confirmed facts |
| Validator | Length, ownership fields, ban false “already published” claims |

## Structured output schemas

Pydantic models in `app/assistant/schemas.py`:

- `IntentResult`
- `RequirementsResult`
- `WritingResult` (`content`, `suggested_hashtags`, `suggested_skills`, `assumptions`, …)
- `ReviewResult` (`passed`, `issues`, `unsupported_claims`, `proposed_revision`, …)

## Persistence

- `agent_threads` — ownership + `graph_state` + `lock_version`
- `agent_messages` — chat history (bounded) + optional `client_message_id` idempotency
- `agent_drafts` — versioned drafts labeled **Draft — not scheduled**

Thread turns take `SELECT … FOR UPDATE`. Draft PATCH uses optimistic `expected_version`.

## Prompt injection strategy

- System prompts forbid publish/schedule overrides
- Intent node flags injection language
- Graph short-circuits to a safe refusal
- No tools that can call LinkedIn or mutate `scheduled_posts`
- User/model text never treated as authorization
- Backend ownership checks on every endpoint

## Human approval boundary

Phase 5B ends at an editable draft (with review notes). Users must use the normal Posts UI
(and existing publish approval) to schedule. The assistant cannot set `confirm_publish` or
create `scheduled_posts` rows.

## Error handling

| Condition | API `state` |
|-----------|-------------|
| AI disabled / missing key | `unavailable` |
| Rate limited | HTTP 429 |
| Provider timeout/rate limit | `error` (prior draft preserved) |
| Injection | `error` |
| Need details | `needs_information` |
| Valid draft | `draft_ready` |
| Draft with persistent review notes | `draft_ready` + `review_issues` |

## LLM environment

```bash
AI_ENABLED=false
AI_PROVIDER=openai   # or fake (tests/local)
OPENAI_API_KEY=
AI_MODEL=gpt-4o-mini
AI_REQUEST_TIMEOUT_SECONDS=30
AI_MAX_LLM_CALLS_PER_TURN=8
AI_LLM_MAX_RETRIES=1
```

`AI_ENABLED=true` with `AI_PROVIDER=openai` requires a non-empty `OPENAI_API_KEY`.

## Example conversation

**User:** Create a job post for an AI Engineer at 7 PM.

**Assistant:** Asks for company, location/remote, experience (date for “7 PM” may also be clarified). Nothing scheduled.

**User:** Company: Acme AI. Location: Bangalore. Experience: 1-3 years. Python, FastAPI, RAG.

**Assistant:** Returns a draft labeled **Draft — not scheduled**, with suggested skills labeled as suggestions.

**User:** Make it shorter and more professional.

**Assistant:** Revises the existing draft; confirmed facts stay intact.

## Draft actions

- `PATCH /assistant/threads/{id}/draft` — manual edit with optimistic concurrency
- `POST /assistant/threads/{id}/draft/actions` — `regenerate` | `rewrite` | `set_tone`

## Future (Phase 5C)

Wire “Use this draft” → `PostService.create` with explicit user confirmation, idempotency,
and existing LinkedIn publishing approval. Still no autonomous publish from the graph.
