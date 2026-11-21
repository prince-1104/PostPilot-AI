# Safe live LinkedIn E2E verification

**Do not run the enable/publish steps automatically.** This document is a manual
operator checklist for publishing to your **real LinkedIn profile**. Automated tests
keep using the fake provider and mocked HTTP only.

Author identity: PostPilot builds `urn:li:person:{oidc_sub}` from the Sign In with
LinkedIn userinfo `sub` claim (documented LinkedIn self-serve flow). If LinkedIn
returns 403 on author, reconnect with `w_member_social` and inspect readiness —
do not invent a member ID.

## Safety model

Every real LinkedIn publish also requires **durable database approval** on the post
(`publish_approved_at` + matching content/schedule hash). The UI Schedule & Publish
confirmation (or Approve on an existing scheduled post) stamps that approval from the
authenticated session. Historical rows stay unapproved until the user confirms them.

### Test canary mode (initial live verification)

| Variable | Safe default | Live test value |
| --- | --- | --- |
| `PUBLISH_PROVIDER` | `fake` | `linkedin` |
| `ENABLE_REAL_PUBLISHING` | `false` | `true` |
| `LIVE_PUBLISH_REQUIRE_CANARY` | `true` | `true` |
| `LIVE_PUBLISH_CANARY_POST_IDS` | _(empty)_ | **one** DB-approved post UUID |

With canary required and an empty allowlist, **no** LinkedIn API publishes occur even
if the real provider is enabled and posts are DB-approved.

### Normal production mode (after one successful canary)

| Variable | Value |
| --- | --- |
| `PUBLISH_PROVIDER` | `linkedin` |
| `ENABLE_REAL_PUBLISHING` | `true` |
| `LIVE_PUBLISH_REQUIRE_CANARY` | `false` |

Disabling the canary **never** bypasses per-post database approval. Due unapproved
posts are not leased. Do not flip canary off until the user explicitly authorizes
production mode after a verified live canary post.

## Diagnostic endpoint (no secrets)

```http
GET /api/v1/publishing/readiness
GET /api/v1/publishing/readiness?post_id=<uuid>
```

Cookie session required. Response includes `configured`, `ready_for_test`,
`publishing_verified` (true only after a real non-fake LinkedIn URN is persisted),
canary settings, pending post counts, and per-check details. Tokens never appear.

## Manual procedure

### Steps 1–5 (prepare; safe)

1. Open `/connections` and confirm the real LinkedIn OAuth session (connected, scopes
   include `w_member_social`, token unexpired).
2. Call readiness: `GET /api/v1/publishing/readiness` (browser session or curl with cookie).
3. Create **one** short harmless test post in the UI (`/posts/new`), scheduled slightly
   in the future (`SCHEDULE_MIN_LEAD_SECONDS`).
4. Confirm exact content and `scheduled_at` on `/posts/{id}` and in PostgreSQL.
5. Copy the post UUID. Set in `.env` (api **and** worker/beat via Compose):

```env
LIVE_PUBLISH_REQUIRE_CANARY=true
LIVE_PUBLISH_CANARY_POST_IDS=<that-uuid-only>
```

Re-check: `GET /api/v1/publishing/readiness?post_id=<uuid>` →
`selected_post_canary_approved=true`, `pending_scheduled_non_canary` shows other posts.

### Steps 6–12 (operator-only; do not automate)

6. Enable real publishing on **worker** (and api if diagnosing), then recreate services:

```powershell
# From repo root — review .env first
# PUBLISH_PROVIDER=linkedin
# ENABLE_REAL_PUBLISHING=true
# LIVE_PUBLISH_CANARY_POST_IDS=<uuid>
docker compose up -d --force-recreate api worker beat
docker compose logs -f worker beat
```

7. Observe Celery Beat `dispatch-due-posts` and Worker `execute_publish` for **only**
   the canary UUID.
8. Capture sanitized post status, attempt row (`provider_http_status`,
   `sanitized_error_code`, attempt id) via UI or SQL — never Authorization headers.
9. Expect HTTP **201** and `x-restli-id` → persisted `linkedin_post_urn`
   (`urn:li:share:…` or `urn:li:ugcPost:…`).
10. Confirm PostgreSQL: `status=published`, `published_at` set, fake URN prefix absent.
11. Confirm the post on the LinkedIn profile / permalink from the post detail page.
12. **Rollback to safe config:**

```env
PUBLISH_PROVIDER=fake
ENABLE_REAL_PUBLISHING=false
LIVE_PUBLISH_REQUIRE_CANARY=true
LIVE_PUBLISH_CANARY_POST_IDS=
```

```powershell
docker compose up -d --force-recreate api worker beat
```

## Failure investigation

| Signal | Action |
| --- | --- |
| 401 / token expired | Reconnect OAuth; do not invent refresh |
| 403 / missing scope | Re-authorize with `w_member_social` |
| `live_publish_canary_blocked` | Post not on allowlist — intentional |
| 5xx / timeout / missing URN | Leave `requires_review`; **do not** auto-retry or switch endpoints |
| Ambiguous after submit | Check LinkedIn feed before any new create |

Never log bearer tokens. Never fall back to legacy UGC endpoints to bypass auth errors.

## Rollback checklist

- [ ] `LIVE_PUBLISH_CANARY_POST_IDS` cleared
- [ ] `PUBLISH_PROVIDER=fake`
- [ ] `ENABLE_REAL_PUBLISHING=false`
- [ ] `LIVE_PUBLISH_REQUIRE_CANARY=true` (keep gate for next time)
- [ ] api / worker / beat recreated
- [ ] Readiness shows `ready_for_test=false`, `publish_provider=fake`
