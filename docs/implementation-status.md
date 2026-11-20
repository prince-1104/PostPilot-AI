# Implementation status

Last updated: 2026-11-20, at the end of Phase 4A (fake-provider background publishing).

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
| Fake LinkedIn publisher | Deterministic scenarios; never calls LinkedIn. |
| Models + migrations | Through `20261120_0003` (`publish_attempts`, leases, `requires_review`). |

### Frontend (`apps/web`)

| Item | Notes |
| --- | --- |
| Connections | `/connections` |
| Posts | `/posts`, `/posts/new`, `/posts/[id]` with status polling and attempt timeline |
| Simulated publication labeling | Clear when URN/result is from the fake provider |

### Infrastructure

| Item | Notes |
| --- | --- |
| Docker Compose | `postgres`, `redis`, `migrate`, `api`, `worker`, `beat`, `web` |
| Docs | `docs/linkedin-oauth.md`, `docs/scheduled-posts.md`, `docs/publishing-engine.md` |

## Not implemented

| Feature | Notes |
| --- | --- |
| Real LinkedIn publishing | Phase 4B |
| AI writing assistant | Not built |
| Monitoring dashboards | In-process metrics only; no UI |
| WebSockets / SSE | UI polls HTTP |
| Provider-side OAuth revocation | Local disconnect only |
| Refresh tokens | LinkedIn does not provide them for this flow |

## Known limitations

- Phase 4A cannot claim exactly-once LinkedIn delivery; ambiguous outcomes go to `requires_review`.
- Fake provider must not be enabled in real production without an explicit isolated-test override.
- Redis carries only rebuildable queue messages; PostgreSQL leases are authoritative.
