# Implementation status

Last updated: 2026-11-20, at the end of Phase 1 (foundation and local infrastructure).

This file states what works today. Anything not listed under "Implemented" does not
exist, even if a directory, a navigation label, or an environment variable hints at it.

## Implemented

### Backend (`apps/api`)

| Item | Notes |
| --- | --- |
| FastAPI application factory | `app.main:create_app`. All routes under `/api/v1`. |
| `GET /api/v1/health/live` | Uses no external service. |
| `GET /api/v1/health/ready` | Runs `SELECT 1` against PostgreSQL with a timeout. Returns 503 with a typed error when it fails. |
| Configuration | `pydantic-settings`, environment variables only, no defaults for required values or secrets. |
| Database access | SQLAlchemy 2 async engine and session factory on asyncpg, created in the application lifespan. |
| Migrations | Async Alembic environment. There are no revisions, because there are no domain tables. |
| Structured logging | structlog, JSON or console output, request ID on every line, secret redaction. |
| Request IDs | `X-Request-ID` accepted, validated, generated when absent, and returned. |
| CORS | Explicit origin allow-list with credentials. Wildcards are rejected at startup. |
| Typed errors | One envelope for application errors, HTTP errors, validation errors, and unhandled exceptions. |
| Tests | 60 unit tests and 1 PostgreSQL integration test (`pytest -m integration`). |
| Lint and format | Ruff, including the security (`S`) and async (`ASYNC`) rule sets. |

### Frontend (`apps/web`)

| Item | Notes |
| --- | --- |
| Next.js App Router shell | Sidebar, mobile drawer, header, PostPilot AI branding. |
| Dashboard | A live system-status card and a list of planned features, each labelled "Not implemented". |
| System status | Calls the readiness endpoint from the browser and shows the real result, including the failure reason and request ID. |
| API client | Typed `fetch` wrapper that parses the API error envelope. |
| Configuration | `NEXT_PUBLIC_API_BASE_URL`, validated at load. |
| Tooling | Strict TypeScript, ESLint with zero warnings allowed, Tailwind CSS 4, shadcn/ui. |

### Infrastructure

| Item | Notes |
| --- | --- |
| Docker Compose stack | `web`, `api`, `postgres`, `redis`, and a one-shot `migrate` job. |
| Persistence | Named volume for PostgreSQL. Verified to survive `docker compose down` and `up`. |
| Health checks and start order | PostgreSQL healthy, then migrations, then API ready, then web. |
| Network isolation | PostgreSQL and Redis on an internal network with no published ports. Web and API on `127.0.0.1` only. |
| Host development override | `infra/docker-compose.host-dev.yml` publishes PostgreSQL on `127.0.0.1`. |
| CI workflow | `.github/workflows/ci.yml`: backend lint, format, tests, migrations, integration test; frontend lint, type check, build. |

## Not implemented

None of the following exists in any form. There is no partial code, no stub endpoint, and
no database table for any of it.

| Feature | What it will need |
| --- | --- |
| LinkedIn OAuth sign-in and account connection | OAuth flow, session handling, encrypted token storage, user and account tables |
| Post creation and scheduling | Post model and migrations, CRUD API, editor and calendar UI |
| Background publishing | Celery workers, Redis broker, claiming of due posts, retries, duplicate protection |
| Publishing status and history | Publish-attempt model, status API, UI |
| AI writing assistant | Language-model integration, prompt handling, cost and failure limits |
| Monitoring views | Queue and worker metrics, failure inspection UI |
| Authentication and authorization | Every current endpoint is public. That is acceptable only because the two endpoints expose nothing but health. |

Related placeholders that are intentionally inert:

- `app/models`, `app/integrations`, and `app/workers` are empty packages.
- Redis runs in Compose, but no code or setting refers to it.
- `LINKEDIN_*` and `TOKEN_ENCRYPTION_KEY` in `.env.example` are read by nothing. Their
  names may change when the features are built.
- Sidebar entries marked "Planned" are not links.

## Blocked on external input

| Item | What is needed |
| --- | --- |
| LinkedIn OAuth and publishing | A LinkedIn developer application with a client ID, a client secret, and a registered redirect URL, with the products that grant the sign-in scopes (`openid`, `profile`, `email`) and the posting scope (`w_member_social`). Confirm the current product names and review requirements in the LinkedIn developer portal before starting. |
| AI writing assistant | A choice of language-model provider and an API key for it. |
| CI execution | The workflow has not run. The directory is not yet a Git repository and has no GitHub remote. It runs on the first push or pull request. |

## Known limitations

- **ESLint 9 instead of 10.** `eslint-config-next` 16.4.6 depends on
  `eslint-plugin-import`, whose peer range stops at ESLint 9. pnpm reports the installed
  ESLint 9 release as no longer supported. Move to ESLint 10 once the Next.js config
  supports it.
- **TypeScript 6.0 instead of 7.** `typescript-eslint` does not yet support TypeScript 7.
- **Outbound request URLs in logs.** httpx logs the full URL of each request at INFO
  level, including the query string. The redaction step masks known secret parameters
  (`code`, `token`, `access_token`, `refresh_token`, `id_token`, `client_secret`,
  `password`, `api_key`), which is covered by a test. When OAuth is implemented, review
  that list against the real requests, and prefer sending secrets in the request body.
- **No rate limiting and no security headers** beyond CORS. Add them with the first
  authenticated endpoint.
- **Local stack only.** Compose is for development. There is no deployment configuration,
  TLS termination, backup, or secret manager integration.
- **Tests have run on Windows only.** The backend suite was run on Windows with Python
  3.14, while the images run the same code on Debian. The running containers were checked
  by hand; the first CI run will be the first automated test run on Linux.
