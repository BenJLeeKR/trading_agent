#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/load_external_env.sh"

compose_args=()
if [[ -n "${AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS:-}" ]]; then
  IFS=':' read -r -a env_paths <<<"$AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS"
  for env_path in "${env_paths[@]}"; do
    [[ -n "$env_path" ]] || continue
    compose_args+=(--env-file "$env_path")
  done
fi

exec docker compose "${compose_args[@]}" "$@"
