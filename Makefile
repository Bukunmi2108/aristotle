SHELL := /bin/bash

.DEFAULT_GOAL := help

WEB_PORT ?= 5173
API_PORT ?= 8400
SEARCH_PORT ?= 8300
POSTGRES_PORT ?= 5433
API_IMAGE ?= aristotle-api
API_CONTAINER ?= aristotle-api-dev
SEARCH_IMAGE ?= aristotle-search
SEARCH_CONTAINER ?= aristotle-search-dev
POSTGRES_CONTAINER ?= aristotle-postgres-dev
POSTGRES_DB ?= aristotle
POSTGRES_USER ?= aristotle
DEV_NETWORK ?= aristotle-dev

.PHONY: help dev web api api-build api-stop search search-build search-stop postgres postgres-stop dev-network check-dev

help:
	@echo "Targets:"
	@echo "  make dev           Start web, api, and search together"
	@echo "  make web           Start the Vite web app on port $(WEB_PORT)"
	@echo "  make api           Start Postgres and the API Docker container on port $(API_PORT)"
	@echo "  make api-build     Build the local API Docker image"
	@echo "  make api-stop      Stop the local API Docker container"
	@echo "  make search        Start the search Docker container on port $(SEARCH_PORT)"
	@echo "  make search-build  Build the local search Docker image"
	@echo "  make search-stop   Stop the local search Docker container"
	@echo "  make postgres      Start the local Postgres container on port $(POSTGRES_PORT)"
	@echo "  make postgres-stop Stop the local Postgres container"

dev: check-dev dev-network
	@set -euo pipefail; \
	echo "Starting Aristotle dev stack"; \
	echo "  web:    http://localhost:$(WEB_PORT)"; \
	echo "  api:    http://localhost:$(API_PORT)"; \
	echo "  search: http://localhost:$(SEARCH_PORT)"; \
	echo "  db:     localhost:$(POSTGRES_PORT)/$(POSTGRES_DB)"; \
	cleanup() { \
		status=$$?; \
		trap - INT TERM EXIT; \
		echo; \
		echo "Stopping Aristotle dev stack"; \
		kill "$$WEB_PID" 2>/dev/null || true; \
		docker stop "$(API_CONTAINER)" >/dev/null 2>&1 || true; \
		docker stop "$(SEARCH_CONTAINER)" >/dev/null 2>&1 || true; \
		docker stop "$(POSTGRES_CONTAINER)" >/dev/null 2>&1 || true; \
		wait "$$WEB_PID" "$$API_PID" "$$SEARCH_PID" 2>/dev/null || true; \
		exit $$status; \
	}; \
	trap cleanup INT TERM EXIT; \
	$(MAKE) --no-print-directory api-stop >/dev/null 2>&1 || true; \
	$(MAKE) --no-print-directory search-stop >/dev/null 2>&1 || true; \
	( $(MAKE) --no-print-directory search ) & SEARCH_PID=$$!; \
	( $(MAKE) --no-print-directory api ) & API_PID=$$!; \
	( $(MAKE) --no-print-directory web ) & WEB_PID=$$!; \
	wait "$$SEARCH_PID" "$$API_PID" "$$WEB_PID"

web:
	@cd web && \
	VITE_AGENT_HTTP_BASE_URL="http://localhost:$(API_PORT)" \
	VITE_AGENT_WS_BASE_URL="ws://localhost:$(API_PORT)" \
	npm run dev -- --host 0.0.0.0 --port "$(WEB_PORT)"

api: dev-network postgres api-build
	@set -euo pipefail; \
	env_args=(); \
	if [ -f .env ]; then env_args+=(--env-file .env); fi; \
	if [ -f api/.env ]; then env_args+=(--env-file api/.env); fi; \
	if [ -n "$${DATABASE_URL:-}" ]; then env_args+=(-e DATABASE_URL); fi; \
	if [ -z "$${DATABASE_URL:-}" ] && ! grep -qs '^DATABASE_URL=' .env api/.env 2>/dev/null; then \
		echo "DATABASE_URL must be set in the shell, .env, or api/.env"; \
		exit 1; \
	fi; \
	docker rm -f "$(API_CONTAINER)" >/dev/null 2>&1 || true; \
	docker run --rm \
		--name "$(API_CONTAINER)" \
		--network "$(DEV_NETWORK)" \
		"$${env_args[@]}" \
		-e PORT=7860 \
		-e ARISTOTLE_SEARCH_BASE_URL="http://$(SEARCH_CONTAINER):7860" \
		-p "$(API_PORT):7860" \
		"$(API_IMAGE)"

api-build:
	@docker build -t "$(API_IMAGE)" ./api

api-stop:
	@docker stop "$(API_CONTAINER)" >/dev/null

search: dev-network search-build
	@set -euo pipefail; \
	env_args=(); \
	if [ -f search/.env ]; then env_args+=(--env-file search/.env); fi; \
	docker rm -f "$(SEARCH_CONTAINER)" >/dev/null 2>&1 || true; \
	docker run --rm \
		--name "$(SEARCH_CONTAINER)" \
		--network "$(DEV_NETWORK)" \
		"$${env_args[@]}" \
		-p "$(SEARCH_PORT):7860" \
		"$(SEARCH_IMAGE)"

search-build:
	@docker build -t "$(SEARCH_IMAGE)" ./search

search-stop:
	@docker stop "$(SEARCH_CONTAINER)" >/dev/null

postgres: dev-network
	@set -euo pipefail; \
	env_args=(); \
	if [ -f .env ]; then env_args+=(--env-file .env); fi; \
	if [ -f api/.env ]; then env_args+=(--env-file api/.env); fi; \
	if [ -n "$${POSTGRES_PASSWORD:-}" ]; then env_args+=(-e POSTGRES_PASSWORD); fi; \
	if [ -z "$${POSTGRES_PASSWORD:-}" ] && ! grep -qs '^POSTGRES_PASSWORD=' .env api/.env 2>/dev/null; then \
		echo "POSTGRES_PASSWORD must be set in the shell, .env, or api/.env"; \
		exit 1; \
	fi; \
	docker rm -f "$(POSTGRES_CONTAINER)" >/dev/null 2>&1 || true; \
	docker run -d --rm \
		--name "$(POSTGRES_CONTAINER)" \
		--network "$(DEV_NETWORK)" \
		"$${env_args[@]}" \
		-e POSTGRES_DB="$(POSTGRES_DB)" \
		-e POSTGRES_USER="$(POSTGRES_USER)" \
		-p "$(POSTGRES_PORT):5432" \
		--tmpfs /var/lib/postgresql/data \
		postgres:16-alpine >/dev/null; \
	echo "Waiting for Postgres"; \
	for attempt in $$(seq 1 30); do \
		if docker exec "$(POSTGRES_CONTAINER)" pg_isready -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" >/dev/null 2>&1; then \
			echo "Postgres ready on localhost:$(POSTGRES_PORT)"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Postgres did not become ready in time"; \
	docker logs "$(POSTGRES_CONTAINER)" || true; \
	exit 1

postgres-stop:
	@docker stop "$(POSTGRES_CONTAINER)" >/dev/null

dev-network:
	@docker network create "$(DEV_NETWORK)" >/dev/null 2>&1 || true

check-dev:
	@command -v docker >/dev/null || { echo "docker is required"; exit 1; }
	@command -v npm >/dev/null || { echo "npm is required"; exit 1; }
