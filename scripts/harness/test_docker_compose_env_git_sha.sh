#!/usr/bin/env bash
# 좁은 검증 스크립트 — docker_compose_env.sh의 AGENT_TRADING_GIT_SHA
# 자동 주입 로직(2026-08-24 KST 추가)만 대상으로 한다.
#
# 왜 pytest가 아니라 별도 bash 스크립트인가:
#   dev validation container(`docker_dev_exec.sh`)에는 git이 설치돼
#   있지 않다(`network_mode=none` 격리 이미지) — `git -C ... rev-parse
#   HEAD`를 실제로 실행해 검증하려면 git이 있는 환경(호스트 셸)에서
#   직접 실행해야 한다. 이 스크립트는 실제 docker/네트워크를 전혀
#   건드리지 않는다 — `docker`를 임시 stub으로 완전히 대체해 "무엇을
#   실행하려 했는지"만 기록하고 검증한다.
#
# 왜 /etc/agent_trading을 건드리지 않는가:
#   운영 호스트에는 실제 비밀값이 담긴 /etc/agent_trading/*.env가 있을
#   수 있다. 이 테스트는 AGENT_TRADING_ENV_DIR을 존재하지 않는 임시
#   경로로 강제해(시나리오 5는 예외적으로 격리된 임시 디렉터리를 씀)
#   실제 운영 env 파일을 절대 읽지 않는다.
#
# 실행: bash scripts/harness/test_docker_compose_env_git_sha.sh
# 종료 코드: 0=전부 통과, 1=하나 이상 실패.

set -Eeuo pipefail

SCRIPT_UNDER_TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_UNDER_TEST="$SCRIPT_UNDER_TEST_DIR/docker_compose_env.sh"

fail_count=0
pass_count=0

_pass() {
  pass_count=$((pass_count + 1))
  echo "PASS: $1"
}

_fail() {
  fail_count=$((fail_count + 1))
  echo "FAIL: $1" >&2
}

# ── 공통 fixture: docker를 stub으로 대체한 임시 PATH ────────────────────────
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

stub_bin_dir="$work_dir/bin"
mkdir -p "$stub_bin_dir"
docker_call_log="$work_dir/docker_call.log"
no_env_dir="$work_dir/nonexistent_env_dir"

cat >"$stub_bin_dir/docker" <<STUB
#!/usr/bin/env bash
# 실제 docker를 절대 호출하지 않는다 — 인자와 관측 대상 env만 기록한다.
{
  echo "ARGS: \$*"
  echo "AGENT_TRADING_GIT_SHA=\${AGENT_TRADING_GIT_SHA:-<unset>}"
} >> "$docker_call_log"
exit 0
STUB
chmod +x "$stub_bin_dir/docker"

run_with_stub_docker() {
  # $1 = 추가 env 대입 문자열(space-separated KEY=VALUE, 필요시), 나머지는
  # docker_compose_env.sh에 넘길 인자. AGENT_TRADING_ENV_DIR은 실제
  # /etc/agent_trading을 건드리지 않도록 항상 존재하지 않는 경로로 고정한다
  # (extra_env 쪽에서 다시 지정하면 그 값으로 override됨).
  local extra_env="$1"
  shift
  : >"$docker_call_log"
  env -i \
    PATH="$stub_bin_dir:/usr/bin:/bin" \
    HOME="$HOME" \
    AGENT_TRADING_ENV_DIR="$no_env_dir" \
    $extra_env \
    bash "$SCRIPT_UNDER_TEST" "$@" \
    2>"$work_dir/stderr.log"
}

# ============================================================================
# 시나리오 1: 명시적 AGENT_TRADING_GIT_SHA가 있으면 그대로 유지한다.
# ============================================================================
run_with_stub_docker "AGENT_TRADING_GIT_SHA=explicit-value-000" ps
if grep -q "^AGENT_TRADING_GIT_SHA=explicit-value-000$" "$docker_call_log"; then
  _pass "명시적 AGENT_TRADING_GIT_SHA 유지(덮어쓰지 않음)"
else
  _fail "명시적 AGENT_TRADING_GIT_SHA가 유지되지 않음: $(cat "$docker_call_log")"
fi
if grep -q "명시값 사용" "$work_dir/stderr.log"; then
  _pass "명시값 사용 로그 출력 확인"
else
  _fail "명시값 사용 로그가 출력되지 않음: $(cat "$work_dir/stderr.log")"
fi

# ============================================================================
# 시나리오 2: 값이 비어 있으면 이 스크립트가 속한 checkout의 HEAD를
# 자동 산출해 주입한다 — 실제 `git -C <repo> rev-parse HEAD`와 일치해야 함.
# ============================================================================
expected_sha="$(git -C "$SCRIPT_UNDER_TEST_DIR" rev-parse HEAD)"
run_with_stub_docker "" ps
if grep -q "^AGENT_TRADING_GIT_SHA=${expected_sha}$" "$docker_call_log"; then
  _pass "AGENT_TRADING_GIT_SHA 미설정 시 checkout HEAD(${expected_sha:0:12}...) 자동 주입"
else
  _fail "자동 주입 SHA가 기대값과 다름(expected=${expected_sha}): $(cat "$docker_call_log")"
