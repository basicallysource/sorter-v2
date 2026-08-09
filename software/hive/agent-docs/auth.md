# Hive auth & permissions

Last verified against the code: 2026-08-08. If you touch auth, re-verify and
update this doc in the same change.

## The four credential types

Hive has four distinct principals. They are deliberately non-interchangeable —
each resolves against its own table, and presenting one type to another type's
endpoints is a 401.

| Credential | Table | Who/what it is | Guarded by (in `backend/app/deps.py`) |
|---|---|---|---|
| Session cookie | `users` (+ `refresh_tokens`) | A human in the browser. JWT access token cookie + refresh token, CSRF-protected. | `get_current_user` |
| API key (`hv_*`) | `user_api_keys` | A program acting *as a user* — CLI tools, bots, agents. Scoped, revocable, optionally expiring. | `get_current_user_or_api_key` + `require_api_key_scopes` |
| Machine token | `machines` | A *registered* sorter tied to an owner's account. Implicitly scoped to its own data (endpoints receive the `Machine` row). | `get_current_machine` |
| Device token | `devices` | The *unregistered* tier: a physical sorter silently enrolled the first time it touches hosted services, account or not. See the `Device` model docstring. | `get_current_device` |

All tokens are stored as SHA-256 hashes with a short display prefix; raw
values are shown exactly once at creation.

## API keys: deny-by-default scoping

Design philosophy: **a key grants exactly what its scopes say, nothing more.**

- Creation requires at least one scope. A key with no scopes (legacy rows)
  grants nothing.
- Scope vocabulary lives in `deps.py` (`VALID_API_KEY_SCOPES`): currently
  `models:read`, `models:write`, `samples:read`, `samples:write`,
  `keys:manage`.
- Keys may carry an optional `expires_at`; expired keys 401.
- Revocation is a tombstone (`revoked_at`), not a delete, so the UI can show
  history.
- `keys:manage` lets a key mint, list, and revoke keys via
  `/api/auth/api-keys` — this is how bots get programmatic key management.
  Key creation additionally requires the resolved user to be an admin.

**Invariant for endpoint authors:** any endpoint that accepts API-key auth
must pair `get_current_user_or_api_key` / `require_role_flex` with
`require_api_key_scopes(<scope>)`. The resolver alone only authenticates; the
scope guard is what enforces deny-by-default. Adding a new key-accessible
surface means adding a scope for it, not reusing a vaguely-related one.

Roles (`member` / `reviewer` / `admin` on `users.role`) still apply on top:
a key never grants more than the owning user's role allows.

## Sessions

Email+password and GitHub OAuth both resolve to a `users` row
(`backend/app/routers/auth.py`). Access token is a short-lived JWT in a
cookie; refresh tokens are persisted and rotated. Non-GET cookie-authed
requests require the CSRF header/cookie pair (`verify_csrf`); Bearer-authed
requests are exempt (self-authenticating).

## Where things are headed (so you don't design against the grain)

Planned direction, tracked in the sorter-v2-agent-notes repo (task
`hive-auth-permissions-overhaul-2026-08-08`):

- A `user_identities` table (provider, provider_user_id) replacing the
  provider-specific columns on `users`, so one account can link multiple
  sign-in methods (GitHub, Discord, …).
- Discord OAuth both as sign-in and as account-link, the link doubling as
  "verify this Hive account owns this Discord user" for the community server.
- Machine-scoped API keys: keys constrained to specific machines the user
  can access, for agents that should only see one sorter.
- Unifying the token plumbing (mint/hash/expiry/revocation) shared by user
  keys, machine tokens, and device tokens.
