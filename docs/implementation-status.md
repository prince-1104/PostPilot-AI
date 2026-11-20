# Implementation status

Last updated: 2026-11-20, at the end of Phase 2 (LinkedIn OAuth and account connection).

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
| Connections | `GET /api/v1/connections/linkedin`, `POST /api/v1/connections/linkedin/disconnect`. |
| Models + migration | `users`, `linkedin_connections`, `auth_sessions`, `oauth_states` (`20261120_0001`). |
| Token encryption | AES-256-GCM, versioned blob format, key from `TOKEN_ENCRYPTION_KEY`. |
| OIDC validation | JWKS signature, issuer allow-list, audience, expiry; userinfo `sub` match. |
| Configuration | LinkedIn, session, cookie, and encryption settings validated at startup. |
| Tests | 104 unit tests (OAuth, crypto, sessions, Phase 1 health/config) + 1 integration test. |

### Frontend (`apps/web`)

| Item | Notes |
| --- | --- |
| Connections page | `/connections` — real status from the API, connect/reconnect/disconnect/sign-out. |
| Account section | Sidebar/mobile session summary from `GET /api/v1/auth/me`. |
| Credentialed API client | `credentials: "include"` for authenticated calls. |
| Dashboard + system status | Unchanged live readiness check; planned features exclude LinkedIn (now built). |

### Infrastructure

| Item | Notes |
| --- | --- |
| Docker Compose | Passes LinkedIn, encryption, session, and `WEB_BASE_URL` into `api` / `migrate`. |
| Docs | `docs/linkedin-oauth.md`, updated README and architecture notes. |

## Not implemented

| Feature | Notes |
| --- | --- |
| Post creation and scheduling | No post model, API, or editor. |
| Background publishing | Redis is provisioned; no Celery workers or publish jobs. |
| Publishing status and history | Not built. |
| AI writing assistant | Not built. |
| Monitoring views | Not built. |
| Provider-side OAuth revocation | Disconnect clears local credentials only. |
| Refresh tokens | LinkedIn does not provide them for this flow; reconnect when expired. |
| LinkedIn person URN mapping | OIDC `sub` is the identity key; publishing URNs are a later concern. |

## Blocked on external input

| Item | What is needed |
| --- | --- |
| Real LinkedIn OAuth in the browser | A LinkedIn developer app with the products for `openid profile email` and `w_member_social`, plus the exact redirect URL. See `docs/linkedin-oauth.md`. |
| AI writing assistant | Language-model provider and API key. |
| CI on GitHub | Runs on the first push/PR once a remote exists. |

## Known limitations

- LinkedIn access tokens expire (~60 days) with no refresh token; reauthorization is required.
- Automated tests mock LinkedIn; a live OAuth connection is only verified when you complete it in the browser with your app credentials.
- ESLint remains on v9 because of `eslint-config-next` peer constraints.
- Redis remains unused by application code until the publishing phase.
