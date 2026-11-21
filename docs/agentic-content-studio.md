# Agentic Content Studio (Phase 5A)

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
  Intent -> Requirements -> (await user | Writing -> Validator)
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
                    +-- ready -> writing -> validator -> draft_ready -> END
```

Typed transitions only. No autonomous tool loops. No LinkedIn tools.

## Agent responsibilities

| Node | Role |
|------|------|
| Intent | Classify category, extract supplied facts, detect injection, note schedule text |
| Requirements | Merge facts, ask 1–3 missing essentials, keep salary optional |
| Writing | Produce draft from confirmed facts; label assumptions |
| Validator | Length, ownership fields, ban false “already published” claims |

## Structured output schemas

Pydantic models in `app/assistant/schemas.py`:

- `IntentResult`
- `RequirementsResult`
- `WritingResult` (`content`, `suggested_hashtags`, `confirmed_facts_used`, `assumptions`, …)

## Persistence

- `agent_threads` — ownership + `graph_state`
- `agent_messages` — chat history (bounded)
- `agent_drafts` — versioned drafts labeled **Draft — not scheduled**

## Prompt injection strategy

- System prompts forbid publish/schedule overrides
- Intent node flags injection language
- Graph short-circuits to a safe refusal
- No tools that can call LinkedIn or mutate `scheduled_posts`
- User/model text never treated as authorization

## Human approval boundary

Phase 5A ends at an editable draft. Users must use the normal Posts UI (and existing
publish approval) to schedule. The assistant cannot set `confirm_publish` or create
`scheduled_posts` rows.

## Error handling

| Condition | API `state` |
|-----------|-------------|
| AI disabled / missing key | `unavailable` |
| Rate limited | HTTP 429 |
| Provider timeout/rate limit | `error` |
| Injection | `error` |
| Need details | `needs_information` |
| Valid draft | `draft_ready` |

## LLM environment

```bash
AI_ENABLED=false
AI_PROVIDER=openai   # or fake (tests/local)
OPENAI_API_KEY=
AI_MODEL=gpt-4o-mini
AI_REQUEST_TIMEOUT_SECONDS=30
```

`AI_ENABLED=true` with `AI_PROVIDER=openai` requires a non-empty `OPENAI_API_KEY`.

## Example conversation

**User:** Post a job requirement for AI Engineer at 7 PM.

**Assistant:** Asks for company, location/remote, experience (date for “7 PM” may also be clarified). Nothing scheduled.

**User:** Company is Hopper Labs. Remote. 3+ years.

**Assistant:** Returns a draft labeled **Draft — not scheduled**. Proposed time stays null until a concrete date is provided.

## Future (Phase 5C)

Wire “Use this draft” → `PostService.create` with explicit user confirmation, idempotency,
and existing LinkedIn publishing approval. Still no autonomous publish from the graph.
