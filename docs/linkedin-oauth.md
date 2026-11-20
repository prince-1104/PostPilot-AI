# LinkedIn OAuth (Phase 2)

This document explains how PostPilot AI connects a LinkedIn account. Publishing is not
implemented yet; the stored access token is kept for a later phase.

## LinkedIn developer app

1. Create an application at [LinkedIn Developers](https://www.linkedin.com/developers/apps).
2. Enable these products (names can change; confirm in the portal):
   - **Sign In with LinkedIn using OpenID Connect** — provides `openid`, `profile`, and
     `email`.
   - **Share on LinkedIn** — provides `w_member_social` (needed later for publishing).
3. Under **Auth**, add this authorized redirect URL exactly:

   ```text
   http://localhost:8000/api/v1/auth/linkedin/callback
   ```

4. Copy the **Client ID** and **Client Secret** into `.env` as `LINKEDIN_CLIENT_ID` and
   `LINKEDIN_CLIENT_SECRET`.

If a required product or scope is missing, the API refuses to start (configuration) or
fails the callback with an actionable error (token response). It does not silently drop
scopes.

## Local environment

In addition to the Phase 1 database secrets, set:

| Variable | Purpose |
| --- | --- |
| `LINKEDIN_CLIENT_ID` | OAuth client ID |
| `LINKEDIN_CLIENT_SECRET` | OAuth client secret (never sent to the browser) |
| `LINKEDIN_REDIRECT_URI` | Must match the LinkedIn app redirect URL |
| `LINKEDIN_SCOPES` | `openid profile email w_member_social` |
| `TOKEN_ENCRYPTION_KEY` | Base64-encoded 32-byte AES-256 key |
| `WEB_BASE_URL` | Frontend origin for post-login redirects |
| `COOKIE_SECURE` | `false` on local HTTP; `true` in production HTTPS |
| `SESSION_TTL_SECONDS` | Opaque session lifetime |

Generate the encryption key:

```sh
uv run --no-project python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Rebuild and restart after changing `.env`:

```sh
docker compose up -d --build --wait
```

## OAuth lifecycle

1. The browser opens `GET /api/v1/auth/linkedin`.
2. The API creates a random `state` and browser `nonce`, stores only their SHA-256 hashes
   with a short TTL, and sets the nonce in an HttpOnly cookie.
3. The browser is redirected to LinkedIn’s authorization URL. The client secret is never
   included in that URL.
4. LinkedIn redirects to
   `GET /api/v1/auth/linkedin/callback` with `code` and `state` (or an error).
5. The API validates and atomically consumes the state, checks the nonce cookie, exchanges
   the code server-side, validates the OIDC ID token (JWKS signature, issuer, audience,
   expiry), calls userinfo, and verifies `userinfo.sub == id_token.sub`.
6. Granted scopes are verified explicitly. Token-exchange `scope` is parsed as a
   space-delimited (URL-decoded) list. If LinkedIn omits `scope`, the API calls
   `POST /oauth/v2/introspectToken` and parses its comma-delimited `scope`. Requested
   scopes are never assumed granted.
7. The user is upserted by LinkedIn OIDC `sub` (not email). The access token is encrypted
   with AES-256-GCM and stored. An opaque session cookie is issued.
8. The browser is redirected to `{WEB_BASE_URL}/connections?oauth=success`. Tokens never
   appear in the redirect URL.

If the user is already signed in, reconnect is allowed only for the same LinkedIn
subject. A different account is rejected.

## Sessions and encryption

- Sessions are random opaque tokens. PostgreSQL stores only the SHA-256 hash.
- Cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` according to `COOKIE_SECURE`.
- Access tokens are encrypted as `v1.<key_id>.<nonce>.<ciphertext>` so key rotation can be
  added later without rewriting the format.
- Decrypted tokens are never returned by the API and are redacted from logs.

## Token expiration

LinkedIn member access tokens for this flow typically last about 60 days and **do not**
include a refresh token. PostPilot records the `expires_in` value from the token response.
When the token is expired or missing, the connections API reports
`reauthorization_required` and the UI offers reconnect. There is no invented refresh flow.

The OIDC `sub` is the identity key for PostPilot. It is **not** interchangeable with the
LinkedIn person URN used by publishing APIs; that mapping belongs to a later phase.

## Testing a real connection in the browser

1. Ensure the LinkedIn app redirect URL and `.env` values match.
2. Start the stack: `docker compose up -d --build --wait`.
3. Open http://localhost:3000/connections.
4. Click **Connect with LinkedIn**, approve the consent screen, and confirm you return to
   `/connections` with your real name (and avatar when LinkedIn provides one).
5. Confirm **Sign out** clears the session and **Disconnect** clears the stored token while
   keeping the PostPilot user.

Automated tests mock LinkedIn; they never use real credentials.
