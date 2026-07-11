#!/bin/bash
set -euo pipefail
cd /workspace/agent_trading
for d in 2026-07-06 2026-07-07 2026-07-08 2026-07-09 2026-07-10; do
  echo "=== generate ${d} ==="
  docker compose exec -T ops-scheduler python3 -m scripts.generate_signal_feature_snapshot_input     --end-date "$d"     --output "data/signal_feature_snapshot_input_${d}_v5_regen.json"     --output-format json
  echo "=== build ${d} ==="
  docker compose exec -T ops-scheduler python3 -m scripts.build_signal_feature_snapshots     --input "data/signal_feature_snapshot_input_${d}_v5_regen.json"     --output json     --trigger-type after_market_scheduler
  echo "=== done ${d} ==="
done
