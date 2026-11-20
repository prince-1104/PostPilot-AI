# LinkedIn real publishing (Phase 4B)

PostPilot can publish **text-only** member posts through LinkedIn’s Posts API when
explicitly enabled. The default provider remains the Phase 4A **fake** publisher.

## Permissions

OAuth scopes (must all be present in `LINKEDIN_SCOPES`):

| Scope | Purpose |
| --- | --- |
| `openid` `profile` `email` | Sign-in / identity |
| `w_member_social` | Create posts as the authenticated member |

The LinkedIn developer app needs **Sign In with LinkedIn using OpenID Connect** and
**Share on LinkedIn**. There is **no refresh token** for this flow — when the access
token expires, the user must reconnect.

## Member URN resolution

Author identity is never accepted from the frontend.

1. OAuth userinfo stores the OIDC `sub` on `users.linkedin_subject` and
   `linkedin_connections.provider_subject`.
2. At publish time PostPilot maps that subject to `urn:li:person:{sub}`.
3. Organization URNs are rejected. Restricted `/v2/me` is not used.
4. Claim verifies the connection belongs to the post owner before decrypting tokens.

## API request

```http
POST https://api.linkedin.com/rest/posts
Authorization: Bearer <decrypted_access_token>
Content-Type: application/json
X-Restli-Protocol-Version: 2.0.0
Linkedin-Version: 202611
```

Payload (text-only):

```json
{
  "author": "urn:li:person:{sub}",
  "commentary": "<scheduled post content exactly as approved>",
  "visibility": "PUBLIC",
  "distribution": {
    "feedDistribution": "MAIN_FEED",
    "targetEntities": [],
    "thirdPartyDistributionChannels": []
  },
  "lifecycleState": "PUBLISHED",
  "isReshareDisabledByAuthor": false
}
```

Success: HTTP **201** with `x-restli-id` of `urn:li:share:…` or `urn:li:ugcPost:…`.
A 201 without a valid post URN is treated as **ambiguous** (`requires_review`).

HTTPX uses explicit connect/read/write/pool timeouts. **Automatic HTTP retries for POST
are disabled.**

## Configuration (safe defaults)

| Variable | Default | Notes |
| --- | --- | --- |
| `PUBLISH_PROVIDER` | `fake` | `linkedin` only when real publishing is intended |
| `ENABLE_REAL_PUBLISHING` | `false` | Required for `PUBLISH_PROVIDER=linkedin` |
| `LINKEDIN_API_VERSION` | `202611` | YYYYMM digits |
| `LINKEDIN_API_BASE_URL` | `https://api.linkedin.com` | Locked to this HTTPS host |

Provider choice is backend/env only — never a frontend request parameter.
Custom publishing base URLs are refused at startup.

## Token security

- Decrypt only inside `RealLinkedInPublisher` on the worker.
- Never put tokens in Celery task args, logs, exception messages, or API responses.
- Expired / revoked tokens → no publish; sanitized failure; connection may move to
  `reauth_required`.

## Error classification (maps into Phase 4A engine)

| Condition | Outcome | Auto-retry? |
| --- | --- | --- |
| 201 + valid URN | success → `published` | — |
| 201 missing/malformed URN | ambiguous → `requires_review` | No |
| 401 / expired token | connection_expired → `failed` + reauth | No |
| 403 / missing scope | permanent → `failed` | No |
| 400 / 422 | permanent validation | No |
| 429 (+ Retry-After) | retryable → back to `scheduled` | Yes (max attempts) |
| 5xx | ambiguous → `requires_review` | No |
| Timeout / transport after submit | ambiguous → `requires_review` | No |

Retries, leases, fencing, and recovery remain the Phase 4A machinery. Do not invent a
second retry layer.

## Exactly-once limitations

LinkedIn does not accept a client idempotency key for Posts API creates. PostPilot
fencing prevents stale workers from overwriting newer DB state and prevents duplicate
claims, but a timeout after the request left the process can still mean the post exists
on LinkedIn while PostPilot marks `requires_review`. **Never blindly republish.**

## Investigating `requires_review`

1. Read `publish_attempts` for the post (HTTP status, sanitized codes).
2. Check the member’s LinkedIn feed for a matching post.
3. If published externally, leave the row as `requires_review` or manually reconcile —
   do not force another API create.
4. If confirmed not published and the failure was pre-network, recovery may have
   already requeued; otherwise create a **new** scheduled post after fixing auth.

## Manual browser E2E (live LinkedIn)

**Do not run live publish steps during automated tests.** See the full canary checklist in
[live-e2e-publishing.md](live-e2e-publishing.md).

In addition to OAuth + `ENABLE_REAL_PUBLISHING`, Phase 4C requires an explicit post ID on
`LIVE_PUBLISH_CANARY_POST_IDS` while `LIVE_PUBLISH_REQUIRE_CANARY=true` (default). An empty
allowlist blocks all real LinkedIn submissions even when the real provider is enabled.
