#!/usr/bin/bash
# =============================================================================
# Deploy: Broker Truth Sync + Duplicate Sell Guard + LLM Subprocess Isolation
# =============================================================================
# Purpose: Rebuild and restart Docker containers for the combined changeset
#          from two previous tasks (~19 files).
#
# Changes included:
#   1. LLM Hang/Timeout Subprocess Isolation (10 files)
#      - scripts/run_agent_subprocess.py (new)
#      - decision_orchestrator.py subprocess isolation
#      - run_ops_scheduler.py timeout 240→120
#      - run_decision_loop.py timeout 90→120
#      - tests/conftest.py AGENT_SUBPROCESS_ISOLATION=0
#
#   2. KIS Broker Truth Sync + Duplicate Sell Guard (9 files, 2 new)
#      - rest_client.py ODNO matching/pagination
#      - order_sync_service.py reconcile_required 해소
#      - sell_guard.py (new)
#      - decision_orchestrator.py sell guard 통합
#      - routes/orders.py inspection API
#      - schemas.py response models
#      - deps.py
#
# Usage:
#   bash scripts/deploy_broker_truth_sync.sh
#
# Notes:
#   - Run from project root (/workspace/agent_trading)
#   - Requires docker-compose to be installed
#   - Does NOT modify .env
#   - Does NOT run DB migrations (none needed)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Step 1: Verify working tree ==="
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    echo "ERROR: Not inside a git repository."
    exit 1
fi
echo "Working tree: $(git rev-parse --show-toplevel)"
echo "Current branch: $(git symbolic-ref --short HEAD 2>/dev/null || echo '(detached)')"
echo "Last commit: $(git log -1 --oneline 2>/dev/null || echo 'N/A')"

# ── Optional: uncomment to pull latest ──
# echo ""
# echo "=== Step 1b: Git pull ==="
# git pull --ff-only origin HEAD 2>&1 || echo "WARNING: git pull failed (continuing anyway)"

echo ""
echo "=== Step 2: Docker compose build (no cache) ==="
# Build app and ops-scheduler images from the same Dockerfile.
# docker-compose build --no-cache uses the same tag for both services.
docker compose build --no-cache app ops-scheduler 2>&1 | tail -20

echo ""
echo "=== Step 3: Docker compose restart ==="
# --force-recreate ensures new containers even if image tag hasn't changed.
docker compose up -d --force-recreate app ops-scheduler

echo ""
echo "=== Step 4: Health check (30s wait, up to 60s) ==="
HEALTH_OK=false
for i in $(seq 1 12); do
    sleep 5
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo "Health check PASSED (HTTP 200) — attempt $i"
        HEALTH_OK=true
        break
    fi
    echo "Waiting... attempt $i (status=$STATUS)"
done

if [ "$HEALTH_OK" = false ]; then
    echo "WARNING: Health check did not return HTTP 200 within 60s."
    echo "         Check container logs for details."
fi

echo ""
echo "=== Step 5: Component status ==="
echo "--- app containers ---"
docker compose ps app ops-scheduler

echo ""
echo "--- recent app logs (last 20 lines) ---"
docker compose logs --tail=20 app 2>/dev/null || true

echo ""
echo "=== Step 6: Inspection API smoke test ==="
echo "--- GET /orders?limit=1 (first 500 chars) ---"
curl -s http://localhost:8000/orders?limit=1 | head -c 500
echo ""

echo ""
echo "=== Step 7: Ops-scheduler health check ==="
OPS_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' agent_trading-ops-scheduler 2>/dev/null || echo "unknown")
echo "ops-scheduler health status: $OPS_HEALTH"

echo ""
echo "=== Deployment complete ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "KST:       $(TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S%z)"
