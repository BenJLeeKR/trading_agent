#!/usr/bin/env bash
# 좁은 검증 스크립트 — detect_fdc_quota_postgres_relevance.sh(FDC quota
# PostgreSQL 전용 CI job의 relevance 판정 로직)만 대상으로 한다.
#
# 왜 pytest가 아니라 별도 bash 스크립트인가:
#   판정 대상 자체가 bash 스크립트고, 실제 git 저장소(커밋 이력)를
#   만들어 진짜 `git diff`로 검증해야 의미가 있다 —
#   `test_docker_compose_env_git_sha.sh`와 동일한 관례.
#
# 이 스크립트는 임시 git 저장소만 만들고 조작한다 — 이 저장소의 원본
# checkout, 운영 DB/컨테이너, 네트워크는 전혀 건드리지 않는다.
#
# 실행: bash scripts/harness/test_detect_fdc_quota_postgres_relevance.sh
# 종료 코드: 0=전부 통과, 1=하나 이상 실패.

set -Eeuo pipefail

SCRIPT_UNDER_TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_UNDER_TEST="$SCRIPT_UNDER_TEST_DIR/detect_fdc_quota_postgres_relevance.sh"

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

_get() {
  # $1=output 텍스트, $2=key → 마지막으로 등장한 key=value의 value를 뽑는다.
  printf '%s\n' "$1" | grep "^$2=" | tail -1 | cut -d'=' -f2-
}

# ── 공통 fixture: 임시 git 저장소 ────────────────────────────────────────
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

repo_dir="$work_dir/fixture_repo"
mkdir -p "$repo_dir"/src/agent_trading/repositories/postgres
mkdir -p "$repo_dir"/db/migrations
mkdir -p "$repo_dir"/docs

git -C "$repo_dir" init -q
git -C "$repo_dir" config user.email "test@example.com"
git -C "$repo_dir" config user.name "test"

echo "base" > "$repo_dir/README.md"
git -C "$repo_dir" add README.md
git -C "$repo_dir" commit -q -m "base commit"
base_sha="$(git -C "$repo_dir" rev-parse HEAD)"

# ============================================================================
# 시나리오 1: PR 전체 범위에 fdc_quota.py 수정이 있고, 마지막 커밋은
# 문서만 수정 → relevant=1이어야 한다(HEAD^ 기준 판정이었다면 여기서
# relevant=0으로 잘못 나왔을 결함 재현 케이스).
# ============================================================================
echo "quota code v1" > "$repo_dir/src/agent_trading/repositories/postgres/fdc_quota.py"
git -C "$repo_dir" add src/agent_trading/repositories/postgres/fdc_quota.py
git -C "$repo_dir" commit -q -m "feat: fdc_quota.py 수정"

echo "docs only" > "$repo_dir/docs/note.md"
git -C "$repo_dir" add docs/note.md
git -C "$repo_dir" commit -q -m "docs: 무관한 문서 커밋(마지막 커밋)"

out="$(bash "$SCRIPT_UNDER_TEST" "pull_request" "$base_sha" "HEAD" "$repo_dir")"
relevant="$(_get "$out" relevant)"
matched="$(_get "$out" matched_file_count)"
if [ "$relevant" = "1" ]; then
  _pass "시나리오1: PR 범위에 fdc_quota.py 변경 + 마지막 커밋은 문서만 → relevant=1"
else
  _fail "시나리오1: relevant=$relevant (기대값 1) matched_file_count=$matched / 전체 출력: $out"
fi
if [ "$matched" = "1" ]; then
  _pass "시나리오1: matched_file_count=1(fdc_quota.py 1건)"
else
  _fail "시나리오1: matched_file_count=$matched (기대값 1)"
fi

