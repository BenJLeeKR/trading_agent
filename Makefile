.PHONY: install run migrate test lint smoke \
        docker-up docker-down docker-build docker-migrate docker-test docker-shell \
        docker-up-api docker-logs-api docker-restart-api \
        run-api-inmemory run-api-postgres

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
#
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  실행 방식 비교                                                        ║
# ║                                                                        ║
# ║  run-api-inmemory  → module-level app (항상 in_memory + auth disabled) ║
# ║  run-api-postgres  → create_app_from_env --factory (환경변수 적용)     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# ⚠️  module-level app (agent_trading.api.app:app) 사용
#     → runtime_mode="in_memory" 고정, auth_enabled=False 고정
#     → INSPECTION_API_TOKEN, API_RUNTIME_MODE 환경변수는 무시됨
#     → 개발/테스트용으로만 사용
run-api-inmemory:
	uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 8000

# ⚠️  INSPECTION_API_TOKEN을 설정해도 module-level app이므로 in_memory
#     (환경변수를 주는 것 자체가 무의미함을 강조)
#     → 개발/테스트용으로만 사용
run-api-inmemory-dev:
	INSPECTION_API_TOKEN=dev-token-123 \
	uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 8000

# ✅  create_app_from_env --factory 사용
#     → API_RUNTIME_MODE, INSPECTION_API_TOKEN, INSPECTION_API_ROLE 환경변수 적용
#     → API_RUNTIME_MODE=postgres 시 PostgreSQL 연결 필요
#     → INSPECTION_API_TOKEN 미설정 시 startup fail (safe default)
#     → 사전에 DATABASE_* 환경변수 export 또는 .env 로드 필요
#
# 사용 예:
#   source .env && make run-api-postgres
#   API_RUNTIME_MODE=postgres INSPECTION_API_TOKEN=dev-token-123 make run-api-postgres
run-api-postgres:
	API_RUNTIME_MODE=postgres \
	INSPECTION_API_TOKEN=dev-token-123 \
	uvicorn agent_trading.api.app:create_app_from_env --factory --reload --host 0.0.0.0 --port 8000

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

# Start the snapshot sync scheduler container
docker-up-snapshot-sync:
	docker compose up -d snapshot-sync

# Tail the snapshot sync scheduler logs
docker-logs-snapshot-sync:
	docker compose logs -f snapshot-sync

# Restart the snapshot sync scheduler container
docker-restart-snapshot-sync:
	docker compose restart snapshot-sync
