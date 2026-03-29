PYTHON := /opt/homebrew/opt/python@3.11/bin/python3.11

kill:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@pkill -9 -f "client/main.py" 2>/dev/null || true
	@echo "Killed processes on ports 8000/5173 and any zombie client/main.py processes"

install:
	cd client && uv sync
	cd ui && pnpm install

dev:
	@./dev.sh

dev-backend:
	@./dev.sh backend

dev-frontend:
	@./dev.sh frontend

run:
	@bash -c 'trap "kill 0" SIGINT; $(PYTHON) client/main.py & cd ui && pnpm dev'
format:
	ruff format client
check:
	pyright --project client/pyproject.toml client
generate:
	@echo "Starting FastAPI server..."
	@$(PYTHON) client/api_only.py & echo $$! > .api.pid
	@sleep 2
	@echo "Generating REST API types..."
	@cd ui && npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/rest.ts
	@kill $$(cat .api.pid) && rm .api.pid
	@echo "Generating WebSocket event types..."
	@$(PYTHON) scripts/export_types.py ui/src/lib/api/events.ts
	@echo "Types generated in ui/src/lib/api/"
list-cameras:
	ffmpeg -f avfoundation -list_devices true -i ""
