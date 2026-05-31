.PHONY: install dev migrate reset-db backend frontend bootstrap-admin

install:
	cd backend && uv sync
	cd frontend && pnpm install

dev:
	$(MAKE) backend & $(MAKE) frontend & wait

backend:
	# Bind dual-stack (IPv6 + IPv4). Default 127.0.0.1 broke browsers
	# that resolve localhost → ::1 first (Happy Eyeballs picks IPv6,
	# fetch() doesn't always fall back to IPv4 the way curl does).
	cd backend && uv run uvicorn app.main:app --reload --host :: --port 8002

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
