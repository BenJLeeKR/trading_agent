.PHONY: install run migrate test lint smoke \
        docker-up docker-down docker-build docker-migrate docker-test docker-shell

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
