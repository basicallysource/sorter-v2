# Hive auth & permissions

Last verified against the code: 2026-08-09. If you touch auth, re-verify and
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
  `keys:manage`, `stats:read`.
- `stats:read` (admin-owned, non-machine-constrained keys only) grants the
  aggregate stats endpoint (`routers/public_stats.py`) — the replacement for
  the legacy `PUBLIC_STATS_API_KEY` shared secret, which stays accepted only
  until consumers cut over; then delete the env var and the legacy branch.
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

**Machine-scoped keys**: a key may carry a machine whitelist
(`user_api_keys.machine_ids`, null = unconstrained). The resolved constraint
rides on the request's `User` object as a transient `_api_key_machine_ids`
attribute — every auth path stamps it (None for cookie sessions), and the
access helpers in `services/access_window.py` check it *before* any
role-based early return, so a constrained key is strictly less powerful than
its owner even for admins. Creation validates the ids against machines the
creator owns. Enforced on samples, pieces, piece-derived tables, and channel
crops — i.e. all machine-owned data reachable by API keys today. If a new
surface becomes key-accessible and machine-owned, wire it through those
helpers (or replicate the constraint check) — don't skip it.

## Sessions & sign-in identities

Every sign-in method resolves to a `users` row. Access token is a short-lived
JWT in a cookie; refresh tokens are persisted and rotated. Non-GET
cookie-authed requests require the CSRF header/cookie pair (`verify_csrf`);
Bearer-authed requests are exempt (self-authenticating).

Sign-in methods:

- **Email + password** — `users.password_hash`.
- **OAuth (GitHub, Discord)** — one `user_identities` row per linked
  provider: `(user_id, provider, provider_user_id)`, unique per provider
  account (an external account belongs to at most one user) and per
  `(user_id, provider)` (one linked account of each provider per user).
  `users.github_id/github_login` no longer exist; `User.github_login` is a
  compatibility property reading the github identity, still served in
  user/profile responses.

Provider adapters live in `backend/app/services/oauth_providers.py` — each
implements authorize-URL / code-exchange / identity-fetch and returns a
normalized `OAuthIdentity`. Router code (`routers/auth.py`) is
provider-agnostic. Adding a provider = one adapter + settings entries
(`<PROVIDER>_CLIENT_ID/SECRET`, enabled-flag property in `config.py`).

Two OAuth entry points per provider:

- **Sign-in**: `/api/auth/{provider}` → callback resolves by identity row,
  falls back to verified-email merge (attaches the identity to the matching
  account), else creates a user. Returning users are matched by identity, so
  a changed provider email never forks the account.
- **Link**: `/api/auth/{provider}/link` (logged-in browser) → same dance,
  but the callback attaches the identity to the *current* user and redirects
  to /settings. This is the Discord-verification primitive: a
  `user_identities` row for discord is proof the Hive account controls that
  Discord user. Errors (identity already claimed, no session) redirect to
  /settings?error=….

`GET /api/auth/identities` lists the current user's linked identities;
`DELETE /api/auth/identities/{provider}` unlinks, refusing to remove the last
remaining sign-in method (`LAST_SIGN_IN_METHOD`). `/api/auth/options` reports
`{provider}_enabled` flags to the frontend (login/register buttons, settings
Connected Accounts card).

## Where things are headed (so you don't design against the grain)

Planned direction, tracked in the sorter-v2-agent-notes repo (task
`hive-auth-permissions-overhaul-2026-08-08`):

- Discord server verification / role sync built on linked identities (bot
  looks up members by discord `provider_user_id`).
- Machine-scoped API keys: keys constrained to specific machines the user
  can access, for agents that should only see one sorter.
- Unifying the token plumbing (mint/hash/expiry/revocation) shared by user
  keys, machine tokens, and device tokens.
