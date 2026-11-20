# Implementation status

Last updated: 2026-11-21 — real LinkedIn publishing is the user-facing workflow (canary-gated).

This file states what works today. Anything not listed under "Implemented" does not
exist, even if a navigation label or environment variable hints at it.

## Implemented

### Backend (`apps/api`)

| Item | Notes |
| --- | --- |
| FastAPI application factory | `app.main:create_app`. All routes under `/api/v1`. |
| Health | `GET /api/v1/health/live`, `GET /api/v1/health/ready` (PostgreSQL). |
| LinkedIn OAuth + sessions | Opaque cookies; encrypted tokens; connections page API. |
| Scheduled posts CRUD | Create/list/get/patch/cancel with idempotency + optimistic concurrency. |
| Publish attempts API | `GET /api/v1/posts/{id}/attempts` (sanitized history). |
| Celery worker + beat | Separate Compose services; Redis broker; DB-backed dispatch/recovery. |
| Fake LinkedIn publisher | Tests / isolated simulation only; never a silent fallback. |
| Real LinkedIn publisher | `RealLinkedInPublisher` → `POST /rest/posts`; off until explicitly enabled. |
| Live canary allowlist | `LIVE_PUBLISH_REQUIRE_CANARY` + `LIVE_PUBLISH_CANARY_POST_IDS` gate real submits. |
| Publishing readiness API | `GET /api/v1/publishing/readiness` (no secrets; configured vs ready vs verified). |
| Person URN mapping | OIDC `sub` → `urn:li:person:{sub}`; ownership checked on claim. |
| Models + migrations | Through `20261120_0003` (`publish_attempts`, leases, `requires_review`). |

### Frontend (`apps/web`)

| Item | Notes |
| --- | --- |
| Connections | `/connections` with OAuth vs permission vs publishing-verified readiness |
| Posts | `/posts`, `/posts/new`, `/posts/[id]` with status polling and attempt timeline |
| Real publish UI | Permalink “Open on LinkedIn”, reconnect hints, `requires_review` warnings |
| Simulated publication labeling | Clear when URN/result is from the fake provider |

### Infrastructure

| Item | Notes |
| --- | --- |
| Docker Compose | `postgres`, `redis`, `migrate`, `api`, `worker`, `beat`, `web` |
| Docs | `docs/linkedin-oauth.md`, `docs/scheduled-posts.md`, `docs/publishing-engine.md`, `docs/linkedin-publishing.md`, `docs/live-e2e-publishing.md` |

## Not implemented

| Feature | Notes |
| --- | --- |
| AI writing assistant | Not built |
| Media / image publishing | Text-only Posts API payload |
| Engagement analytics | Not built |
| Monitoring dashboards | In-process metrics only; no UI |
| WebSockets / SSE | UI polls HTTP |
| Provider-side OAuth revocation | Local disconnect only |
| Refresh tokens | LinkedIn does not provide them for this flow |

## Known limitations

- No LinkedIn-side create idempotency; ambiguous outcomes go to `requires_review`.
- Real publishing requires `PUBLISH_PROVIDER=linkedin` **and** `ENABLE_REAL_PUBLISHING=true`.
- Fake provider must not be enabled in real production without an explicit isolated-test override.
- Redis carries only rebuildable queue messages; PostgreSQL leases are authoritative.
