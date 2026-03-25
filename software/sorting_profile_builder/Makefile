.PHONY: run migrate

run:
	uv run python main.py

migrate:
	uv run python -c "from db import initDb; initDb('./parts.db')"
