# Safe live LinkedIn E2E verification (Phase 4C)

**Do not run the enable/publish steps automatically.** This document is a manual
operator checklist. Automated tests use the fake provider and mocked HTTP only.

## Safety model

Live publishing requires **all** of:

| Variable | Safe default | Live test value |
| --- | --- | --- |
| `PUBLISH_PROVIDER` | `fake` | `linkedin` |
| `ENABLE_REAL_PUBLISHING` | `false` | `true` |
| `LIVE_PUBLISH_REQUIRE_CANARY` | `true` | `true` |
| `LIVE_PUBLISH_CANARY_POST_IDS` | _(empty)_ | **one** approved post UUID |

With canary required and an empty allowlist, **no** LinkedIn API publishes occur even
if the real provider is enabled. Historical scheduled posts are not leased for dispatch.

After verification, clear the allowlist and set `PUBLISH_PROVIDER=fake` /
`ENABLE_REAL_PUBLISHING=false` again (recommended). To disable the canary gate entirely
set `LIVE_PUBLISH_REQUIRE_CANARY=false` — only after you accept that every due post may
publish.

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
