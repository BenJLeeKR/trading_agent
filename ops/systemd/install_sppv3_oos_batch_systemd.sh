#!/usr/bin/env bash
# SPPV-3 OOS 일봉 cache 배치 — systemd service/timer 설치 스크립트.
#
# **이 스크립트는 이번 구현 턴에서 실행되지 않았다.** 실제
# `/etc/systemd/system/` 설치, `systemctl daemon-reload`,
# `systemctl enable`, `systemctl start`는 사용자가 명시적으로 승인한
# 뒤 이 스크립트를 직접 실행할 때만 일어난다. 이 파일 자체를 추가하는
# 것은 "배치 정의"일 뿐 "실제 자동 실행 활성화"가 아니다
# (docs/40_action_plans/sppv3_oos_daily_batch_design_2026-08-25.md §6).
#
# 사용법(승인 후, 운영 서버에서 root 권한으로):
#   AGENT_TRADING_REPO_ROOT=/workspace/agent_trading \
#     bash ops/systemd/install_sppv3_oos_batch_systemd.sh --yes
#
# `--yes` 없이 실행하면 무엇을 할지만 출력하고 아무것도 바꾸지 않는다
# (dry-run이 기본값이다).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_UNIT_DIR="/etc/systemd/system"
REPO_ROOT="${AGENT_TRADING_REPO_ROOT:-/workspace/agent_trading}"
DOCKER_COMPOSE_BIN="${DOCKER_COMPOSE_BIN:-/usr/bin/docker}"

APPLY=0
for arg in "$@"; do
  if [[ "$arg" == "--yes" ]]; then
    APPLY=1
  fi
done

echo "[install_sppv3_oos_batch_systemd] REPO_ROOT=${REPO_ROOT}"
echo "[install_sppv3_oos_batch_systemd] DOCKER_COMPOSE_BIN=${DOCKER_COMPOSE_BIN}"
echo "[install_sppv3_oos_batch_systemd] APPLY=${APPLY} (--yes 없으면 dry-run)"

if [[ ! -d "$REPO_ROOT" ]]; then
  echo "[오류] REPO_ROOT가 디렉터리가 아닙니다: ${REPO_ROOT}" >&2
  exit 1
fi
if [[ ! -f "${REPO_ROOT}/docker-compose.yml" ]]; then
  echo "[오류] ${REPO_ROOT}/docker-compose.yml을 찾을 수 없습니다 — 운영 checkout 경로를 확인하세요." >&2
  exit 1
fi

render_unit() {
  local template_path="$1"
  sed \
    -e "s#__AGENT_TRADING_REPO_ROOT__#${REPO_ROOT}#g" \
    -e "s#__DOCKER_COMPOSE_BIN__#${DOCKER_COMPOSE_BIN}#g" \
    "$template_path"
}

echo "[install_sppv3_oos_batch_systemd] 렌더링될 service 파일 미리보기:"
render_unit "${SCRIPT_DIR}/sppv3-oos-batch.service"
echo "---"
echo "[install_sppv3_oos_batch_systemd] timer 파일은 자리표시자 치환이 없습니다(그대로 설치):"
cat "${SCRIPT_DIR}/sppv3-oos-batch.timer"

if [[ "$APPLY" -ne 1 ]]; then
  echo
  echo "[install_sppv3_oos_batch_systemd] dry-run 종료 — 아무 파일도 쓰지 않았고," \
       "daemon-reload/enable/start도 실행하지 않았습니다. 실제 적용하려면 --yes를 붙여 재실행하세요."
  exit 0
fi

render_unit "${SCRIPT_DIR}/sppv3-oos-batch.service" > "${SYSTEMD_UNIT_DIR}/sppv3-oos-batch.service"
cp "${SCRIPT_DIR}/sppv3-oos-batch.timer" "${SYSTEMD_UNIT_DIR}/sppv3-oos-batch.timer"

systemctl daemon-reload
systemctl enable sppv3-oos-batch.timer
systemctl start sppv3-oos-batch.timer

echo "[install_sppv3_oos_batch_systemd] 설치 완료 — 'systemctl status sppv3-oos-batch.timer'로 확인하세요."
