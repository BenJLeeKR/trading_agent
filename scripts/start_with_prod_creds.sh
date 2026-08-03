#!/usr/bin/env bash
# scripts/start_with_prod_creds.sh
# KIS/NAVER live credential 정식 런타임 주입 — docker compose up wrapper
#
# 사용법:
#   ./scripts/start_with_prod_creds.sh          # 모든 서비스 기동
#   ./scripts/start_with_prod_creds.sh -d       # detach 모드
#   ./scripts/start_with_prod_creds.sh -d ops-scheduler  # 특정 서비스만
#
# Live disclosure는 KIS_LIVE_INFO_APP_KEY/SECRET을 직접 사용
# (settings.py _resolve_kis_live_app_key()에서 KIS_LIVE_INFO_APP_KEY 읽음)
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/harness/load_external_env.sh"

# ---- Validation ----
MISSING=""
if [ -z "${KIS_LIVE_INFO_APP_KEY:-}" ] || [ -z "${KIS_LIVE_INFO_APP_SECRET:-}" ]; then
  MISSING="$MISSING KIS_LIVE_INFO_APP_KEY/SECRET"
fi
if [ -z "${NAVER_CLIENT_ID:-}" ] || [ -z "${NAVER_CLIENT_SECRET:-}" ]; then
  MISSING="$MISSING NAVER_CLIENT_ID/SECRET"
fi
if [ -n "$MISSING" ]; then
  echo "[WARN] Missing credentials:$MISSING — related features disabled" >&2
fi

echo "[start_with_prod_creds] KIS_LIVE_INFO_APP_KEY=$( [[ -n ${KIS_LIVE_INFO_APP_KEY:-} ]] && echo configured || echo missing )"
echo "[start_with_prod_creds] KIS_LIVE_INFO_APP_SECRET=$( [[ -n ${KIS_LIVE_INFO_APP_SECRET:-} ]] && echo configured || echo missing )"
echo "[start_with_prod_creds] NAVER_CLIENT_ID=$( [[ -n ${NAVER_CLIENT_ID:-} ]] && echo configured || echo missing )"
echo "[start_with_prod_creds] NAVER_CLIENT_SECRET=$( [[ -n ${NAVER_CLIENT_SECRET:-} ]] && echo configured || echo missing )"

exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/harness/docker_compose_env.sh" up "$@"
