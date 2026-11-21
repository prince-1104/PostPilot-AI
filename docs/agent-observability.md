# Agent observability (Phase 5D)

## Trace architecture

Each assistant turn creates a `TurnTelemetry` collector with:

- `trace_id` — correlates all node spans and LLM usage for the turn
- `turn_id` — unique per HTTP turn
- `usages[]` — one entry per LLM invocation (intent, requirements, writing, review, revise)
- `traces[]` — one entry per instrumented node execution

Persistence is append-only:

| Table | Purpose |
|-------|---------|
| `llm_usage_events` | Provider usage + estimated cost snapshot |
| `agent_node_traces` | Node timing/status/review outcome |
| `model_pricing_versions` | Immutable pricing catalog versions |

Recording uses a **separate DB session** after the user draft is committed. Observability failures are logged and never roll back a valid draft.

OpenTelemetry: optional spans via `app.observability.otel.node_span` when the OTEL SDK is installed; otherwise no-op.

## Usage and cost accounting

OpenAI adapter reads `completion.usage` (prompt/completion/total tokens and cached prompt tokens when present). Missing usage is stored as `usage_known=false` with **null** token fields — never coerced to zero.

Estimated cost:

```
billable_input = max(input_tokens - cached_input_tokens, 0)
cost = billable_input * input_rate
     + cached_input_tokens * cached_rate   # when cached rate exists
     + output_tokens * output_rate
```

Rates live in `app/observability/pricing.py` under a version string (e.g. `2026-11-21.1`). Each usage event stores `pricing_version` + `estimated_cost` so later catalog edits **do not** rewrite history.

Costs are labeled **estimates**, not official provider billing totals.

## Pricing assumptions

- Currency: USD
- Units: USD per 1M tokens
- Models without a catalog entry → cost unavailable
- Fake provider never invents tokens (`usage_known=false`)

## Privacy / security

- No prompts, message bodies, OAuth tokens, or API keys in telemetry
- Trace `meta` strips keys containing prompt/token/secret/etc.
- Admin analytics requires allowlist: `ADMIN_USER_IDS` and/or `ADMIN_EMAILS`
- Ordinary authenticated users receive HTTP 403 on `/api/v1/admin/ai/*`
- Thread inspection omits conversation text by default

## Guardrails

Reuses existing AI budgets where possible:

| Setting | Role |
|---------|------|
| `AI_MAX_LLM_CALLS_PER_TURN` | Max LLM calls per user message |
| `AI_MAX_OUTPUT_TOKENS` | Passed to OpenAI when set |
| `AI_MAX_USER_REGENERATIONS_PER_DRAFT` | Rewrite/regenerate cap per draft |
| `AI_NODE_TIMEOUT_SECONDS` | Per-node wall clock timeout |
| `AI_RATE_LIMIT_PER_MINUTE` | Existing per-user message rate limit |
| `AI_MAX_CONCURRENT_REQUESTS_PER_USER` | In-flight request cap |

Exceeded limits return a meaningful error, preserve conversation/draft state, and do not create scheduled posts.

## Evaluation methodology

`apps/api/evals/` contains an offline dataset and runner using the **fake** LLM:

- Deterministic assertions only (intent/clarification/injection/fact preservation)
- No invented LLM-as-judge scores
- Run: `uv run --env-file ../../.env python -m evals.run_assistant_eval` from `apps/api`

## Metrics definitions

| Metric | Definition |
|--------|------------|
| Total LLM requests | Rows in `llm_usage_events` in window |
| Input/output tokens | Sum of known token fields only |
| Estimated API cost | Sum of `estimated_cost` where `cost_available` |
| Review failure rate | `review_passed=false` / review node traces |
| Automatic revisions | `revise` node traces |
| Drafts generated | `agent_drafts` created in window |
| AI drafts scheduled | Confirmed `agent_draft_schedule_ops` |

## Failure handling

- Provider errors → traced with sanitized `error_category`
- Duplicate usage/traces → unique `idempotency_key` rejects duplicates
- Recorder exceptions → warning logs only

## Deployment

1. Apply migration `20261121_0008`
2. Set `ADMIN_EMAILS` / `ADMIN_USER_IDS` in environment
3. Rebuild API/web containers
4. Open `/admin/ai-analytics` while signed in as an allowlisted admin
