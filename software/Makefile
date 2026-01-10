PYTHON := /opt/homebrew/opt/python@3.11/bin/python3.11

kill:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@pkill -9 -f "client/main.py" 2>/dev/null || true
	@echo "Killed processes on port 8000 and any zombie client/main.py processes"

install:
	$(PYTHON) -m pip install -r client/requirements.txt
	cd ui && npm install

run:
	@bash -c 'trap "kill 0" SIGINT; $(PYTHON) client/main.py & cd ui && npm run dev'
upload:
	mpremote cp firmware/feeder/main.py :main.py
format:
	ruff format client
check:
	pyright client
generate:
	@echo "Starting FastAPI server..."
	@$(PYTHON) client/main.py & echo $$! > .api.pid
	@sleep 2
	@echo "Generating REST API types..."
	@cd ui && npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/rest.ts
	@kill $$(cat .api.pid) && rm .api.pid
	@echo "Generating WebSocket event types..."
	@$(PYTHON) scripts/export_types.py ui/src/lib/api/events.ts
	@echo "Types generated in ui/src/lib/api/"
