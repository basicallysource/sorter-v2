# SortHive

Community platform for collaborative Lego training data collection and verification.

## Setup

```bash
# Start Postgres
docker compose up -d

# Install dependencies
make install

# Run migrations
make migrate

# Seed first admin user
make seed-admin

# Start dev servers (backend :8001 + frontend :5174)
make dev
```

If you run the built frontend directly instead of `pnpm dev`, set `PUBLIC_API_BASE_URL` for the frontend process, for example:

```bash
PUBLIC_API_BASE_URL=http://localhost:8001 node build
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
http://localhost:8001/api/auth/github/callback
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
- a host such as `sorthive.neuhaus.nrw`
- `https://<domain>/api/*` routed to the backend
- all other paths routed to the frontend

On startup, the backend automatically runs Alembic migrations and bootstraps an admin user from `ADMIN_EMAIL` / `ADMIN_PASSWORD` if those values are set.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + PostgreSQL (port 8001)
- **Frontend**: SvelteKit + Tailwind CSS (port 5174)
- **Storage**: Local filesystem for uploaded images
