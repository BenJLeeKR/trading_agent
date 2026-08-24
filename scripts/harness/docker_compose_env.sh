#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/load_external_env.sh"

# ── AGENT_TRADING_GIT_SHA 자동 주입 (Stage A-2 policy fingerprint) ──────────
# 이 값은 정책 설정값이 아니라, trade_decisions/guardrail_evaluations에
# 남는 "이 결정이 어떤 코드 버전에서 나왔는지" 확인용 관측성 전용
# 식별자다(agent_trading.config.settings.resolve_policy_git_sha()가
# 읽는 그 값) — 어떤 gate/threshold/submit 판정에도 쓰이지 않는다.
#
# 우선순위: 이 시점에 이미 값이 설정돼 있으면(위 load_external_env_files가
# /etc/agent_trading/*.env에서 로드했거나, 호출자가 직접 export했거나)
# 절대 덮어쓰지 않는다. 값이 없거나 빈 문자열일 때만 자동 산출한다.
#
# SHA 산출 위치: 이 스크립트 자신이 위치한 checkout(`git -C "$SCRIPT_DIR"`)
# 의 HEAD를 쓴다. 호출자의 현재 작업 디렉터리와 무관하게, 항상 "이
# docker_compose_env.sh가 속한 저장소"가 채택되므로 배포 파이프라인
# (`.github/workflows/harness.yml`의 sync_source가 `/workspace/
# agent_trading`을 deploy_target_sha로 hard reset한 뒤, 바로 그 경로에서
# 이 스크립트를 호출하는 activate_runtime)과 정확히 같은 커밋을 가리킨다.
# detached HEAD에서도 `git rev-parse HEAD`는 커밋 SHA를 정상 반환한다.
#
# 실패 정책: SHA 산출이 실패해도(git 저장소가 아닌 등) 배포를 막지
# 않는다 — 이 필드는 nullable 관측성 전용이라 결측이 허용된다. 다만
# 조용히 빈 값으로 넘어가지 않고 명확한 경고를 남긴다. 로그에는 전체
# SHA를 반복 출력하지 않고 "자동 주입됨/명시값 사용/미주입" 상태와
# 앞 12자리만 남긴다(비밀값이 아니므로 노출 자체는 문제 없으나 로그
# 소음을 줄이기 위함).
if [[ -z "${AGENT_TRADING_GIT_SHA:-}" ]]; then
  if _resolved_git_sha="$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)"; then
    export AGENT_TRADING_GIT_SHA="$_resolved_git_sha"
    echo "AGENT_TRADING_GIT_SHA: 자동 주입됨 (${_resolved_git_sha:0:12}...)" >&2
  else
    echo "WARNING: AGENT_TRADING_GIT_SHA 자동 산출 실패(git 저장소 아님 등)" \
      "— 관측성 필드 없이(NULL) 계속 진행합니다." >&2
  fi
  unset _resolved_git_sha
else
  echo "AGENT_TRADING_GIT_SHA: 명시값 사용 (길이=${#AGENT_TRADING_GIT_SHA})" >&2
fi

compose_args=()
if [[ -n "${AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS:-}" ]]; then
  IFS=':' read -r -a env_paths <<<"$AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS"
  for env_path in "${env_paths[@]}"; do
    [[ -n "$env_path" ]] || continue
    compose_args+=(--env-file "$env_path")
  done
fi

exec docker compose "${compose_args[@]}" "$@"