# HEAD^ 기준(결함 재현)이었다면 어떻게 나왔을지 대조 확인 — 마지막
# 커밋(문서만)과 그 직전 커밋만 비교하면 matched=0이어야 결함이 실재함을
# 증명한다.
head_caret_out="$(bash "$SCRIPT_UNDER_TEST" "pull_request" "HEAD^" "HEAD" "$repo_dir")"
head_caret_matched="$(_get "$head_caret_out" matched_file_count)"
if [ "$head_caret_matched" = "0" ]; then
  _pass "대조 확인: HEAD^ 기준이었다면 matched_file_count=0으로 결함이 실제로 재현됐을 것"
else
  _fail "대조 확인 실패: HEAD^ 기준에서도 matched_file_count=$head_caret_matched (0 기대)"
fi

# ============================================================================
# 시나리오 2: PR 전체 범위에 migration sql이 있고, 마지막 커밋은 무관한
# 파일 변경 → relevant=1.
# ============================================================================
echo "sql v1" > "$repo_dir/db/migrations/0099_add_fdc_quota_extra.sql"
git -C "$repo_dir" add db/migrations/0099_add_fdc_quota_extra.sql
git -C "$repo_dir" commit -q -m "feat: fdc_quota migration 추가"

echo "unrelated" > "$repo_dir/docs/unrelated.md"
git -C "$repo_dir" add docs/unrelated.md
git -C "$repo_dir" commit -q -m "docs: 무관한 변경(마지막 커밋)"

out2="$(bash "$SCRIPT_UNDER_TEST" "pull_request" "$base_sha" "HEAD" "$repo_dir")"
relevant2="$(_get "$out2" relevant)"
if [ "$relevant2" = "1" ]; then
  _pass "시나리오2: PR 범위에 migration sql 변경 + 마지막 커밋은 무관 → relevant=1"
else
  _fail "시나리오2: relevant=$relevant2 (기대값 1) / 전체 출력: $out2"
fi

# ============================================================================
# 시나리오 3: PR 전체 범위에 관련 파일이 전혀 없음 → relevant=0.
# ============================================================================
scenario3_base="$(git -C "$repo_dir" rev-parse HEAD)"
echo "unrelated 1" > "$repo_dir/docs/a.md"
git -C "$repo_dir" add docs/a.md
git -C "$repo_dir" commit -q -m "docs: a"
echo "unrelated 2" > "$repo_dir/docs/b.md"
git -C "$repo_dir" add docs/b.md
git -C "$repo_dir" commit -q -m "docs: b"

out3="$(bash "$SCRIPT_UNDER_TEST" "pull_request" "$scenario3_base" "HEAD" "$repo_dir")"
relevant3="$(_get "$out3" relevant)"
matched3="$(_get "$out3" matched_file_count)"
if [ "$relevant3" = "0" ] && [ "$matched3" = "0" ]; then
  _pass "시나리오3: 관련 파일 없는 PR 범위 → relevant=0, matched_file_count=0"
else
  _fail "시나리오3: relevant=$relevant3 matched_file_count=$matched3 (기대값 relevant=0, matched=0) / 전체 출력: $out3"
fi

# ============================================================================
# 시나리오 4: workflow_dispatch → 관련 파일 여부와 무관하게 relevant=1.
# ============================================================================
out4="$(bash "$SCRIPT_UNDER_TEST" "workflow_dispatch" "" "HEAD" "$repo_dir")"
relevant4="$(_get "$out4" relevant)"
if [ "$relevant4" = "1" ]; then
  _pass "시나리오4: workflow_dispatch → relevant=1"
else
  _fail "시나리오4: relevant=$relevant4 (기대값 1) / 전체 출력: $out4"
fi

# ============================================================================
# 시나리오 5(추가): base_ref를 구할 수 없음(빈 문자열) → fail-open
# (relevant=0)이 아니라 보수적 fallback(relevant=1)이어야 한다.
# ============================================================================
out5="$(bash "$SCRIPT_UNDER_TEST" "push" "" "HEAD" "$repo_dir")"
relevant5="$(_get "$out5" relevant)"
if [ "$relevant5" = "1" ]; then
  _pass "시나리오5: base_ref 빈 문자열(push 최초 커밋 등) → 보수적 fallback relevant=1"
