# Hive

Community platform for collaborative Lego training data collection and verification.

## Setup

```bash
# Start Postgres
docker compose up -d

# Install dependencies
make install

# Run migrations
make migrate

# Bootstrap first admin user (uses ADMIN_EMAIL / ADMIN_PASSWORD from .env)
make bootstrap-admin

# Start dev servers (backend :8002 + frontend :5174)
make dev
```

If you run the built frontend directly instead of `pnpm dev`, set `PUBLIC_API_BASE_URL` for the frontend process, for example:

```bash
PUBLIC_API_BASE_URL=http://localhost:8002 node build
```

Without that, a standalone frontend process on another port cannot reach the backend `/api` routes by itself.

## Configuration

Copy `.env.example` to `backend/.env` and adjust values as needed.

For GitHub login, create an OAuth app in GitHub and set:

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_REDIRECT_URI`

For local development, the redirect URI should typically be:

```text
http://localhost:8002/api/auth/github/callback
```

Using the backend callback directly avoids dev-proxy cookie edge cases during the OAuth redirect back from GitHub.

If GitHub login fails with an email-permission error, double-check that you created an OAuth App under `Developer settings -> OAuth Apps`.
If you intentionally use a GitHub App instead, it must have `Account permissions -> Email addresses -> Read-only`, and you need to re-authorize it after changing permissions.

The login session is designed as a short-lived access token plus a rotating refresh token in persistent cookies, so users remain signed in across browser restarts until the refresh window expires or they log out.

## Production Docker

For a server deployment behind Traefik, use `docker-compose.prod.yml`.

1. Copy `.env.prod.example` to `.env.prod`
2. Set strong values for:
   - `POSTGRES_PASSWORD`
   - `JWT_SECRET`
   - `ADMIN_PASSWORD`
3. Optionally add GitHub OAuth production credentials
4. Start the stack:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

The production stack expects:
- Traefik running on the external Docker network `web`
- a host such as `hive.neuhaus.nrw`
- `https://<domain>/api/*` routed to the backend
- all other paths routed to the frontend

On startup, the backend automatically runs Alembic migrations and bootstraps an admin user from `ADMIN_EMAIL` / `ADMIN_PASSWORD` if those values are set.

### Persisted data

The backend bind-mounts two host directories under `software/hive/data/` so they
survive container rebuilds/recreates:

- `data/uploads` — uploaded sample images
- `data/profile_builder` — the Rebrickable parts catalog SQLite db
  (`parts.db`: parts, categories, colors). **Without this mount the catalog
  lives only in the container layer and is wiped on every recreate, forcing a
  full multi-hour re-sync from Rebrickable on each deploy.**

`REBRICKABLE_API_KEY` must be set in `.env.prod` for the catalog auto-sync to run.

To seed `parts.db` (e.g. from a machine that already has a populated catalog)
instead of syncing from scratch, copy a clean snapshot into the host dir before
starting the stack — the container runs as uid `100`, so the dir and file must
be writable by it:

```bash
# on the source machine: make a consistent copy (works even while the db is open)
python -c "import sqlite3; s=sqlite3.connect('parts.db'); d=sqlite3.connect('/tmp/parts_seed.db'); s.backup(d)"
# on the server:
mkdir -p software/hive/data/profile_builder
scp /tmp/parts_seed.db <server>:.../software/hive/data/profile_builder/parts.db
chown -R 100:101 software/hive/data/profile_builder
```

The catalog db carries its own `schema_version`; the backend applies only the
parts-db migrations newer than that version on open, so a seeded db from a newer
build is used as-is (no downgrade needed).

## Architecture

- **Backend**: FastAPI + SQLAlchemy + PostgreSQL (port 8002)
- **Frontend**: SvelteKit + Tailwind CSS (port 5174)
- **Storage**: Local filesystem for uploaded images
