#!/bin/bash
set -euo pipefail
cd /workspace/agent_trading
DATES=(2026-07-06 2026-07-07 2026-07-08 2026-07-09)
for d in "${DATES[@]}"; do
  echo "=== generate $d ==="
  docker compose exec -T ops-scheduler python3 -m scripts.generate_signal_feature_snapshot_input     --end-date "$d"     --output "data/signal_feature_snapshot_input_${d}_v5_rerun.json"     --output-format json
  echo "=== build $d ==="
  docker compose exec -T ops-scheduler python3 -m scripts.build_signal_feature_snapshots     --input "data/signal_feature_snapshot_input_${d}_v5_rerun.json"     --output json     --trigger-type after_market_scheduler
  echo "=== attribution $d ==="
  docker compose exec -T ops-scheduler python3 /app/scripts/analyze_trigger_proxy_attribution.py     --start-date 2026-06-27     --end-date "$d"     --output json     --write-json "/app/logs/trigger_proxy_attribution_${d}_rerun_v5.json"
done
