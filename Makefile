.PHONY: install run migrate test lint smoke \
        docker-up docker-down docker-build docker-migrate docker-test docker-shell \
        docker-up-api docker-logs-api docker-restart-api

# =============================================================================
# Local Development (requires local Python venv + local PostgreSQL)
# =============================================================================

install:
	pip install -e ".[dev]"

run:
	python -m agent_trading.main

migrate:
	python -m agent_trading.db.migrations.run

test:
	python -m pytest tests/ -v

smoke:
	python3 -m pytest tests/smoke/test_kis_paper_smoke.py -v -m "smoke" -W ignore::DeprecationWarning

smoke-all:
	python3 -m pytest tests/smoke/test_kis_paper_smoke.py -v -m "smoke or slow" -W ignore::DeprecationWarning

lint:
	@echo "Running ruff ..."
	python -m pip install ruff -q && python -m ruff check src/

# =============================================================================
# API Server (FastAPI)
# =============================================================================

# 운영 실행 — INSPECTION_API_TOKEN 미설정 시 startup fail (safe default)
run-api:
	uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 8000

# 개발 편의용 — 고정 개발 토큰을 자동 주입
run-api-dev:
	INSPECTION_API_TOKEN=dev-token-123 \
	uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 8000

# =============================================================================
# Docker Development (requires Docker + docker compose)
# =============================================================================

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-build:
	docker compose build

docker-migrate:
	docker compose exec app python -m agent_trading.db.migrations.run

docker-test:
	docker compose exec app python -m pytest tests/ -v

docker-shell:
	docker compose exec app /bin/bash

# Start only the DB + API services (no dev shell)
# Usage: make docker-up-api
docker-up-api:
	docker compose up -d db api

# Tail the API server logs
docker-logs-api:
	docker compose logs -f api

# Restart the API server container
docker-restart-api:
	docker compose restart api
