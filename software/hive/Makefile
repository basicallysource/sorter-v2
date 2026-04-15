.PHONY: install dev migrate reset-db backend frontend

install:
	cd backend && uv sync
	cd frontend && pnpm install

dev:
	$(MAKE) backend & $(MAKE) frontend & wait

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8002

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

seed-admin:
	cd backend && uv run python -m app.seed_admin
