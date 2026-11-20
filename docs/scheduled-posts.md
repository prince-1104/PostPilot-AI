# Scheduled posts (Phase 3)

This document describes how PostPilot stores and manages scheduled LinkedIn posts.
**Phase 3 does not publish to LinkedIn.** Workers, Celery, and provider POST calls belong
to Phase 4.

## Schema (`scheduled_posts`)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | Server-generated |
| `user_id` | UUID FK → `users` | Cascade on user delete |
| `linkedin_connection_id` | UUID FK → `linkedin_connections` | Restrict delete |
| `content` | TEXT | Non-empty; max length from `POST_CONTENT_MAX_LENGTH` (default 3000) |
| `scheduled_at` | TIMESTAMPTZ | Stored in UTC |
| `timezone` | VARCHAR(64) | IANA zone for display and offset checks |
| `status` | VARCHAR(32) | See state machine |
| `idempotency_key` | VARCHAR(128) | Unique per user |
| `request_fingerprint` | VARCHAR(64) | SHA-256 of normalized create payload |
| `version` | INTEGER | Optimistic concurrency; starts at 1 |
| `linkedin_post_urn` | VARCHAR(255) | Nullable; reserved for Phase 4 |
| `created_at` / `updated_at` | TIMESTAMPTZ | |
| `published_at` | TIMESTAMPTZ | Nullable; reserved for Phase 4 |

Indexes:

- `(status, scheduled_at)` — future due-queue scans
- `(user_id, scheduled_at)` — per-user lists
- unique `(user_id, idempotency_key)`
- unique partial on `linkedin_post_urn` where not null

Migration: `apps/api/alembic/versions/20261120_0002_scheduled_posts.py`.

## State transitions

| From | To | Who | Phase |
| --- | --- | --- | --- |
| _(new)_ | `scheduled` | API create | 3 |
| `scheduled` | `scheduled` | API update (content / time) | 3 |
| `scheduled` | `cancelled` | API cancel | 3 |
| `cancelled` | `cancelled` | Repeated cancel (idempotent) | 3 |
| `scheduled` | `processing` | Worker claim | 4 (not implemented) |
| `processing` | `published` / `failed` | Worker outcome | 4 (not implemented) |

Phase 3 application code **never** writes `processing`, `published`, or `failed`.
Updates and cancellation are refused unless `status = scheduled` (except repeated cancel
of an already-cancelled post, which returns the current row).

## API

All routes require an authenticated session. Mutating routes require the existing Origin
CSRF check. `user_id` is never accepted from the client.

### `POST /api/v1/posts`

Requires header `Idempotency-Key` (8–128 chars: `A-Za-z0-9._-`).

```json
{
  "content": "Hello from PostPilot",
  "scheduled_at": "2026-12-01T15:30:00+05:30",
  "timezone": "Asia/Kolkata",
  "linkedin_connection_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
}
```

Response `201` includes the post plus optional connection-expiry warning fields when the
LinkedIn access token expires before `scheduled_at`.

### Idempotency

1. Fingerprint = SHA-256 of normalized JSON: content, UTC `scheduled_at`, timezone,
   connection id.
2. Same key + same fingerprint → return existing post (`201`).
3. Same key + different fingerprint → `409 idempotency_conflict`.
4. Concurrent creates: PostgreSQL uses `INSERT … ON CONFLICT DO NOTHING` on
   `(user_id, idempotency_key)` then reloads the winning row. SQLite unit tests catch
   `IntegrityError` on commit and reload the same way.

### `GET /api/v1/posts`

Cursor pagination (`scheduled_at DESC, id DESC`). Optional `status`, `scheduled_from`,
`scheduled_to`, `limit`. Only the current user’s posts.

### `GET /api/v1/posts/{id}`

`404` for missing or other users’ posts (no existence leak).

### `PATCH /api/v1/posts/{id}`

```json
{
  "expected_version": 1,
  "content": "Updated copy",
  "scheduled_at": "2026-12-01T16:00:00+05:30",
  "timezone": "Asia/Kolkata"
}
```

Requires `status=scheduled` and matching `expected_version`. On success, `version`
increments. Conflicts return `409`.

### `POST /api/v1/posts/{id}/cancel`

```json
{ "expected_version": 2 }
```

Atomic transition to `cancelled`. Already-cancelled posts return the current row.
`processing` / `published` cannot be cancelled in this phase.

## Timezone handling

- Naive `scheduled_at` values are rejected (`422`).
- Client must send an **offset-aware** instant **and** an IANA `timezone`.
- At that UTC instant, the offset must equal `ZoneInfo(timezone).utcoffset(...)`.
- Storage is always UTC; `timezone` is preserved for UI.
- Minimum lead time: `SCHEDULE_MIN_LEAD_SECONDS` (default **60**). Configurable to avoid
  races where a post is due before the API response returns.

## Concurrency

| Concern | Mechanism |
| --- | --- |
| Duplicate creates | Idempotency key + DB unique constraint |
| Stale edits | `expected_version` optimistic lock |
| Ownership | Server session user; connection must belong to user |
| Mass assignment | Pydantic `extra=forbid`; status / URN not writable |

## What Phase 3 intentionally does not implement

- Celery / Redis workers
- LinkedIn UGC or Posts API calls
- Token refresh (LinkedIn does not provide refresh tokens for this flow)
- AI generation
- Engagement metrics or fake analytics
- Multi-account LinkedIn selection beyond the single connected account

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCHEDULE_MIN_LEAD_SECONDS` | `60` | Earliest allowed `scheduled_at` relative to now |
| `POST_CONTENT_MAX_LENGTH` | `3000` | Conservative text bound (not a claimed LinkedIn hard limit) |
| `POSTS_PAGE_SIZE_DEFAULT` | `20` | Default list page size |
| `POSTS_PAGE_SIZE_MAX` | `50` | Max list page size |
