# 0001: Architecture and stack

- **Status:** Accepted
- **Date:** 2026-11-20
- **Scope:** Phase 1 foundation; Phase 2 LinkedIn OAuth builds on these decisions

## Context

PostPilot AI lets a user connect a LinkedIn account, schedule posts, and have them
published in the background, with an AI assistant for drafting. The core promise is that
a scheduled post is published once, at the right time, and that the user can always see
what happened to it.

That promise shapes the architecture more than anything else. Publishing is a side effect
on a third-party system that cannot be undone, so the design has to survive process
crashes, retries, and restarts without losing a post or publishing it twice.

Phase 1 builds only the foundation. This record fixes the decisions that are expensive to
change later and deliberately leaves the rest open.

## Decisions

### 1. One repository, two deployable applications

`apps/web` and `apps/api` live in one repository and are built and deployed separately.
Each uses its own native toolchain (pnpm, uv) with its own lockfile. There is no shared
workspace tool at the root, because the two applications share no code.

Background workers will be a second process type of the same backend codebase
(`app/workers`), not a separate service. They need the same models, settings, and
integrations as the API.

### 2. Frontend: Next.js App Router, strict TypeScript, Tailwind CSS, shadcn/ui

- The browser calls the API directly. The frontend has no backend-for-frontend layer and
  no API routes of its own, so there is one place where business rules live.
- TypeScript runs in strict mode with additional checks (`noUncheckedIndexedAccess` and
  others). API responses are parsed at the boundary instead of cast.
- shadcn/ui components are copied into the repository, so they are ordinary code we own
  rather than a dependency to work around.
- `NEXT_PUBLIC_API_BASE_URL` is validated when the bundle loads. A missing or malformed
  value fails loudly instead of producing requests to `undefined`.

### 3. Backend: FastAPI, Pydantic v2, SQLAlchemy 2 (async), asyncpg, Alembic

- The workload is I/O bound: database queries and calls to LinkedIn and a language-model
  provider. An async stack fits that without threads.
- Layering is explicit and shallow: `api` (HTTP only) calls `services` (logic), which use
  `db` and `integrations`. Routes stay thin so the same logic can be called from workers.
- The application is built by a factory, `create_app(settings)`. Tests construct an
  application with explicit settings instead of patching globals.
- The database engine is created in the application lifespan and disposed on shutdown.
  Nothing connects at import time.
- Configuration is one `pydantic-settings` class that reads process environment variables
  only. Required values have no defaults, so a misconfigured process fails at startup
  with the name of the missing variable. Secrets are `SecretStr` and never appear in
  `repr` or logs.
- Every error leaves the API in one typed envelope with a stable `code` and the request
  ID, so the frontend handles errors in one place.
- Logs are structured (structlog). A redaction step runs last on every event, including
  events from third-party libraries, and removes secret-looking keys, URL credentials,
  bearer tokens, and secret query parameters.

### 4. PostgreSQL is the authoritative store

All durable state will live in PostgreSQL, and only there. This is the most consequential
decision in this record.

**Why it has to be authoritative:**

- **A schedule is a durable commitment.** A post scheduled for next Tuesday must survive
  restarts, deploys, and a lost queue. That needs a store with real durability
  guarantees, not a broker.
- **Publishing must happen exactly once from the user's point of view.** A queue can
  deliver a job twice, and a worker can crash after LinkedIn accepted a post but before
  it recorded the result. Safety therefore has to come from state that is checked and
  changed atomically: a row's status, a unique constraint, a row lock. Transactions make
  "claim this post for publishing" a single atomic step.
- **The queue is derived state.** Because the database knows which posts are due and
  which are in flight, a lost or flushed queue can be rebuilt by reading the database.
  The reverse is not true. This is why Redis runs with persistence turned off: nothing in
  it is allowed to be the only copy of anything.
- **One source of truth for status.** The UI, the API, and the workers all read post
  status from the same rows. There is no second copy to drift.
- **Relational integrity fits the data.** Users, connected accounts, posts, and publish
  attempts are relational, and constraints catch bugs that application code misses.

**What follows from it:**

- Redis is used only for transient coordination (the Celery broker, later perhaps rate
  limiting or caching). Losing it may delay work but must never lose or duplicate a post.
- Schema changes go through Alembic migrations, applied by a one-shot `migrate` job
  before the API starts. The API never creates tables itself.
- The readiness endpoint checks PostgreSQL and nothing else, because it is the only
  dependency without which the API cannot do anything useful.

Phase 1 contains no domain tables. The schema will be designed with the features that
need it.

### 5. Redis, for Celery, in a later phase

Redis is provisioned in Compose now so the local topology is complete and its network
placement and authentication are settled. No application code or setting references it
yet. Celery with a Redis broker is the planned queue because it is the simplest option
that supports scheduled and retried tasks at this scale.

### 6. Docker Compose for local infrastructure

- PostgreSQL and Redis sit on an internal network with no published ports. Only the API
  can reach them.
- The web app and the API are published on `127.0.0.1` only.
- Secrets have no defaults. Compose stops with an explanation if one is missing.
- Start order follows health, not just start: PostgreSQL healthy, then migrations
  complete, then the API ready, then the web app.
- Containers run as non-root users, and image versions are pinned.

## Deliberately not used

| Option | Reason |
| --- | --- |
| Microservices | One team and one domain. A service boundary would add network failure modes and distributed transactions exactly where atomicity matters most. |
| Kafka | The workload is a modest number of scheduled jobs, not a high-volume event stream. |
| Kubernetes | Compose covers local development. Deployment orchestration is a separate decision and is not needed to build the product. |
| LangGraph | AI generation is expected to be a single prompt-and-response step. An agent framework is unjustified until there is a multi-step workflow. |
| Redis as a data store | Conflicts with decision 4. |

## Consequences

- PostgreSQL is a hard dependency: when it is down, the API reports not ready and the
  stack does not serve traffic. This is intended.
- Correctness of publishing will rest on database constraints and transactions, so those
  need integration tests against a real PostgreSQL, not mocks. The test suite already
  separates unit tests from an `integration` marker for this.
- Workers will poll or be fed from the database, which adds a small scheduling delay
  compared with a pure queue. That is acceptable for posts scheduled to the minute.
- The frontend calls the API across origins, so CORS has to be configured correctly, and
  any future browser session mechanism has to be designed with that in mind.

## Phase 2 additions (accepted)

- LinkedIn OIDC `sub` is the external identity key (not email).
- Access tokens are encrypted at rest with AES-256-GCM in a versioned blob (`v1.<key_id>…`).
- Browser auth uses opaque server-side sessions (hashed in PostgreSQL), not JWTs.
- OAuth CSRF uses hashed one-time state plus an HttpOnly browser nonce cookie.
- No refresh-token flow: LinkedIn member tokens expire and require reauthorization.

## Open questions for later phases

These are not decided here:

- Encryption key rotation procedure in production.
- Mapping from OIDC `sub` to the LinkedIn person URN used by publishing APIs.
- The exact claiming and retry scheme for due posts.
- Which language-model provider is used, and how its cost and failures are bounded.
