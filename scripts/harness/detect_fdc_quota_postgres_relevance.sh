#!/usr/bin/env bash
# FDC quota PostgreSQL 전용 CI job(`fdc_quota_postgres_integration`)의
# 실행 여부를 판정하는 순수 로직. GitHub Actions 컨텍스트(`github.*`
# 표현식)에 의존하지 않아 단위 테스트가 가능하다 — workflow 쪽은 이벤트별
# base ref만 계산해 이 스크립트에 넘긴다.
#
# 왜 별도 스크립트로 분리했는가:
#   워크플로 YAML 안의 인라인 bash는 fixture git 저장소로 직접 실행해
#   검증하기 어렵다. 이 스크립트는 인자로 받은 event_name/base_ref/
#   head_ref/repo_dir만으로 동작하므로, 실제 GitHub Actions 없이도
#   `scripts/harness/test_detect_fdc_quota_postgres_relevance.sh`가 임시
#   git 저장소를 만들어 그대로 재현·검증할 수 있다.
#
# Usage:
#   detect_fdc_quota_postgres_relevance.sh <event_name> <base_ref> [head_ref=HEAD] [repo_dir=.] [pattern_override]
#
# [pattern_override](5번째 인자, 선택)를 주면 기본 FDC quota 패턴 대신
# 그 정규식으로 관련 파일을 판정한다 — 판정 로직(이벤트별 base ref 처리,
# 보수적 fallback 등)은 완전히 재사용하면서 다른 좁은 PostgreSQL CI job
# (예: `postgres_fixture_loop_scope_integration`)의 relevance 판정에도
# 그대로 쓸 수 있게 하기 위함이다. 생략하면 기존 FDC quota 판정과 100%
# 동일하게 동작한다(하위 호환).
#
# <base_ref>가 빈 문자열이거나 로컬에서 찾을 수 없으면(예: fetch-depth
# 부족, 최초 push의 all-zero SHA) **fail-open(relevant=0)하지 않고**
# 보수적으로 relevant=1을 출력한다 — PostgreSQL 검증을 놓치는 것보다
# 불필요하게 한 번 더 실행하는 쪽이 훨씬 저렴하고 안전하다.
#
# stdout에 아래 key=value 줄을 한 번씩만 출력한다(비밀값·원격 URL 없음
# — git ref/파일 경로만 다룬다):
#   event_name=...
#   base_ref=...
#   head_ref=...
#   compare_range=...
#   changed_file_count=...
#   matched_file_count=...
#   relevant=0|1
set -euo pipefail

event_name="${1:?event_name 인자가 필요합니다}"
base_ref="${2-}"
head_ref="${3:-HEAD}"
repo_dir="${4:-.}"

# 이 PR/PostgreSQL 전용 job과 직접 관련된 파일만 대상으로 한다 — 기존
# 판정 로직(1차 구현)과 동일한 패턴을 그대로 유지한다. 5번째 인자로
# override가 오면 그 패턴을 대신 쓴다(다른 좁은 PostgreSQL CI job 재사용).
default_pattern='^(db/migrations/.*fdc_quota.*\.sql|src/agent_trading/repositories/postgres/fdc_quota\.py|src/agent_trading/repositories/(memory|contracts)\.py|src/agent_trading/services/fdc_quota_coordinator\.py|tests/services/test_fdc_quota_coordinator\.py|\.github/workflows/harness\.yml)$'
pattern="${5:-$default_pattern}"

_emit_fallback() {
  local reason="$1"
  echo "event_name=$event_name"
  echo "base_ref=$base_ref"
  echo "head_ref=$head_ref"
  echo "compare_range=($reason)"
  echo "changed_file_count=0"
  echo "matched_file_count=0"
  echo "relevant=1"
}

if [ "$event_name" = "workflow_dispatch" ]; then
  _emit_fallback "workflow_dispatch: 수동 트리거는 항상 실행"
  exit 0
fi

if [ -z "$base_ref" ]; then
  _emit_fallback "base_ref를 확인할 수 없음 — 보수적 fallback(relevant=1)"
  exit 0
fi

if ! git -C "$repo_dir" cat-file -e "${base_ref}^{commit}" 2>/dev/null; then
  _emit_fallback "base_ref($base_ref)가 로컬 저장소에 없음(fetch-depth 부족 또는 all-zero SHA 가능) — 보수적 fallback(relevant=1)"
  exit 0
fi

compare_range="${base_ref}..${head_ref}"
changed_files="$(git -C "$repo_dir" diff --name-only "$compare_range" || true)"
changed_file_count="$(printf '%s\n' "$changed_files" | sed '/^$/d' | wc -l | tr -d ' ')"
matched_file_count="$(printf '%s\n' "$changed_files" | sed '/^$/d' | grep -cE "$pattern" || true)"

relevant="0"
[ "$matched_file_count" != "0" ] && relevant="1"

echo "event_name=$event_name"
echo "base_ref=$base_ref"
echo "head_ref=$head_ref"
echo "compare_range=$compare_range"
echo "changed_file_count=$changed_file_count"
echo "matched_file_count=$matched_file_count"
echo "relevant=$relevant"
