# Publishing engine (Phase 4A + 4B)

PostPilot runs a **reliable background publishing pipeline** on Celery + Redis +
PostgreSQL. Phase 4A introduced the fake provider, leases, retries, and recovery.
Phase 4B adds an optional **real LinkedIn Posts API** publisher behind explicit flags.

See [linkedin-publishing.md](linkedin-publishing.md) for LinkedIn-specific headers,
URN mapping, and live E2E steps.

## Architecture

```text
Celery Beat ──► dispatch_due_posts ──► Redis queue ──► Celery Worker (execute_publish)
     │                                      ▲
     └──► recover_stale_leases              │
                                            │
PostgreSQL ◄── leases, attempts, status ────┘
                     │
                     ▼
            FakeLinkedInPublisher  (default)
            RealLinkedInPublisher  (PUBLISH_PROVIDER=linkedin + ENABLE_REAL_PUBLISHING)
```

- **Beat** only schedules periodic tasks. It never publishes.
- **Worker** claims posts and runs the configured publisher.
- **PostgreSQL** is the system of record. Redis is a rebuildable queue.
- Compose runs the worker with `--pool=solo`. The default Celery prefork pool
  deadlocks when tasks call `asyncio.run()` with SQLAlchemy async sessions; solo
  (and the per-task engine dispose in `app.workers.runtime`) keep dispatch healthy.

## Post state machine

| From | To | Trigger |
| --- | --- | --- |
| _(new)_ | `scheduled` | API create |
| `scheduled` | `scheduled` | API edit / retry backoff |
| `scheduled` | `cancelled` | API cancel |
| `scheduled` | `processing` | Worker claim |
| `processing` | `published` | Confirmed success |
| `processing` | `scheduled` | Safe retryable failure |
| `processing` | `failed` | Permanent failure / retry exhaustion |
| `processing` | `requires_review` | Ambiguous / interrupted after submission |

Terminal for auto-dispatch: `published`, `failed`, `cancelled`, `requires_review`.

## Attempt state machine

`claimed` → `submitting` → (`succeeded` | `retryable_failure` | `permanent_failure` | `ambiguous` | `interrupted`)

`submitting` is written **before** the publisher call. That is the conservative boundary:

- Failure **before** `submitting` → safe to requeue.
- Failure **after** `submitting` without confirmation → `requires_review` (no auto resubmit).

## Database locking

- Dispatcher: `SELECT … FOR UPDATE SKIP LOCKED`, set `dispatch_lease_until`, **commit**, then enqueue post UUID only.
- Worker claim: row lock, validate status/due/connection ownership, `scheduled → processing`, insert `publish_attempts`, set `current_attempt_id` (fencing token) + `processing_lease_until`, **commit**, then call publisher.
- Results apply only when `current_attempt_id` still matches the attempt fencing token.

## Retry classification

Auto-retry only when non-publication is known (`retryable`, `pre_network_failure`).

Config (defaults):

| Variable | Default |
| --- | --- |
| `PUBLISH_RETRY_INITIAL_SECONDS` | 30 |
| `PUBLISH_RETRY_BACKOFF_MULTIPLIER` | 2 |
| `PUBLISH_RETRY_MAX_DELAY_SECONDS` | 900 |
| `PUBLISH_RETRY_MAX_ATTEMPTS` | 5 |

Retry schedule is stored as `next_attempt_at` in PostgreSQL (not Celery countdown).

## Crash recovery

`recover_stale_leases` finds `processing` rows with expired `processing_lease_until`:

- Attempt still `claimed` and no `request_started_at` → return to `scheduled`.
- Attempt already `submitting` / ambiguous → `requires_review`.

## Exactly-once limitations

There is **no** LinkedIn-side idempotency key. Fencing prevents stale DB writes; it does
**not** guarantee exactly-once external delivery. Ambiguous outcomes stop automatic
republishing.

## Providers

| `PUBLISH_PROVIDER` | Flag | Behavior |
| --- | --- | --- |
| `fake` (default) | — | Deterministic simulation; never calls LinkedIn |
| `linkedin` | `ENABLE_REAL_PUBLISHING=true` | `POST /rest/posts` with decrypted member token |

### Database publishing approval

When `PUBLISH_PROVIDER=linkedin`, every post must carry durable approval:

- `publish_approved_at` / `publish_approved_by` (session user)
- `approved_content_hash` covering content + schedule + timezone + connection
- `approval_revoked_at` null

UI `confirm_publish=true` on create/update/approve stamps approval. Historical rows
remain unapproved. Editing material fields without confirmation is rejected; cancel
revokes approval. Fake provider mode skips the DB approval gate for isolated tests.

### Live canary (temporary operator gate)

When `PUBLISH_PROVIDER=linkedin` and `LIVE_PUBLISH_REQUIRE_CANARY=true` (default):

- Dispatcher leases **only** IDs listed in `LIVE_PUBLISH_CANARY_POST_IDS`.
- An empty allowlist means **zero** real dispatches.
- Canary never bypasses database approval.
- The worker blocks unauthorized IDs before claim / before HTTP and leaves them
  `scheduled` (deferred).
- Fake provider mode ignores the canary gate.

See [live-e2e-publishing.md](live-e2e-publishing.md).

Fake content markers (still supported):

- `[[fake:success]]`
- `[[fake:rate_limit]]`
- `[[fake:permanent]]`
- `[[fake:expired]]`
- `[[fake:pre_network]]`
- `[[fake:ambiguous]]`
- `[[fake:interrupted]]`

Fake success URNs use the `urn:li:share:fake-…` prefix and are labeled
`publication_simulated` in the API/UI. Real publishing never stores those as genuine
results.

## Observability

Sanitized attempt history is exposed at `GET /api/v1/posts/{id}/attempts`.
Tokens and Authorization headers are never logged.