else
  _fail "시나리오5: relevant=$relevant5 (기대값 1, fail-open 금지) / 전체 출력: $out5"
fi

# ============================================================================
# 시나리오 6(추가): base_ref가 로컬 저장소에 없는 SHA(예: shallow
# checkout으로 fetch되지 않은 경우 재현) → 보수적 fallback(relevant=1).
# ============================================================================
out6="$(bash "$SCRIPT_UNDER_TEST" "pull_request" "0000000000000000000000000000000000000000" "HEAD" "$repo_dir")"
relevant6="$(_get "$out6" relevant)"
if [ "$relevant6" = "1" ]; then
  _pass "시나리오6: base_ref가 로컬에 없는 SHA(all-zero 포함) → 보수적 fallback relevant=1"
else
  _fail "시나리오6: relevant=$relevant6 (기대값 1) / 전체 출력: $out6"
fi

# ============================================================================
# 시나리오 7(추가): 로그 출력에 비밀값/URL이 없고 필요한 필드가 전부
# 있는지 확인.
# ============================================================================
required_keys=(event_name base_ref head_ref compare_range changed_file_count matched_file_count relevant)
missing_key=""
for key in "${required_keys[@]}"; do
  if ! printf '%s\n' "$out" | grep -q "^${key}="; then
    missing_key="$key"
    break
  fi
done
if [ -z "$missing_key" ]; then
  _pass "시나리오7: 필수 로그 필드(event_name/base_ref/head_ref/compare_range/changed_file_count/matched_file_count/relevant) 전부 출력됨"
else
  _fail "시나리오7: 필수 로그 필드 누락: $missing_key"
fi
if printf '%s\n' "$out" | grep -qiE "https?://|token|password|secret"; then
  _fail "시나리오7: 출력에 URL/비밀값으로 의심되는 문자열이 포함됨"
else
  _pass "시나리오7: 출력에 URL/비밀값 문자열 없음"
fi

# ============================================================================
# 시나리오 8(추가, 2026-08-26): 5번째 인자로 pattern override를 주면
# 기본 FDC quota 패턴 대신 그 패턴으로 판정해야 한다 — 다른 좁은
# PostgreSQL CI job(postgres_fixture_loop_scope_integration)이 이
# 스크립트를 재사용할 수 있는 근거.
# ============================================================================
scenario8_base="$(git -C "$repo_dir" rev-parse HEAD)"
echo "conftest change" > "$repo_dir/docs/conftest_marker.md"
git -C "$repo_dir" add docs/conftest_marker.md
git -C "$repo_dir" commit -q -m "docs: fdc quota와 무관한 변경(기본 패턴은 매칭하면 안 됨)"

custom_pattern='^docs/conftest_marker\.md$'
out8_default="$(bash "$SCRIPT_UNDER_TEST" "pull_request" "$scenario8_base" "HEAD" "$repo_dir")"
out8_custom="$(bash "$SCRIPT_UNDER_TEST" "pull_request" "$scenario8_base" "HEAD" "$repo_dir" "$custom_pattern")"
relevant8_default="$(_get "$out8_default" relevant)"
relevant8_custom="$(_get "$out8_custom" relevant)"
if [ "$relevant8_default" = "0" ] && [ "$relevant8_custom" = "1" ]; then
  _pass "시나리오8: 5번째 인자(pattern override)로 다른 판정 기준을 재사용 가능(기본 패턴=0, override 패턴=1)"
else
  _fail "시나리오8: relevant8_default=$relevant8_default relevant8_custom=$relevant8_custom (기대값 0/1)"
fi

echo ""
echo "==== 결과: pass=$pass_count fail=$fail_count ===="
[[ "$fail_count" -eq 0 ]]
