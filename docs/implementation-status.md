# Implementation status

Last updated: 2026-11-20, at the end of Phase 3 (scheduled post management).

This file states what works today. Anything not listed under "Implemented" does not
exist, even if a navigation label or environment variable hints at it.

## Implemented

### Backend (`apps/api`)

| Item | Notes |
| --- | --- |
| FastAPI application factory | `app.main:create_app`. All routes under `/api/v1`. |
| Health | `GET /api/v1/health/live`, `GET /api/v1/health/ready` (PostgreSQL). |
| LinkedIn OAuth | `GET /api/v1/auth/linkedin`, `GET /api/v1/auth/linkedin/callback`. |
| Sessions | Opaque HttpOnly cookies; `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`. |
| Connections | `GET /api/v1/connections/linkedin` (includes connection `id`), `POST .../disconnect`. |
| Scheduled posts | `POST/GET/PATCH /api/v1/posts`, `GET /api/v1/posts/{id}`, `POST .../cancel`. |
| Models + migrations | Phase 2 tables (`20261120_0001`) + `scheduled_posts` (`20261120_0002`). |
| Token encryption | AES-256-GCM, versioned blob format, key from `TOKEN_ENCRYPTION_KEY`. |
| OIDC validation | JWKS signature, issuer allow-list, audience, expiry; userinfo `sub` match. |
| Idempotency + concurrency | `Idempotency-Key`, request fingerprint, optimistic `expected_version`. |
| Configuration | LinkedIn, session, cookie, encryption, schedule lead time, content length. |
| Tests | Unit tests for OAuth/sessions/posts + PostgreSQL concurrency integration test. |

### Frontend (`apps/web`)

| Item | Notes |
| --- | --- |
| Connections page | `/connections` — real status from the API, connect/reconnect/disconnect/sign-out. |
| Posts list | `/posts` — status filter, pagination, cancel with confirmation. |
| Schedule form | `/posts/new` — connection check, editor, IANA timezone, offset-aware submit, idempotency key. |
| Post detail | `/posts/[id]` — edit/reschedule while scheduled, cancel, Phase 4 placeholder. |
| Account section | Sidebar/mobile session summary from `GET /api/v1/auth/me`. |
| Credentialed API client | `credentials: "include"`; JSON POST/PATCH helpers with custom headers. |
| Dashboard + system status | Live readiness check; scheduling marked available on the roadmap. |

### Infrastructure

| Item | Notes |
| --- | --- |
| Docker Compose | Passes LinkedIn, encryption, session, and `WEB_BASE_URL` into `api` / `migrate`. |
| Docs | `docs/linkedin-oauth.md`, `docs/scheduled-posts.md`, README, architecture notes. |

## Not implemented

| Feature | Notes |
| --- | --- |
| Background publishing | Redis is provisioned; no Celery workers or LinkedIn POST jobs. |
| Publishing status history | `processing` / `published` / `failed` reserved; no worker transitions. |
| AI writing assistant | Not built. |
| Monitoring views | Not built. |
| Provider-side OAuth revocation | Disconnect clears local credentials only. |
| Refresh tokens | LinkedIn does not provide them for this flow; reconnect when expired. |
| LinkedIn person URN mapping | OIDC `sub` is the identity key; publishing URNs are a Phase 4 concern. |

## Blocked on external input

| Item | What is needed |
| --- | --- |
| Real LinkedIn OAuth in the browser | A LinkedIn developer app with the products for `openid profile email` and `w_member_social`, plus the exact redirect URL. See `docs/linkedin-oauth.md`. |
| End-to-end schedule in browser | Requires a live signed-in session after OAuth consent. |
| AI writing assistant | Language-model provider and API key. |
| CI on GitHub | Runs on the first push/PR once a remote exists. |

## Known limitations

- LinkedIn access tokens expire (~60 days) with no refresh token; scheduling surfaces a warning when the token expires before `scheduled_at`.
- Automated tests mock LinkedIn; a live OAuth connection is only verified when you complete it in the browser with your app credentials.
- ESLint remains on v9 because of `eslint-config-next` peer constraints.
- Redis remains unused by application code until the publishing phase.
- Phase 3 application code only produces `scheduled` and `cancelled` statuses.
