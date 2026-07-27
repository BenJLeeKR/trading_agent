.PHONY: install run migrate test lint smoke \
        harness-status env-check check-file test-one test-file lint-path docs-check accept-docs accept-env accept-backend-file accept-backend-runtime accept-admin-ui accept-ops-report admin-test-one \
        full-test docker-test-safe smoke-safe admin-build admin-test-all \
        docker-up docker-down docker-build docker-migrate docker-test docker-shell \
        docker-up-api docker-logs-api docker-restart-api \
        run-api-inmemory run-api-postgres

# =============================================================================
# Local Development (requires local Python venv + local PostgreSQL)
# =============================================================================

install:
	pip install -e ".[dev]"

run:
	python3 -m agent_trading.main

migrate:
	python3 -m agent_trading.db.migrations.run

test:
	bash scripts/harness/run.sh full-test

smoke:
	bash scripts/harness/run.sh smoke

smoke-all:
	@echo "smoke-all은 부하 제한 대상입니다. 필요한 경우 사용자 승인 후 직접 실행하세요."
	@exit 1

lint:
	@echo "Running ruff ..."
	bash scripts/harness/run.sh lint-path src/agent_trading

# =============================================================================
# Harness-Safe Commands (preferred for AI agents)
# =============================================================================

harness-status:
	bash scripts/harness/run.sh status

env-check:
	bash scripts/harness/run.sh env-check

check-file:
	@test -n "$(FILE)" || (echo "사용법: make check-file FILE=src/agent_trading/foo.py" >&2; exit 1)
	bash scripts/harness/run.sh py-compile "$(FILE)"

test-one:
	@test -n "$(TEST)" || (echo "사용법: make test-one TEST=tests/path/test_file.py::test_name" >&2; exit 1)
	bash scripts/harness/run.sh test-one "$(TEST)"

test-file:
	@test -n "$(TEST)" || (echo "사용법: make test-file TEST=tests/path/test_file.py" >&2; exit 1)
	bash scripts/harness/run.sh test-file "$(TEST)"

lint-path:
	@test -n "$(TARGET)" || (echo "사용법: make lint-path TARGET=src/agent_trading/foo.py" >&2; exit 1)
	bash scripts/harness/run.sh lint-path "$(TARGET)"

docs-check:
	bash scripts/harness/run.sh docs-check

accept-docs:
	bash scripts/harness/run.sh accept docs

accept-env:
	bash scripts/harness/run.sh accept env

accept-backend-file:
	@test -n "$(FILE)" || (echo "사용법: make accept-backend-file FILE=src/agent_trading/foo.py" >&2; exit 1)
	bash scripts/harness/run.sh accept backend-file "$(FILE)"

accept-backend-runtime:
	bash scripts/harness/run.sh accept backend-runtime

accept-admin-ui:
	bash scripts/harness/run.sh accept frontend

accept-ops-report:
	@test -n "$(SUMMARY_JSON)" || (echo "사용법: make accept-ops-report SUMMARY_JSON='<summary_json 또는 json 파일 경로>'" >&2; exit 1)
	bash scripts/harness/run.sh accept ops-report "$(SUMMARY_JSON)"

admin-test-one:
	@test -n "$(TEST)" || (echo "사용법: make admin-test-one TEST=src/path/file.test.tsx" >&2; exit 1)
	bash scripts/harness/run.sh admin-test-one "$(TEST)"

full-test:
	bash scripts/harness/run.sh full-test

docker-test-safe:
	bash scripts/harness/run.sh docker-test

smoke-safe:
	bash scripts/harness/run.sh smoke

admin-build:
	bash scripts/harness/run.sh admin-build

admin-test-all:
	bash scripts/harness/run.sh admin-test-all

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

# 표준 migration 실행 경로(`docker compose run --rm migrate`, docker-compose.yml의
# one-shot `migrate` service)의 convenience alias다 — 별도 실행 경로가 아니다.
docker-migrate:
	docker compose run --rm migrate

docker-test:
	bash scripts/harness/run.sh docker-test

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
