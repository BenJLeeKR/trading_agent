#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="/workspace/agent_trading"
SAFE_TIMEOUT_SECONDS="${HARNESS_SAFE_TIMEOUT_SECONDS:-90}"
HEAVY_TIMEOUT_SECONDS="${HARNESS_HEAVY_TIMEOUT_SECONDS:-900}"

usage() {
  cat <<'EOF'
사용법:
  bash scripts/harness/run.sh status
  bash scripts/harness/run.sh env-check
  bash scripts/harness/run.sh py-compile <python_file>
  bash scripts/harness/run.sh test-one <tests/path.py::test_name>
  bash scripts/harness/run.sh test-file <tests/path.py>
  bash scripts/harness/run.sh lint-path <path>
  bash scripts/harness/run.sh docs-check
  bash scripts/harness/run.sh admin-test-one <test_file_or_selector>

승인 필요 명령:
  HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh full-test
  HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh docker-test
  HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh smoke
  HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh admin-build
  HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh admin-test-all
EOF
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

run_with_timeout() {
  local seconds="$1"
  shift
  timeout "$seconds" "$@"
}

run_python_with_timeout() {
  local seconds="$1"
  shift
  if docker ps --format '{{.Names}}' | grep -qx 'agent_trading-app-1'; then
    timeout "$seconds" docker exec -w /app agent_trading-app-1 python3 "$@"
  else
    echo "WARN: agent_trading-app-1 컨테이너가 없어 host python3를 사용합니다." >&2
    timeout "$seconds" python3 "$@"
  fi
}

require_arg() {
  local value="${1:-}"
  local name="$2"
  [[ -n "$value" ]] || fail "${name} 인자가 필요합니다."
}

resolve_in_repo() {
  local raw="$1"
  [[ "$raw" != -* ]] || fail "옵션처럼 보이는 경로는 허용하지 않습니다: $raw"
  local resolved
  resolved="$(realpath -m "$ROOT_DIR/$raw")"
  [[ "$resolved" == "$ROOT_DIR"/* ]] || fail "프로젝트 밖 경로는 허용하지 않습니다: $raw"
  printf '%s\n' "$resolved"
}

require_existing_file() {
  local raw="$1"
  local resolved
  resolved="$(resolve_in_repo "$raw")"
  [[ -f "$resolved" ]] || fail "파일이 존재하지 않습니다: $raw"
  printf '%s\n' "$resolved"
}

require_safe_test_selector() {
  local selector="$1"
  local file_part="${selector%%::*}"
  [[ "$file_part" == tests/* ]] || fail "테스트는 tests/ 아래 파일만 허용합니다: $selector"
  case "$file_part" in
    tests/smoke/*|tests/integration/*|tests/brokers/*)
      fail "부하 또는 외부 연동 가능성이 있는 테스트 경로는 승인 없이 실행하지 않습니다: $file_part"
      ;;
  esac
  require_existing_file "$file_part" >/dev/null
}

require_heavy_allowed() {
  [[ "${HARNESS_ALLOW_HEAVY:-}" == "1" ]] || fail "무거운 검증은 차단되었습니다. 사용자가 명시 승인한 경우에만 HARNESS_ALLOW_HEAVY=1을 설정해 실행하세요."
}

read_expected_version() {
  local version_file="$1"
  [[ -f "$version_file" ]] || fail "버전 파일이 없습니다: ${version_file#$ROOT_DIR/}"
  head -n 1 "$version_file" | tr -d '[:space:]'
}

check_exact_version() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  [[ -n "$actual" ]] || fail "${name} 버전을 확인할 수 없습니다."
  if [[ "$actual" != "$expected" ]]; then
    fail "${name} 버전 불일치: expected=$expected actual=$actual"
  fi
  echo "${name}=$actual"
}

env_check() {
  local expected_python expected_node expected_postgres
  expected_python="$(read_expected_version "$ROOT_DIR/.python-version")"
  expected_node="$(read_expected_version "$ROOT_DIR/admin_ui/.nvmrc")"
  local expected_npm
  expected_npm="$(read_expected_version "$ROOT_DIR/admin_ui/.npm-version")"
  expected_postgres="$(read_expected_version "$ROOT_DIR/.postgres-version")"

  local actual_python
  if docker ps --format '{{.Names}}' | grep -qx 'agent_trading-app-1'; then
    actual_python="$(docker exec agent_trading-app-1 python3 -c 'import platform; print(platform.python_version())')"
  else
    actual_python="$(python3 -c 'import platform; print(platform.python_version())')"
    echo "WARN: agent_trading-app-1 컨테이너가 없어 host Python을 확인했습니다." >&2
  fi
  check_exact_version "python" "$expected_python" "$actual_python"

  if docker image inspect node:20-slim >/dev/null 2>&1; then
    local actual_node
    actual_node="$(docker run --rm node:20-slim node --version | sed 's/^v//')"
    check_exact_version "node" "$expected_node" "$actual_node"
    local actual_npm
    actual_npm="$(docker run --rm node:20-slim npm --version)"
    check_exact_version "npm" "$expected_npm" "$actual_npm"
  elif command -v node >/dev/null 2>&1; then
    local actual_node
    actual_node="$(node --version | sed 's/^v//')"
    check_exact_version "node" "$expected_node" "$actual_node"
    if command -v npm >/dev/null 2>&1; then
      local actual_npm
      actual_npm="$(npm --version)"
      check_exact_version "npm" "$expected_npm" "$actual_npm"
    else
      fail "npm 버전을 확인할 수 없습니다."
    fi
  else
    fail "Node.js 버전을 확인할 수 없습니다."
  fi

  if docker ps --format '{{.Names}}' | grep -qx 'trading_db'; then
    local actual_postgres
    actual_postgres="$(docker exec trading_db psql -U trading -d trading -tAc 'SHOW server_version;' 2>/dev/null | tr -d '[:space:]')"
    check_exact_version "postgres" "$expected_postgres" "$actual_postgres"
  else
    echo "postgres=not-checked"
    echo "WARN: trading_db 컨테이너가 실행 중이 아니라 PostgreSQL 서버 버전을 확인하지 못했습니다." >&2
  fi

  [[ -f "$ROOT_DIR/.env.example" ]] || fail ".env.example 파일이 없습니다."
  echo "env_template=.env.example"
  if [[ -f "$ROOT_DIR/.env" ]]; then
    echo "env_file=present-redacted"
  else
    echo "env_file=missing"
  fi
}

docs_check() {
  python3 - <<'PY'
import re
from pathlib import Path

root = Path("/workspace/agent_trading")
files = [
    root / "README.md",
    root / "CLAUDE.md",
    root / "AGENTS.md",
    root / "src" / "AGENTS.md",
    root / "admin_ui" / "AGENTS.md",
    root / "docs" / "99_meta_handover" / "agent_workspace_guide.md",
]

missing = []
line_suffix = re.compile(r"^(.*\.(?:md|py|sql|yml|yaml|toml|json|txt|sh))(?:[:#]L?\d+(?:-L?\d+)?)$")

for file_path in files:
    if not file_path.exists():
        missing.append((str(file_path.relative_to(root)), "<file>", str(file_path)))
        continue
    text = file_path.read_text()
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1).split("#", 1)[0]
        if not target or re.match(r"^[a-z]+://", target) or target.startswith("mailto:"):
            continue
        candidate = target.replace("%20", " ")
        line_match = line_suffix.match(candidate)
        if line_match:
            candidate = line_match.group(1)
        resolved = Path(candidate) if candidate.startswith("/") else (file_path.parent / candidate).resolve()
        if not resolved.exists():
            missing.append((str(file_path.relative_to(root)), target, str(resolved)))

print(f"markdown_link_missing_count={len(missing)}")
for source, target, resolved in missing:
    print(f"MISSING {source} -> {target} => {resolved}")

raise SystemExit(1 if missing else 0)
PY
}

main() {
  cd "$ROOT_DIR"

  local command="${1:-}"
  shift || true

  case "$command" in
    status)
      echo "root=$ROOT_DIR"
      python3 --version
      git status --short
      ;;
    env-check)
      env_check
      ;;
    py-compile)
      local target="${1:-}"
      require_arg "$target" "python_file"
      local file_path
      file_path="$(require_existing_file "$target")"
      [[ "$file_path" == *.py ]] || fail "Python 파일만 py-compile 대상이 될 수 있습니다: $target"
      run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m py_compile "$target"
      ;;
    test-one)
      local selector="${1:-}"
      require_arg "$selector" "test_selector"
      [[ "$selector" == *::* ]] || fail "test-one은 tests/path.py::test_name 형태만 허용합니다."
      require_safe_test_selector "$selector"
      run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m pytest "$selector" -v
      ;;
    test-file)
      local test_file="${1:-}"
      require_arg "$test_file" "test_file"
      require_safe_test_selector "$test_file"
      run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m pytest "$test_file" -v
      ;;
    lint-path)
      local target_path="${1:-}"
      require_arg "$target_path" "path"
      local resolved_path
      resolved_path="$(resolve_in_repo "$target_path")"
      [[ -e "$resolved_path" ]] || fail "경로가 존재하지 않습니다: $target_path"
      run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m ruff check "$target_path"
      ;;
    docs-check)
      docs_check
      ;;
    admin-test-one)
      local selector="${1:-}"
      require_arg "$selector" "test_selector"
      [[ "$selector" != -* ]] || fail "옵션처럼 보이는 테스트 selector는 허용하지 않습니다: $selector"
      [[ -d admin_ui ]] || fail "admin_ui 디렉터리가 없습니다."
      run_with_timeout "$SAFE_TIMEOUT_SECONDS" bash -lc "cd '$ROOT_DIR/admin_ui' && npm run test:run -- '$selector'"
      ;;
    full-test)
      require_heavy_allowed
      run_python_with_timeout "$HEAVY_TIMEOUT_SECONDS" -m pytest tests/ -v
      ;;
    docker-test)
      require_heavy_allowed
      run_with_timeout "$HEAVY_TIMEOUT_SECONDS" docker compose exec app python3 -m pytest tests/ -v
      ;;
    smoke)
      require_heavy_allowed
      run_python_with_timeout "$HEAVY_TIMEOUT_SECONDS" -m pytest tests/smoke/test_kis_sandbox_smoke.py -v -m "smoke" -W ignore::DeprecationWarning
      ;;
    admin-build)
      require_heavy_allowed
      run_with_timeout "$HEAVY_TIMEOUT_SECONDS" bash -lc "cd '$ROOT_DIR/admin_ui' && npm run build"
      ;;
    admin-test-all)
      require_heavy_allowed
      run_with_timeout "$HEAVY_TIMEOUT_SECONDS" bash -lc "cd '$ROOT_DIR/admin_ui' && npm run test:run"
      ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      usage >&2
      fail "알 수 없는 명령입니다: $command"
      ;;
  esac
}

main "$@"
