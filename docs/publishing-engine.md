# Publishing engine (Phase 4A)

Phase 4A runs a **reliable background publishing pipeline** against a **deterministic fake
LinkedIn provider**. Real LinkedIn HTTP publishing is Phase 4B and is refused by this build.

## Architecture

```text
Celery Beat ──► dispatch_due_posts ──► Redis queue ──► Celery Worker (execute_publish)
     │                                      ▲
     └──► recover_stale_leases              │
                                            │
PostgreSQL ◄── leases, attempts, status ────┘
```

- **Beat** only schedules periodic tasks. It never publishes.
- **Worker** claims posts and runs the fake publisher.
- **PostgreSQL** is the system of record. Redis is a rebuildable queue.

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
- Worker claim: row lock, validate status/due/connection, `scheduled → processing`, insert `publish_attempts`, set `current_attempt_id` (fencing token) + `processing_lease_until`, **commit**, then call publisher.
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

There is **no** LinkedIn-side idempotency key in Phase 4A. Fencing prevents stale DB writes; it does **not** guarantee exactly-once external delivery. Ambiguous outcomes stop automatic republishing.

## Fake provider

`PUBLISH_PROVIDER=fake` (default). Content markers:

- `[[fake:success]]`
- `[[fake:rate_limit]]`
- `[[fake:permanent]]`
- `[[fake:expired]]`
- `[[fake:pre_network]]`
- `[[fake:ambiguous]]`
- `[[fake:interrupt]]`

Fake URNs look like `urn:li:share:fake-…`. Production refuses fake unless `ALLOW_FAKE_PUBLISHER_IN_PRODUCTION=true`.

## Running workers

```sh
docker compose up -d --build --wait
# services: worker (execute) and beat (schedule)
```

Host:

```sh
cd apps/api
uv run --env-file ../../.env celery -A app.workers.celery_app.celery_app worker -Q publish -c 2
uv run --env-file ../../.env celery -A app.workers.celery_app.celery_app beat
```

## Tests

```sh
cd apps/api
uv run pytest tests/test_publishing.py
uv run --env-file ../../.env pytest -m integration
```
