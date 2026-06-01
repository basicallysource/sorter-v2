.PHONY: install dev migrate reset-db backend frontend bootstrap-admin

install:
	cd backend && uv sync
	cd frontend && pnpm install

dev:
	$(MAKE) backend & $(MAKE) frontend & wait

backend:
	# Bind 0.0.0.0 so IPv4 clients connect (the Sorter Pi dials the Mac's
	# LAN/Tailscale IPv4 address). uvicorn's `--host ::` came up IPv6-only
	# here, refusing every IPv4 connection. On the Mac use http://127.0.0.1
	# (not localhost, which resolves to ::1 first) to hit the dev server.
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8002

frontend:
	cd frontend && pnpm dev --port 5174

migrate:
	cd backend && uv run alembic upgrade head

revision:
	cd backend && uv run alembic revision --autogenerate -m "$(msg)"

reset-db:
	docker compose down -v
	docker compose up -d
	sleep 2
	$(MAKE) migrate

bootstrap-admin:
	cd backend && uv run python -m app.bootstrap_admin
