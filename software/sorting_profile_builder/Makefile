.PHONY: run dev migrate

run:
	uv run python main.py

dev:
	uv run python -m uvicorn main:create_app --factory --reload --host 0.0.0.0 --port 8001

migrate:
	uv run python -c "from db import initDb; initDb('./parts.db')"