fi
if grep -q "자동 주입됨" "$work_dir/stderr.log"; then
  _pass "자동 주입 로그 출력 확인"
else
  _fail "자동 주입 로그가 출력되지 않음: $(cat "$work_dir/stderr.log")"
fi

# ============================================================================
# 시나리오 3: 빈 문자열도 "명시값 없음"으로 취급해 자동 산출해야 한다.
# ============================================================================
run_with_stub_docker "AGENT_TRADING_GIT_SHA=" ps
if grep -q "^AGENT_TRADING_GIT_SHA=${expected_sha}$" "$docker_call_log"; then
  _pass "빈 문자열은 명시값으로 취급하지 않고 자동 산출함"
else
  _fail "빈 문자열 케이스에서 자동 산출이 동작하지 않음: $(cat "$docker_call_log")"
fi

# ============================================================================
# 시나리오 4: git 저장소 밖에서는 실패를 명확히 경고하고, 배포(=docker
# 호출)는 계속 진행하며(관측성 결측 허용), AGENT_TRADING_GIT_SHA는
# unset으로 남는다.
# ============================================================================
outside_repo_dir="$work_dir/outside_git_repo"
mkdir -p "$outside_repo_dir"
cp "$SCRIPT_UNDER_TEST_DIR/docker_compose_env.sh" "$outside_repo_dir/"
cp "$SCRIPT_UNDER_TEST_DIR/load_external_env.sh" "$outside_repo_dir/"
: >"$docker_call_log"
env -i \
  PATH="$stub_bin_dir:/usr/bin:/bin" \
  HOME="$HOME" \
  AGENT_TRADING_ENV_DIR="$no_env_dir" \
  bash "$outside_repo_dir/docker_compose_env.sh" ps \
  2>"$work_dir/stderr_outside.log"
if grep -q "^AGENT_TRADING_GIT_SHA=<unset>$" "$docker_call_log"; then
  _pass "git 저장소 밖: AGENT_TRADING_GIT_SHA가 unset으로 남음(NULL 허용)"
else
  _fail "git 저장소 밖 케이스에서 예상과 다른 값: $(cat "$docker_call_log")"
fi
if grep -q "WARNING: AGENT_TRADING_GIT_SHA 자동 산출 실패" "$work_dir/stderr_outside.log"; then
  _pass "git 저장소 밖: 명확한 WARNING 출력 확인"
else
  _fail "git 저장소 밖 케이스에서 WARNING이 출력되지 않음: $(cat "$work_dir/stderr_outside.log")"
fi
if [[ -s "$docker_call_log" ]]; then
  _pass "git 저장소 밖에서도 docker(compose) 호출 자체는 계속 진행됨(배포를 막지 않음)"
else
  _fail "git 저장소 밖 케이스에서 docker 호출이 발생하지 않음(배포가 막힘 — 허용되지 않는 동작)"
fi

# ============================================================================
# 시나리오 5: 기존 "AGENT_TRADING_ENV_DIR → --env-file 배선" 계약과
# 추가 인자(compose subcommand) 전달 계약이 그대로 유지되는지.
# load_external_env_files()가 실제로 파일을 스캔해 만드는 값이므로,
# 이 변수를 직접 주입하지 않고 실제 디렉터리 스캔 경로를 그대로 태운다.
# (주의: AGENT_TRADING_REQUIRED_ENV_FILES="" 는 bash의 ${VAR:-default}
# 규칙상 "미설정"과 구분되지 않아 기본값(runtime.env:ai.env:kis.env)이
# 그대로 적용된다 — 그래서 이 3개 필수 파일도 함께 준비한다.)
# ============================================================================
fake_env_dir="$work_dir/fake_etc_agent_trading"
mkdir -p "$fake_env_dir"
: >"$fake_env_dir/runtime.env"
: >"$fake_env_dir/ai.env"
: >"$fake_env_dir/kis.env"
echo "FOO=bar" >"$fake_env_dir/local.override.env"
: >"$docker_call_log"
env -i \
  PATH="$stub_bin_dir:/usr/bin:/bin" \
  HOME="$HOME" \
  AGENT_TRADING_ENV_DIR="$fake_env_dir" \
  AGENT_TRADING_GIT_SHA="keep-me" \
  bash "$SCRIPT_UNDER_TEST" up -d --build --remove-orphans \
  2>"$work_dir/stderr5.log"
if grep -q -- "--env-file $fake_env_dir/local.override.env" "$docker_call_log" \
  && grep -q -- "--env-file $fake_env_dir/runtime.env" "$docker_call_log" \
  && grep -q "up -d --build --remove-orphans" "$docker_call_log" \
  && grep -q "^AGENT_TRADING_GIT_SHA=keep-me$" "$docker_call_log"; then
  _pass "--env-file 배선, 추가 compose 인자 전달, 명시적 GIT_SHA 유지가 모두 함께 성립"
else
  _fail "--env-file 배선 또는 인자 전달이 깨짐: $(cat "$docker_call_log") / stderr: $(cat "$work_dir/stderr5.log")"
fi

echo ""
echo "==== 결과: pass=$pass_count fail=$fail_count ===="
[[ "$fail_count" -eq 0 ]]
