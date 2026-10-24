# OpenPoke developer commands (macOS/Linux). Run `make help` for the list.

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

# First Python 3.10+ interpreter on PATH; override with `make setup PYTHON=/path/to/python`.
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11 python3.10 python3; do \
	command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null && { echo $$p; break; }; \
	done)

# API port comes from OPENPOKE_PORT (environment or .env), defaulting to 8001 like server/config.py.
# Named API_PORT, not PORT, because Next.js would also bind to an exported PORT.
API_PORT ?= $(or $(OPENPOKE_PORT),$(shell sed -n 's/^OPENPOKE_PORT=//p' .env 2>/dev/null | tr -d "\"' "),8001)

PID_FILE := .server.pid
LOG_FILE := .server.log
REQUIRED_ENV := OPENROUTER_API_KEY COMPOSIO_API_KEY COMPOSIO_GMAIL_AUTH_CONFIG_ID

# Next.js dev server pointed at the API port (an existing PY_SERVER_URL wins).
WEB_DEV = env -u PORT PY_SERVER_URL="$${PY_SERVER_URL:-http://localhost:$(API_PORT)}" npm run dev --prefix web

.PHONY: help setup env install dev web start stop logs check-env health clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: env install ## First-time setup: create .env, venv, and install all dependencies
	@echo "Setup complete. Fill in your keys in .env, then run 'make check-env' and 'make dev'."

env:
	@if [ -f .env ]; then echo ".env already exists, leaving it alone"; \
	else cp .env.example .env && echo "Created .env from .env.example; add your API keys"; fi

$(PY):
	@if [ -z "$(PYTHON)" ]; then echo "Python 3.10+ not found; install it or pass PYTHON=/path/to/python" >&2; exit 1; fi
	@echo "Creating $(VENV) with $$($(PYTHON) --version)"
	$(PYTHON) -m venv $(VENV)

install: $(VENV)/.installed web/node_modules/.installed ## Install backend and frontend dependencies

$(VENV)/.installed: server/requirements.txt | $(PY)
	$(PIP) install -r server/requirements.txt
	@touch $@

web/node_modules/.installed: web/package-lock.json
	npm ci --prefix web
	@touch $@

dev: install ## Run the API server (with reload) and web app together; Ctrl-C stops both
	@trap 'kill 0' INT TERM EXIT; \
	$(PY) -m server.server --reload --port $(API_PORT) & \
	$(WEB_DEV) & \
	wait

web: web/node_modules/.installed ## Run only the web UI (expects the API server from 'make start')
	@$(WEB_DEV)

start: install ## Start the API server in the background (logs to .server.log)
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "Server already running (pid $$(cat $(PID_FILE)))"; exit 0; fi; \
	nohup $(PY) -m server.server --port $(API_PORT) > $(LOG_FILE) 2>&1 & echo $$! > $(PID_FILE); \
	echo "Server started on port $(API_PORT) (pid $$(cat $(PID_FILE))); 'make logs' to follow output"

stop: ## Stop the background API server
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		kill $$(cat $(PID_FILE)) && echo "Stopped server (pid $$(cat $(PID_FILE)))"; \
	else echo "Server not running"; fi; \
	rm -f $(PID_FILE)

logs: ## Follow the background server's log
	@touch $(LOG_FILE)
	tail -f $(LOG_FILE)

check-env: ## Verify required keys are set (environment or .env) and not placeholders
	@missing=0; \
	for key in $(REQUIRED_ENV); do \
		val="$${!key}"; \
		if [ -z "$$val" ] && [ -f .env ]; then \
			val=$$(sed -n "s/^$$key=//p" .env | tail -n 1 | tr -d "\"' "); fi; \
		if [ -z "$$val" ] || [[ "$$val" == your_*_here ]]; then \
			echo "  ✗ $$key is missing or still a placeholder"; missing=1; \
		else echo "  ✓ $$key"; fi; \
	done; \
	exit $$missing

health: ## Check the running API server's health endpoint
	@curl -fsS http://localhost:$(API_PORT)/api/v1/health && echo || \
		{ echo "No healthy server on port $(API_PORT)" >&2; exit 1; }

clean: ## Remove caches, build output, and server log/pid files
	find server -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf web/.next $(LOG_FILE) $(PID_FILE)
