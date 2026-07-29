#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
export HARNESS_ROOT_DIR="$ROOT_DIR"
SAFE_TIMEOUT_SECONDS="${HARNESS_SAFE_TIMEOUT_SECONDS:-90}"
HEAVY_TIMEOUT_SECONDS="${HARNESS_HEAVY_TIMEOUT_SECONDS:-900}"

usage() {
  cat <<'EOF'
사용법:
  bash scripts/harness/run.sh status
  bash scripts/harness/run.sh check quick
  bash scripts/harness/run.sh check changed
  bash scripts/harness/run.sh type-check backend
  bash scripts/harness/run.sh type-check frontend
  bash scripts/harness/run.sh security scan
  bash scripts/harness/run.sh py-compile <python_file>
  bash scripts/harness/run.sh test-one <tests/path.py::test_name>
  bash scripts/harness/run.sh test-file <tests/path.py>
  bash scripts/harness/run.sh lint-path <path>
  bash scripts/harness/run.sh accept docs
  bash scripts/harness/run.sh accept ci
  bash scripts/harness/run.sh accept env
  bash scripts/harness/run.sh accept db-structure
  bash scripts/harness/run.sh accept architecture
  bash scripts/harness/run.sh accept style
  bash scripts/harness/run.sh accept no-bypass
  bash scripts/harness/run.sh accept backend-file <src/agent_trading/file.py>
  bash scripts/harness/run.sh accept backend-runtime
  bash scripts/harness/run.sh accept frontend
  bash scripts/harness/run.sh accept ops-report <summary_json>
  bash scripts/harness/run.sh dump ops-report [YYYY-MM-DD]
  bash scripts/harness/run.sh run api-inmemory
  bash scripts/harness/run.sh run api-postgres
  bash scripts/harness/run.sh admin-test-one <test_file_or_selector>

호환 alias:
  bash scripts/harness/run.sh docs-check
  bash scripts/harness/run.sh env-check

승인 필요 명령:
  HARNESS_ALLOW_OPS_DUMP=1 bash scripts/harness/run.sh dump ops-report [YYYY-MM-DD]
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

require_env_names() {
  local missing=0
  local name
  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      echo "환경변수 누락: $name" >&2
      missing=1
    fi
  done
  [[ "$missing" -eq 0 ]] || fail ".env.example을 참고해 사용자가 직접 export한 뒤 다시 실행하세요."
}

resolve_in_repo() {
  local raw="$1"
  [[ "$raw" != -* ]] || fail "옵션처럼 보이는 경로는 허용하지 않습니다: $raw"
  local resolved
  resolved="$(realpath -m "$ROOT_DIR/$raw")"
  [[ "$resolved" == "$ROOT_DIR"/* ]] || fail "프로젝트 밖 경로는 허용하지 않습니다: $raw"
  printf '%s\n' "$resolved"
}

repo_relative_from_resolved() {
  local resolved="$1"
  printf '%s\n' "${resolved#$ROOT_DIR/}"
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

require_ops_dump_allowed() {
  [[ "${HARNESS_ALLOW_OPS_DUMP:-}" == "1" ]] || fail "운영 리포트 DB 덤프는 차단되었습니다. 사용자가 명시 승인한 경우에만 HARNESS_ALLOW_OPS_DUMP=1을 설정해 실행하세요."
}

run_api_inmemory() {
  exec python3 -m uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port "${API_PORT:-8000}"
}

run_api_postgres() {
  require_env_names DATABASE_HOST DATABASE_PORT DATABASE_NAME DATABASE_USER DATABASE_PASSWORD INSPECTION_API_TOKEN
  API_RUNTIME_MODE=postgres exec python3 -m uvicorn agent_trading.api.app:create_app_from_env --factory --reload --host 0.0.0.0 --port "${API_PORT:-8000}"
}

env_check() {
  accept_env
}

accept_ci() {
  python3 - <<'PY'
import os
import re
from pathlib import Path

root = Path(os.environ["HARNESS_ROOT_DIR"])
workflow_dir = root / ".github" / "workflows"
workflow = root / ".github" / "workflows" / "harness.yml"
readme = root / "README.md"
harness_readme = root / "scripts" / "harness" / "README.md"
agents = root / "AGENTS.md"
makefile = root / "Makefile"

required_files = [workflow, workflow_dir, readme, harness_readme, agents, makefile]
missing_files = [path for path in required_files if not path.exists()]
workflow_files = []
if workflow_dir.exists():
    workflow_files = sorted(
        path for path in workflow_dir.iterdir()
        if path.suffix in {".yml", ".yaml"}
    )

workflow_text = workflow.read_text() if workflow.exists() else ""
workflow_lines = workflow_text.splitlines()
workflow_text_by_path = {
    path: path.read_text() for path in workflow_files
}

def contains(path: Path, *needles: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text()
    return all(needle in text for needle in needles)

def section_between(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        return ""
    end_index = text.find(end, start_index + len(start))
    return text[start_index:] if end_index < 0 else text[start_index:end_index]

harness_command_lines = [
    (path, line_no, line)
    for path, text in workflow_text_by_path.items()
    for line_no, line in enumerate(text.splitlines(), 1)
    if "bash scripts/harness/run.sh" in line
]

required_harness_commands = [
    "bash scripts/harness/run.sh check quick",
    "bash scripts/harness/run.sh accept db-structure",
    "bash scripts/harness/run.sh accept architecture",
    "bash scripts/harness/run.sh accept style",
    "bash scripts/harness/run.sh accept no-bypass",
    "bash scripts/harness/run.sh type-check backend",
    "bash scripts/harness/run.sh type-check frontend",
    "bash scripts/harness/run.sh security scan",
]
missing_harness_commands = [
    command for command in required_harness_commands
    if command not in workflow_text
]

direct_verifier_pattern = re.compile(
    r"\b("
    r"python3\s+-m\s+pytest|pytest\b|"
    r"python3\s+-m\s+ruff|ruff\s+check|"
    r"npm\s+(test|run\s+(test|test:run|build))|"
    r"vitest\b|tsc\s+--noEmit"
    r")"
)
direct_verifier_lines = []
for path, text in workflow_text_by_path.items():
    for line_no, line in enumerate(text.splitlines(), 1):
        if "bash scripts/harness/run.sh" in line:
            continue
        if direct_verifier_pattern.search(line):
            direct_verifier_lines.append((path, line_no, line.strip()))

deploy_impact_pattern = re.compile(
    r"(appleboy/ssh-action|SERVER_HOST|SERVER_KEY|"
    r"docker\s+compose\s+(up|down)|docker-compose\s+(up|down)|"
    r"git\s+pull\s+origin\s+main|git\s+reset\s+--hard\s+origin/main)"
)
deploy_workflows = [
    (path, text) for path, text in workflow_text_by_path.items()
    if deploy_impact_pattern.search(text)
]
legacy_docker_compose_hits = [
    (path, line_no, line.strip())
    for path, text in workflow_text_by_path.items()
    for line_no, line in enumerate(text.splitlines(), 1)
    if re.search(r"\bdocker-compose\s+(up|down|run|build|exec|ps|logs|restart)\b", line)
]

def deploy_has_harness_gate(text: str) -> bool:
    needs_safe_gate = (
        (
            "needs: safe" in text
            or "needs: [safe, changes]" in text
            or "needs: [changes, safe]" in text
        )
        and "needs.safe.result == 'success'" in text
    )
    workflow_run_gate = (
        "workflow_run:" in text
        and "Harness" in text
        and "conclusion == 'success'" in text
    )
    return needs_safe_gate or workflow_run_gate

ungated_deploy_workflows = [
    path for path, text in deploy_workflows
    if not deploy_has_harness_gate(text)
]
deploy_missing_migration_workflows = [
    path for path, text in deploy_workflows
    if "docker compose run --rm migrate" not in text
]
deploy_change_detector_present = (
    "Deployment change detector" in workflow_text
    and "deploy_relevant_file_count" in workflow_text
    and "deploy_skipped_by_docs_only_count" in workflow_text
)
deploy_without_change_detector_count = (
    0 if deploy_change_detector_present else len(deploy_workflows)
)

safe_section = section_between(workflow_text, "  safe:", "  heavy:")
safe_forbidden_heavy_pattern = re.compile(
    r"(HARNESS_ALLOW_HEAVY|full-test|docker-test|smoke|admin-build|admin-test-all)"
)
safe_forbidden_heavy_lines = [
    (line_no, line.strip())
    for line_no, line in enumerate(safe_section.splitlines(), 1)
    if safe_forbidden_heavy_pattern.search(line)
]

contract_checks = [
    ("workflow_declares_pull_request", "pull_request:" in workflow_text),
    ("workflow_declares_main_push", "push:" in workflow_text and "- main" in workflow_text),
    ("workflow_declares_manual_heavy", "workflow_dispatch:" in workflow_text and "run_heavy:" in workflow_text),
    ("workflow_safe_job_present", "  safe:" in workflow_text),
    ("workflow_heavy_job_present", "  heavy:" in workflow_text),
    ("workflow_uses_setup_python_pin", "python-version-file: .python-version" in workflow_text),
    ("workflow_uses_setup_node_pin", "node-version-file: admin_ui/.nvmrc" in workflow_text),
    ("workflow_uses_postgres_pin", "POSTGRES_VERSION=\"$(cat .postgres-version)\"" in workflow_text and "\"postgres:${POSTGRES_VERSION}\"" in workflow_text),
    ("workflow_heavy_requires_dispatch", "if: github.event_name == 'workflow_dispatch' && inputs.run_heavy == 'true'" in workflow_text),
    ("workflow_heavy_sets_allow_flag", 'HARNESS_ALLOW_HEAVY: "1"' in workflow_text),
    ("workflow_deploy_depends_on_safe", contains(workflow, "needs: [safe, changes]", "needs.safe.result == 'success'")),
    ("workflow_deploy_depends_on_change_detector", contains(workflow, "Deployment change detector", "needs.changes.outputs.deploy_required == '1'", "deploy_skipped_by_docs_only_count")),
    ("workflow_deploy_runs_migration_before_restart", contains(workflow, "docker compose run --rm migrate", "docker compose up -d --build --remove-orphans")),
    ("readme_declares_ci_harness", contains(readme, "CI 검증 기준", ".github/workflows/harness.yml", "bash scripts/harness/run.sh", "Require Harness on main", "Safe harness contracts")),
    ("harness_readme_declares_ci_harness", contains(harness_readme, "CI 공동 사용 원칙", "safe", "workflow_dispatch", "HARNESS_ALLOW_HEAVY=1", "Require Harness on main", "Safe harness contracts")),
    ("workflow_fetches_full_history_for_diff_contracts", contains(workflow, "fetch-depth: 0")),
    ("agents_declares_ci_harness", contains(agents, ".github/workflows/harness.yml", "bash scripts/harness/run.sh")),
    ("makefile_declares_accept_ci", contains(makefile, "accept-ci:", "bash scripts/harness/run.sh accept ci")),
]
failed_contract_checks = [name for name, passed in contract_checks if not passed]

metrics = {
    "required_file_missing_count": len(missing_files),
    "workflow_file_count": len(workflow_files),
    "harness_command_count": len(harness_command_lines),
    "required_harness_command_missing_count": len(missing_harness_commands),
    "direct_verifier_command_count": len(direct_verifier_lines),
    "safe_forbidden_heavy_command_count": len(safe_forbidden_heavy_lines),
    "deploy_workflow_count": len(deploy_workflows),
    "ungated_deploy_workflow_count": len(ungated_deploy_workflows),
    "deploy_without_change_detector_count": deploy_without_change_detector_count,
    "deploy_missing_migration_count": len(deploy_missing_migration_workflows),
    "legacy_docker_compose_count": len(legacy_docker_compose_hits),
    "ci_contract_failed_count": len(failed_contract_checks),
}

informational_metrics = {
    "harness_command_count",
    "workflow_file_count",
    "deploy_workflow_count",
}
passed = all(
    value == 0
    for key, value in metrics.items()
    if key not in informational_metrics
) and metrics["harness_command_count"] > 0

print(f"ACCEPT ci: {'PASS' if passed else 'FAIL'}")
for key, value in metrics.items():
    print(f"- {key}={value}")
print("- full_test_run=0")
print("- full_build_run=0")
print("- database_connection_run=0")
print("- external_network_run=0")

if missing_files:
    print("DETAIL missing_files:")
    for path in missing_files:
        print(f"- {path.relative_to(root)}")

if missing_harness_commands:
    print("DETAIL missing_harness_commands:")
    for command in missing_harness_commands:
        print(f"- {command}")

if direct_verifier_lines:
    print("DETAIL direct_verifier_commands:")
    for source, line_no, line in direct_verifier_lines:
        print(f"- {source.relative_to(root)}:{line_no}: {line}")

if safe_forbidden_heavy_lines:
    print("DETAIL safe_forbidden_heavy_commands:")
    for line_no, line in safe_forbidden_heavy_lines:
        print(f"- safe_section:{line_no}: {line}")

if ungated_deploy_workflows:
    print("DETAIL ungated_deploy_workflows:")
    for path in ungated_deploy_workflows:
        print(f"- {path.relative_to(root)}")

if deploy_missing_migration_workflows:
    print("DETAIL deploy_missing_migration_workflows:")
    for path in deploy_missing_migration_workflows:
        print(f"- {path.relative_to(root)}")

if legacy_docker_compose_hits:
    print("DETAIL legacy_docker_compose:")
    for source, line_no, line in legacy_docker_compose_hits:
        print(f"- {source.relative_to(root)}:{line_no}: {line}")

if failed_contract_checks:
    print("DETAIL failed_contract_checks:")
    for name in failed_contract_checks:
        print(f"- {name}")

raise SystemExit(0 if passed else 1)
PY
}

check_quick() {
  local step_count=8
  local failed_step_count=0
  local accept_docs_exit_code=0
  local accept_ci_exit_code=0
  local accept_no_bypass_exit_code=0
  local accept_env_exit_code=0
  local accept_backend_runtime_exit_code=0
  local accept_frontend_exit_code=0
  local lint_exit_code=0
  local diff_check_exit_code=0

  echo "CHECK quick: start"

  if accept_docs; then
    accept_docs_exit_code=0
  else
    accept_docs_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if accept_ci; then
    accept_ci_exit_code=0
  else
    accept_ci_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if accept_no_bypass; then
    accept_no_bypass_exit_code=0
  else
    accept_no_bypass_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if accept_env; then
    accept_env_exit_code=0
  else
    accept_env_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if accept_backend_runtime; then
    accept_backend_runtime_exit_code=0
  else
    accept_backend_runtime_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if accept_frontend; then
    accept_frontend_exit_code=0
  else
    accept_frontend_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m ruff check src/agent_trading; then
    lint_exit_code=0
  else
    lint_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if git diff --check; then
    diff_check_exit_code=0
  else
    diff_check_exit_code=$?
    failed_step_count=$((failed_step_count + 1))
  fi

  if [[ "$failed_step_count" -eq 0 ]]; then
    echo "CHECK quick: PASS"
  else
    echo "CHECK quick: FAIL"
  fi
  echo "- step_count=$step_count"
  echo "- failed_step_count=$failed_step_count"
  echo "- accept_docs_exit_code=$accept_docs_exit_code"
  echo "- accept_ci_exit_code=$accept_ci_exit_code"
  echo "- accept_no_bypass_exit_code=$accept_no_bypass_exit_code"
  echo "- accept_env_exit_code=$accept_env_exit_code"
  echo "- accept_backend_runtime_exit_code=$accept_backend_runtime_exit_code"
  echo "- accept_frontend_exit_code=$accept_frontend_exit_code"
  echo "- lint_exit_code=$lint_exit_code"
  echo "- diff_check_exit_code=$diff_check_exit_code"
  echo "- full_test_run=0"
  echo "- full_build_run=0"
  echo "- database_connection_run=0"
  echo "- external_network_run=0"

  [[ "$failed_step_count" -eq 0 ]]
}

check_changed() {
  local changed_paths=()
  local deleted_backend_paths=()
  local path
  local changed_backend_file_count=0
  local deleted_backend_file_count=0
  local skipped_non_backend_file_count=0
  local failed_backend_file_count=0
  local total_changed_path_count=0

  mapfile -t changed_paths < <(
    {
      git diff --name-only --diff-filter=ACMR
      git ls-files --others --exclude-standard
    } | sort -u
  )
  mapfile -t deleted_backend_paths < <(
    git diff --name-only --diff-filter=D -- src/agent_trading | awk '/\.py$/ {print}' | sort -u
  )

  total_changed_path_count="${#changed_paths[@]}"
  deleted_backend_file_count="${#deleted_backend_paths[@]}"

  echo "CHECK changed: start"

  for path in "${changed_paths[@]}"; do
    case "$path" in
      src/agent_trading/*.py|src/agent_trading/**/*.py)
        if [[ -f "$path" ]]; then
          changed_backend_file_count=$((changed_backend_file_count + 1))
          if accept_backend_file "$path"; then
            :
          else
            failed_backend_file_count=$((failed_backend_file_count + 1))
          fi
        fi
        ;;
      *)
        skipped_non_backend_file_count=$((skipped_non_backend_file_count + 1))
        ;;
    esac
  done

  if [[ "$failed_backend_file_count" -eq 0 && "$deleted_backend_file_count" -eq 0 ]]; then
    echo "CHECK changed: PASS"
  else
    echo "CHECK changed: FAIL"
  fi
  echo "- total_changed_path_count=$total_changed_path_count"
  echo "- changed_backend_file_count=$changed_backend_file_count"
  echo "- deleted_backend_file_count=$deleted_backend_file_count"
  echo "- skipped_non_backend_file_count=$skipped_non_backend_file_count"
  echo "- failed_backend_file_count=$failed_backend_file_count"
  echo "- full_test_run=0"
  echo "- full_build_run=0"
  echo "- database_connection_run=0"
  echo "- external_network_run=0"

  if [[ "$deleted_backend_file_count" -gt 0 ]]; then
    echo "DETAIL deleted_backend_files:"
    for path in "${deleted_backend_paths[@]}"; do
      echo "- $path"
    done
  fi

  [[ "$failed_backend_file_count" -eq 0 && "$deleted_backend_file_count" -eq 0 ]]
}

type_check_backend() {
  local mypy_available=0
  local pyright_available=0
  local backend_type_tool_missing_count=0
  local backend_type_check_run=0
  local backend_type_check_failed_count=0
  local selected_tool="none"
  local exit_code=0

  if run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('mypy') else 1)" >/dev/null 2>&1; then
    mypy_available=1
  fi
  if run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('pyright') else 1)" >/dev/null 2>&1; then
    pyright_available=1
  fi

  if [[ "$mypy_available" -eq 1 ]]; then
    selected_tool="mypy"
    backend_type_check_run=1
    if run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m mypy src/agent_trading; then
      exit_code=0
    else
      exit_code=$?
      backend_type_check_failed_count=1
    fi
  elif [[ "$pyright_available" -eq 1 ]]; then
    selected_tool="pyright"
    backend_type_check_run=1
    if run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m pyright src/agent_trading; then
      exit_code=0
    else
      exit_code=$?
      backend_type_check_failed_count=1
    fi
  else
    backend_type_tool_missing_count=1
  fi

  if [[ "$backend_type_check_failed_count" -eq 0 ]]; then
    echo "TYPE-CHECK backend: PASS"
  else
    echo "TYPE-CHECK backend: FAIL"
  fi
  echo "- selected_tool=$selected_tool"
  echo "- mypy_available=$mypy_available"
  echo "- pyright_available=$pyright_available"
  echo "- backend_type_tool_missing_count=$backend_type_tool_missing_count"
  echo "- backend_type_check_run=$backend_type_check_run"
  echo "- backend_type_check_failed_count=$backend_type_check_failed_count"
  echo "- full_test_run=0"
  echo "- database_connection_run=0"
  echo "- external_network_run=0"

  return "$exit_code"
}

type_check_frontend() {
  local script_name="none"
  local frontend_typecheck_script_missing_count=0
  local frontend_type_check_run=0
  local frontend_type_check_failed_count=0
  local exit_code=0

  [[ -d admin_ui ]] || fail "admin_ui 디렉터리가 없습니다."

  script_name="$(
    python3 - <<'PY'
import json
from pathlib import Path

scripts = json.loads(Path("admin_ui/package.json").read_text()).get("scripts", {})
for candidate in ("typecheck", "type-check", "check:types"):
    if candidate in scripts:
        print(candidate)
        break
else:
    print("none")
PY
  )"

  if [[ "$script_name" == "none" ]]; then
    frontend_typecheck_script_missing_count=1
  else
    frontend_type_check_run=1
    if run_with_timeout "$SAFE_TIMEOUT_SECONDS" bash -lc "cd '$ROOT_DIR/admin_ui' && npm run '$script_name'"; then
      exit_code=0
    else
      exit_code=$?
      frontend_type_check_failed_count=1
    fi
  fi

  if [[ "$frontend_type_check_failed_count" -eq 0 ]]; then
    echo "TYPE-CHECK frontend: PASS"
  else
    echo "TYPE-CHECK frontend: FAIL"
  fi
  echo "- selected_script=$script_name"
  echo "- frontend_typecheck_script_missing_count=$frontend_typecheck_script_missing_count"
  echo "- frontend_type_check_run=$frontend_type_check_run"
  echo "- frontend_type_check_failed_count=$frontend_type_check_failed_count"
  echo "- full_build_run=0"
  echo "- full_test_run=0"
  echo "- external_network_run=0"

  return "$exit_code"
}

security_scan() {
  python3 - <<'PY'
import os
import re
import subprocess
from pathlib import Path

root = Path(os.environ["HARNESS_ROOT_DIR"])

excluded_dirs = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "__pycache__",
}
excluded_suffixes = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".sqlite",
    ".db",
    ".pyc",
}
excluded_names = {
    "package-lock.json",
    "requirements.lock",
    "tsconfig.tsbuildinfo",
}
allowed_placeholder_values = {
    "",
    "<missing>",
    "<redacted>",
    "redacted",
    "present-redacted",
    "your_api_key_here",
    "your-api-key-here",
    "changeme",
    "change_me",
    "example",
    "dummy",
    "test",
}

key_pattern = re.compile(
    r"(?i)\b(secret|password|passwd|authorization|approval_key|access_token|refresh_token|bearer_token|appkey|appsecret|api_key|client_secret)\b"
)
assignment_pattern = re.compile(
    r"(?i)\b(secret|password|passwd|authorization|approval_key|access_token|refresh_token|bearer_token|appkey|appsecret|api_key|client_secret)\b"
    r"\s*[:=]\s*['\"]?([^'\"\s#,}]{8,})"
)
bearer_pattern = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}")
identifier_reference_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

def run_git(args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line for line in completed.stdout.splitlines() if line]

def is_scannable(path: Path) -> bool:
    parts = set(path.parts)
    if parts & excluded_dirs:
        return False
    if path.name in excluded_names:
        return False
    if path.name == ".env" or path.name.startswith(".env."):
        return False
    if path.suffix.lower() in excluded_suffixes:
        return False
    return path.is_file()

def normalized_value(value: str) -> str:
    return value.strip().strip("'\"").lower()

def is_placeholder(value: str) -> bool:
    normalized = normalized_value(value)
    if normalized in allowed_placeholder_values:
        return True
    if normalized.startswith("bearer"):
        return True
    if identifier_reference_pattern.fullmatch(value.strip().strip("'\"")):
        return True
    return (
        "example" in normalized
        or "placeholder" in normalized
        or "redacted" in normalized
        or normalized.startswith("<")
    )

changed_files = [Path(item) for item in run_git(["diff", "--name-only", "--diff-filter=ACMR"])]
untracked_files = [Path(item) for item in run_git(["ls-files", "--others", "--exclude-standard"])]
candidate_files = sorted(set(changed_files + untracked_files))
env_tracked_files = [
    path
    for path in candidate_files
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example")
]

scan_files = []
for path in candidate_files:
    absolute = root / path
    if is_scannable(absolute):
        scan_files.append(path)

secret_hits: list[tuple[str, int, str]] = []
read_error_count = 0

for path in scan_files:
    absolute = root / path
    try:
        text = absolute.read_text(errors="ignore")
    except Exception:
        read_error_count += 1
        continue
    for line_no, line in enumerate(text.splitlines(), 1):
        if not key_pattern.search(line) and "Bearer " not in line:
            continue
        for match in assignment_pattern.finditer(line):
            value = match.group(2)
            if not is_placeholder(value):
                secret_hits.append((path.as_posix(), line_no, match.group(1).lower()))
        if bearer_pattern.search(line):
            secret_hits.append((path.as_posix(), line_no, "bearer"))

secret_hits = sorted(set(secret_hits))

metrics = {
    "changed_file_count": len(changed_files),
    "untracked_file_count": len(untracked_files),
    "candidate_file_count": len(candidate_files),
    "scanned_file_count": len(scan_files),
    "read_error_count": read_error_count,
    "tracked_env_file_count": len(env_tracked_files),
    "secret_hit_count": len(secret_hits),
    "dependency_audit_run": 0,
    "external_network_run": 0,
    "full_test_run": 0,
    "full_build_run": 0,
}

passed = (
    metrics["read_error_count"] == 0
    and metrics["tracked_env_file_count"] == 0
    and metrics["secret_hit_count"] == 0
)

print(f"SECURITY scan: {'PASS' if passed else 'FAIL'}")
for key, value in metrics.items():
    print(f"- {key}={value}")

if env_tracked_files:
    print("DETAIL tracked_env_files:")
    for path in env_tracked_files:
        print(f"- {path.as_posix()}")

if secret_hits:
    print("DETAIL secret_hits:")
    for path, line_no, kind in secret_hits:
        print(f"- {path}:{line_no}: kind={kind}")

raise SystemExit(0 if passed else 1)
PY
}

accept_docs() {
  python3 - <<'PY'
import os
import re
from pathlib import Path

root = Path(os.environ["HARNESS_ROOT_DIR"])
core_docs = [
    root / "README.md",
    root / "AGENTS.md",
    root / "CLAUDE.md",
    root / "src" / "AGENTS.md",
    root / "admin_ui" / "AGENTS.md",
    root / "scripts" / "harness" / "README.md",
    root / "docs" / "99_meta_handover" / "agent_workspace_guide.md",
    root / "docs" / "20_harness_engineering" / "ai_friendly_error_message_contract.md",
    root / "docs" / "20_harness_engineering" / "definition_of_done.md",
    root / "docs" / "20_harness_engineering" / "no_bypass_policy.md",
    root / "tests" / "fixtures" / "README.md",
]
required_files = core_docs + [
    root / "scripts" / "harness" / "run.sh",
    root / "Makefile",
]

line_suffix = re.compile(r"^(.*\.(?:md|py|sql|yml|yaml|toml|json|txt|sh))(?:[:#]L?\d+(?:-L?\d+)?)$")
deprecated_reference = re.compile(r"\bplan_docs\b|\]\((?:\.\./)*plans/")

missing_files = [path for path in required_files if not path.exists()]
missing_links = []
deprecated_hits = []

make_targets = set()
makefile = root / "Makefile"
if makefile.exists():
    for line in makefile.read_text().splitlines():
        if line.startswith("\t") or line.startswith(" "):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*:", line)
        if match:
            make_targets.add(match.group(1))

documented_make_target_misses = []

for file_path in core_docs:
    if not file_path.exists():
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
            missing_links.append((file_path, target, resolved))
    for line_no, line in enumerate(text.splitlines(), 1):
        if deprecated_reference.search(line):
            deprecated_hits.append((file_path, line_no, line.strip()))
        for match in re.finditer(r"\bmake\s+([A-Za-z0-9_.-]+)", line):
            target = match.group(1)
            next_char = line[match.end(1):match.end(1) + 1]
            if next_char == "*" or target not in make_targets:
                if next_char != "*":
                    documented_make_target_misses.append(
                        (file_path, line_no, target, line.strip())
                    )

def contains(path: Path, *needles: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text()
    return all(needle in text for needle in needles)

def not_contains(path: Path, *needles: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text()
    return all(needle not in text for needle in needles)

def absent(path: Path) -> bool:
    return not path.exists()

semantic_checks = [
    ("readme_routes_to_agents", contains(root / "README.md", "AGENTS.md", "CLAUDE.md", "agent_workspace_guide.md", "scripts/harness/README.md")),
    ("readme_quickstart_uses_accept", contains(root / "README.md", "기본 하네스 검증", "make accept-docs", "make accept-env", "HARNESS_ALLOW_HEAVY=1 make heavy-full-test")),
    ("readme_removes_stale_full_test_count", not_contains(root / "README.md", "53 passed, 0 failed, 0 errors")),
    ("claude_routes_to_nested_agents", contains(root / "CLAUDE.md", "AGENTS.md", "src/AGENTS.md", "admin_ui/AGENTS.md", "scripts/harness/README.md")),
    ("claude_routes_to_definition_of_done", contains(root / "CLAUDE.md", "definition_of_done.md", "완료")),
    ("claude_routes_to_language_policy", contains(root / "CLAUDE.md", "언어 원칙", "중국어 사용 금지")),
    ("claude_declares_api_run", contains(root / "CLAUDE.md", "run api-inmemory", "run api-postgres")),
    ("root_agents_requires_harness", contains(root / "AGENTS.md", "scripts/harness/run.sh", "검증 부하 제한")),
    ("root_agents_declares_no_chinese_policy", contains(root / "AGENTS.md", "중국어", "사용하지 않는다")),
    ("root_agents_env_secret_policy", contains(root / "AGENTS.md", ".env", "직접 수정하지 않는다", "노출하지 않는다")),
    ("root_agents_routes_to_definition_of_done", contains(root / "AGENTS.md", "definition_of_done.md", "완료를 주장")),
    ("root_agents_routes_to_no_bypass_policy", contains(root / "AGENTS.md", "no_bypass_policy.md", "accept no-bypass")),
    ("root_agents_prefers_accept_env", contains(root / "AGENTS.md", "accept env", "make accept-env", "env-check", "호환 alias")),
    ("workspace_guide_declares_project_root", contains(root / "docs" / "99_meta_handover" / "agent_workspace_guide.md", "/workspace/agent_trading/", "문서 역할 분리")),
    ("workspace_guide_routes_to_definition_of_done", contains(root / "docs" / "99_meta_handover" / "agent_workspace_guide.md", "definition_of_done.md", "완료를 주장")),
    ("workspace_guide_declares_no_chinese_policy", contains(root / "docs" / "99_meta_handover" / "agent_workspace_guide.md", "중국어", "사용하지 않는다")),
    ("definition_of_done_declares_completion_contract", contains(root / "docs" / "20_harness_engineering" / "definition_of_done.md", "Definition of Done", "완료", "검증하지 못한 가정", "failed_step_count", "full_test", "Safe harness contracts")),
    ("no_bypass_policy_declares_two_level_policy", contains(root / "docs" / "20_harness_engineering" / "no_bypass_policy.md", "Hard Fail", "Review Flag", "hard_bypass_count", "review_bypass_count")),
    ("ai_friendly_error_contract_declares_structured_errors", contains(root / "docs" / "20_harness_engineering" / "ai_friendly_error_message_contract.md", "error_code", "next_action", "count")),
    ("workspace_guide_prefers_accept_env", contains(root / "docs" / "99_meta_handover" / "agent_workspace_guide.md", "accept env", "make accept-env")),
    ("harness_readme_declares_metrics", contains(root / "scripts" / "harness" / "README.md", "accept backend-file", "tests_run_count", "secret_key_hit_count")),
    ("harness_readme_declares_validation_layers", contains(root / "scripts" / "harness" / "README.md", "L0", "L6", "check quick", "make check-quick", "check changed", "make check-changed", "type-check backend", "make type-check-backend", "security scan", "make security-scan")),
    ("harness_readme_declares_api_run", contains(root / "scripts" / "harness" / "README.md", "run api-postgres", "INSPECTION_API_TOKEN")),
    ("harness_readme_declares_compat_aliases", contains(root / "scripts" / "harness" / "README.md", "docs-check", "env-check", "호환 alias")),
    ("harness_readme_routes_to_definition_of_done", contains(root / "scripts" / "harness" / "README.md", "definition_of_done.md", "완료를 주장")),
    ("harness_readme_declares_no_bypass", contains(root / "scripts" / "harness" / "README.md", "accept no-bypass", "hard_bypass_count", "review_bypass_count")),
    ("root_agents_declares_api_run", contains(root / "AGENTS.md", "run api-inmemory", "run api-postgres")),
    ("fixture_policy_present", contains(root / "tests" / "fixtures" / "README.md", "data/", "logs/", "tmp/")),
    ("pytest_config_single_source", absent(root / "pytest.ini") and contains(root / "pyproject.toml", "[tool.pytest.ini_options]", 'asyncio_default_fixture_loop_scope = "module"', "markers = [")),
]
failed_semantic_checks = [name for name, ok in semantic_checks if not ok]

metrics = {
    "required_file_missing_count": len(missing_files),
    "markdown_link_missing_count": len(missing_links),
    "deprecated_reference_count": len(deprecated_hits),
    "documented_make_target_missing_count": len(documented_make_target_misses),
    "semantic_check_failed_count": len(failed_semantic_checks),
}

passed = all(value == 0 for value in metrics.values())
print(f"ACCEPT docs: {'PASS' if passed else 'FAIL'}")
for key, value in metrics.items():
    print(f"- {key}={value}")

if missing_files:
    print("DETAIL missing_files:")
    for path in missing_files:
        print(f"- {path.relative_to(root)}")

if missing_links:
    print("DETAIL missing_links:")
    for source, target, resolved in missing_links:
        print(f"- {source.relative_to(root)} -> {target} => {resolved}")

if deprecated_hits:
    print("DETAIL deprecated_references:")
    for source, line_no, line in deprecated_hits:
        print(f"- {source.relative_to(root)}:{line_no}: {line}")

if documented_make_target_misses:
    print("DETAIL documented_make_target_misses:")
    for source, line_no, target, line in documented_make_target_misses:
        print(f"- {source.relative_to(root)}:{line_no}: make {target} :: {line}")

if failed_semantic_checks:
    print("DETAIL failed_semantic_checks:")
    for name in failed_semantic_checks:
        print(f"- {name}")

raise SystemExit(0 if passed else 1)
PY
}

accept_env() {
  ACCEPT_SAFE_TIMEOUT_SECONDS="$SAFE_TIMEOUT_SECONDS" python3 - <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path

root = Path(os.environ["HARNESS_ROOT_DIR"])
safe_timeout = int(os.environ.get("ACCEPT_SAFE_TIMEOUT_SECONDS", "90"))

def read_first_line(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text().splitlines()[0].strip()

def run_command(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=safe_timeout,
            check=False,
        )
    except Exception:
        return 1, ""
    return completed.returncode, completed.stdout.strip()

def normalize_postgres_version(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)+", value)
    return match.group(0) if match else value.replace(" ", "")

def parse_env_keys(path: Path) -> set[str]:
    keys = set()
    if not path.exists():
        return keys
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            keys.add(key)
    return keys

expected = {
    "python": read_first_line(root / ".python-version"),
    "node": read_first_line(root / "admin_ui" / ".nvmrc"),
    "npm": read_first_line(root / "admin_ui" / ".npm-version"),
    "postgres": read_first_line(root / ".postgres-version"),
}

required_files = [
    root / ".python-version",
    root / ".postgres-version",
    root / "requirements.lock",
    root / "pyproject.toml",
    root / "Dockerfile",
    root / "admin_ui" / ".nvmrc",
    root / "admin_ui" / ".npm-version",
    root / "admin_ui" / ".npmrc",
    root / "admin_ui" / "package.json",
    root / "admin_ui" / "package-lock.json",
    root / "admin_ui" / "Dockerfile",
    root / ".env.example",
    root / ".gitignore",
]
missing_files = [path for path in required_files if not path.exists()]

runtime_versions: dict[str, str] = {}
runtime_sources: dict[str, str] = {}

code, output = run_command(["docker", "exec", "agent_trading-app-1", "python3", "-c", "import platform; print(platform.python_version())"])
if code == 0 and output:
    runtime_versions["python"] = output
    runtime_sources["python"] = "agent_trading-app-1"
else:
    code, output = run_command(["python3", "-c", "import platform; print(platform.python_version())"])
    runtime_versions["python"] = output if code == 0 else ""
    runtime_sources["python"] = "host-python3"

pinned_node_image = f"node:{expected['node']}-slim" if expected["node"] else "node:20-slim"

code, output = run_command(["docker", "run", "--rm", pinned_node_image, "node", "--version"])
if code == 0 and output:
    runtime_versions["node"] = output.removeprefix("v")
    runtime_sources["node"] = pinned_node_image
else:
    code, output = run_command(["node", "--version"])
    runtime_versions["node"] = output.removeprefix("v") if code == 0 else ""
    runtime_sources["node"] = "host-node"

code, output = run_command(["docker", "run", "--rm", pinned_node_image, "npm", "--version"])
if code == 0 and output:
    runtime_versions["npm"] = output
    runtime_sources["npm"] = pinned_node_image
else:
    code, output = run_command(["npm", "--version"])
    runtime_versions["npm"] = output if code == 0 else ""
    runtime_sources["npm"] = "host-npm"

code, output = run_command(["docker", "exec", "trading_db", "psql", "-U", "trading", "-d", "trading", "-tAc", "SHOW server_version;"])
runtime_versions["postgres"] = normalize_postgres_version(output) if code == 0 else ""
runtime_sources["postgres"] = "trading_db"

runtime_mismatches = []
for name, expected_version in expected.items():
    actual_version = runtime_versions.get(name, "")
    if not expected_version or actual_version != expected_version:
        runtime_mismatches.append((name, expected_version or "<missing>", actual_version or "<missing>", runtime_sources.get(name, "<unknown>")))

static_checks = []
pyproject = (root / "pyproject.toml").read_text() if (root / "pyproject.toml").exists() else ""
dockerfile = (root / "Dockerfile").read_text() if (root / "Dockerfile").exists() else ""
admin_dockerfile = (root / "admin_ui" / "Dockerfile").read_text() if (root / "admin_ui" / "Dockerfile").exists() else ""
npmrc = (root / "admin_ui" / ".npmrc").read_text().strip() if (root / "admin_ui" / ".npmrc").exists() else ""
gitignore = (root / ".gitignore").read_text() if (root / ".gitignore").exists() else ""
requirements_lock = (root / "requirements.lock").read_text() if (root / "requirements.lock").exists() else ""

static_checks.append(("pyproject_python_range", 'requires-python = ">=3.14,<3.15"' in pyproject))
static_checks.append(("dockerfile_python_pin", f"FROM python:{expected['python']}-slim" in dockerfile))
static_checks.append(("dockerfile_uses_requirements_lock", "requirements.lock" in dockerfile and "--constraint requirements.lock" in dockerfile))
static_checks.append(("pyproject_dev_ruff_pin", '"ruff==0.16.0"' in pyproject))
static_checks.append(("requirements_lock_ruff_pin", re.search(r"(?m)^ruff==0\.16\.0$", requirements_lock) is not None))
static_checks.append(("pyproject_ruff_config", "[tool.ruff]" in pyproject and "[tool.ruff.lint]" in pyproject))
static_checks.append(("admin_dockerfile_node_pin", f"FROM node:{expected['node']}-slim AS build" in admin_dockerfile))
static_checks.append(("npm_engine_strict", npmrc == "engine-strict=true"))
static_checks.append(("gitignore_excludes_env", re.search(r"(?m)^\.env$", gitignore) is not None))

code, output = run_command(["docker", "exec", "agent_trading-app-1", "python3", "-m", "ruff", "--version"])
if code != 0:
    code, output = run_command(["python3", "-m", "ruff", "--version"])
static_checks.append(("ruff_executable", code == 0 and output.strip() == "ruff 0.16.0"))

try:
    package_json = json.loads((root / "admin_ui" / "package.json").read_text())
except Exception:
    package_json = {}
try:
    package_lock = json.loads((root / "admin_ui" / "package-lock.json").read_text())
except Exception:
    package_lock = {}

package_engines = package_json.get("engines", {})
lock_engines = package_lock.get("packages", {}).get("", {}).get("engines", {})
static_checks.append(("package_json_node_engine", package_engines.get("node") == expected["node"]))
static_checks.append(("package_json_npm_engine", package_engines.get("npm") == expected["npm"]))
static_checks.append(("package_lock_node_engine", lock_engines.get("node") == expected["node"]))
static_checks.append(("package_lock_npm_engine", lock_engines.get("npm") == expected["npm"]))

failed_static_checks = [name for name, ok in static_checks if not ok]

lock_checks = []
lock_checks.append(("requirements_lock_nonempty", (root / "requirements.lock").exists() and bool((root / "requirements.lock").read_text().strip())))
lock_checks.append(("package_lock_nonempty", (root / "admin_ui" / "package-lock.json").exists() and bool((root / "admin_ui" / "package-lock.json").read_text().strip())))
failed_lock_checks = [name for name, ok in lock_checks if not ok]

tracked_env_count = 0
code, output = run_command(["git", "ls-files", ".env"])
if code == 0 and output:
    tracked_env_count = len(output.splitlines())

env_example_keys = parse_env_keys(root / ".env.example")
env_file = root / ".env"
if env_file.exists():
    env_keys = parse_env_keys(env_file)
    advisory_missing_env_example_keys = sorted(env_example_keys - env_keys)
    env_file_status = "present-redacted"
else:
    advisory_missing_env_example_keys = sorted(env_example_keys)
    env_file_status = "missing"

metrics = {
    "required_file_missing_count": len(missing_files),
    "runtime_version_mismatch_count": len(runtime_mismatches),
    "static_pin_failed_count": len(failed_static_checks),
    "lockfile_failed_count": len(failed_lock_checks),
    "env_example_key_count": len(env_example_keys),
    "advisory_env_example_key_missing_count": len(advisory_missing_env_example_keys),
    "tracked_env_file_count": tracked_env_count,
}

passed = (
    metrics["required_file_missing_count"] == 0
    and metrics["runtime_version_mismatch_count"] == 0
    and metrics["static_pin_failed_count"] == 0
    and metrics["lockfile_failed_count"] == 0
    and metrics["tracked_env_file_count"] == 0
)

print(f"ACCEPT env: {'PASS' if passed else 'FAIL'}")
for key, value in metrics.items():
    print(f"- {key}={value}")
for name in ("python", "node", "npm", "postgres"):
    print(f"- {name}={runtime_versions.get(name, '<missing>')} source={runtime_sources.get(name, '<unknown>')}")
print(f"- env_file={env_file_status}")
print("- env_values=redacted")

if missing_files:
    print("DETAIL missing_files:")
    for path in missing_files:
        print(f"- {path.relative_to(root)}")

if runtime_mismatches:
    print("DETAIL runtime_version_mismatches:")
    for name, expected_version, actual_version, source in runtime_mismatches:
        print(f"- {name}: expected={expected_version} actual={actual_version} source={source}")

if failed_static_checks:
    print("DETAIL failed_static_checks:")
    for name in failed_static_checks:
        print(f"- {name}")

if failed_lock_checks:
    print("DETAIL failed_lock_checks:")
    for name in failed_lock_checks:
        print(f"- {name}")

if advisory_missing_env_example_keys:
    print("ADVISORY env_example_keys_missing_from_env:")
    for key in advisory_missing_env_example_keys:
        print(f"- {key}")

raise SystemExit(0 if passed else 1)
PY
}

accept_backend_file() {
  local target="${1:-}"
  require_arg "$target" "backend_file"
ACCEPT_BACKEND_TARGET="$target" ACCEPT_SAFE_TIMEOUT_SECONDS="$SAFE_TIMEOUT_SECONDS" python3 - <<'PY'
import ast
import os
import subprocess
from pathlib import Path

root = Path(os.environ["HARNESS_ROOT_DIR"])
target_raw = os.environ["ACCEPT_BACKEND_TARGET"]
safe_timeout = int(os.environ.get("ACCEPT_SAFE_TIMEOUT_SECONDS", "90"))

def run_command(command: list[str], timeout_seconds: int = safe_timeout) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + f"\nTIMEOUT after {timeout_seconds}s"
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return completed.returncode, completed.stdout.strip()

def python_command(args: list[str]) -> list[str]:
    code, names = run_command(["docker", "ps", "--format", "{{.Names}}"], timeout_seconds=10)
    if code == 0 and "agent_trading-app-1" in set(names.splitlines()):
        return ["docker", "exec", "-w", "/app", "agent_trading-app-1", "python3", *args]
    return ["python3", *args]

details: list[str] = []
resolved = (root / target_raw).resolve()
src_root = (root / "src" / "agent_trading").resolve()

valid_path = (
    str(resolved).startswith(str(src_root) + "/")
    and resolved.exists()
    and resolved.is_file()
    and resolved.suffix == ".py"
)

py_compile_passed = False
safe_test_candidates: list[Path] = []
unsafe_test_candidates: list[Path] = []
selected_test_candidates: list[Path] = []
tests_run_count = 0
test_failed_count = 0
dropped_test_candidate_count = 0
test_outputs: list[tuple[str, int, str]] = []
test_discovery_mode = "none"
matched_by_import_count = 0
no_test_override = os.environ.get("HARNESS_ALLOW_NO_TEST") == "1"

def is_unsafe_test_candidate(candidate: Path) -> bool:
    rel = candidate.relative_to(root).as_posix()
    return rel.startswith(("tests/smoke/", "tests/integration/", "tests/brokers/"))

def is_test_file(candidate: Path) -> bool:
    return (
        candidate.exists()
        and candidate.is_file()
        and candidate.suffix == ".py"
        and candidate.name != "conftest.py"
        and (candidate.name.startswith("test_") or candidate.name.endswith("_test.py"))
    )

def module_import_score(candidate: Path, module_name: str) -> int:
    try:
        text = candidate.read_text()
        tree = ast.parse(text)
    except Exception:
        return 0

    parent_module, _, leaf_name = module_name.rpartition(".")
    score = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    score += 4
                elif alias.name.startswith(f"{module_name}."):
                    score += 3
        elif isinstance(node, ast.ImportFrom):
            imported_from = node.module or ""
            if imported_from == module_name:
                score += 4 + len(node.names)
            elif imported_from.startswith(f"{module_name}."):
                score += 3
            elif imported_from == parent_module:
                for alias in node.names:
                    if alias.name == leaf_name:
                        score += 3
    if module_name in text:
        score += 1
    return score

def discover_import_graph_candidates(module_name: str) -> list[tuple[Path, int]]:
    matches: list[tuple[Path, int]] = []
    for candidate in sorted((root / "tests").rglob("*.py")):
        if not is_test_file(candidate):
            continue
        score = module_import_score(candidate, module_name)
        if score > 0:
            matches.append((candidate.resolve(), score))
    return sorted(matches, key=lambda item: (-item[1], item[0].relative_to(root).as_posix()))

def discover_stem_fallback_candidates(module_relative: Path, stem: str) -> list[Path]:
    direct_candidates = [
        root / "tests" / module_relative.parent / f"test_{stem}.py",
        root / "tests" / module_relative.parent / f"{stem}_test.py",
    ]
    candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in direct_candidates:
        candidate = candidate.resolve()
        if is_test_file(candidate) and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return candidates

if not valid_path:
    if not str(resolved).startswith(str(src_root) + "/"):
        details.append(f"invalid_path_scope={target_raw}")
    elif not resolved.exists():
        details.append(f"missing_file={target_raw}")
    elif resolved.suffix != ".py":
        details.append(f"not_python_file={target_raw}")
else:
    relative_target = resolved.relative_to(root).as_posix()
    code, output = run_command(python_command(["-m", "py_compile", relative_target]))
    py_compile_passed = code == 0
    if not py_compile_passed:
        details.append("py_compile_failed")
        if output:
            test_outputs.append(("py_compile", code, output))

    module_relative = resolved.relative_to(src_root)
    module_name = "agent_trading." + ".".join(module_relative.with_suffix("").parts)
    stem = resolved.stem
    import_candidates = discover_import_graph_candidates(module_name)
    matched_by_import_count = len(import_candidates)
    candidates = [candidate for candidate, _score in import_candidates]
    candidate_scores = {candidate: score for candidate, score in import_candidates}
    if candidates:
        test_discovery_mode = "import_graph"
    else:
        candidates = discover_stem_fallback_candidates(module_relative, stem)
        candidate_scores = {candidate: 1 for candidate in candidates}
        if candidates:
            test_discovery_mode = "stem_fallback"

    for candidate in candidates:
        if is_unsafe_test_candidate(candidate):
            unsafe_test_candidates.append(candidate)
        else:
            safe_test_candidates.append(candidate)

    max_safe_test_files = int(os.environ.get("ACCEPT_BACKEND_MAX_TEST_FILES", "3"))
    safe_test_candidates = sorted(
        safe_test_candidates,
        key=lambda candidate: (-candidate_scores.get(candidate, 0), candidate.relative_to(root).as_posix()),
    )
    selected_test_candidates = safe_test_candidates[:max_safe_test_files]
    dropped_test_candidate_count = max(len(safe_test_candidates) - len(selected_test_candidates), 0)
    if not safe_test_candidates and not no_test_override:
        details.append("no_safe_test_candidate_found")
    for candidate in selected_test_candidates:
        rel = candidate.relative_to(root).as_posix()
        code, output = run_command(python_command(["-m", "pytest", rel, "-v"]))
        tests_run_count += 1
        if code != 0:
            test_failed_count += 1
            test_outputs.append((rel, code, output))

metrics = {
    "valid_backend_file": 1 if valid_path else 0,
    "py_compile_passed": 1 if py_compile_passed else 0,
    "safe_test_candidate_count": len(safe_test_candidates),
    "unsafe_test_candidate_count": len(unsafe_test_candidates),
    "selected_test_candidate_count": len(selected_test_candidates),
    "dropped_test_candidate_count": dropped_test_candidate_count,
    "matched_by_import_count": matched_by_import_count,
    "tests_run_count": tests_run_count,
    "test_failed_count": test_failed_count,
    "no_test_override": 1 if no_test_override else 0,
}

passed = (
    metrics["valid_backend_file"] == 1
    and metrics["py_compile_passed"] == 1
    and (metrics["safe_test_candidate_count"] > 0 or no_test_override)
    and metrics["test_failed_count"] == 0
)

print(f"ACCEPT backend-file: {'PASS' if passed else 'FAIL'}")
print(f"- file={target_raw}")
print(f"- test_discovery_mode={test_discovery_mode}")
for key, value in metrics.items():
    print(f"- {key}={value}")

if selected_test_candidates:
    print("DETAIL selected_test_candidates:")
    for candidate in selected_test_candidates:
        print(f"- {candidate.relative_to(root).as_posix()}")

if safe_test_candidates:
    print("DETAIL safe_test_candidates:")
    for candidate in safe_test_candidates:
        print(f"- {candidate.relative_to(root).as_posix()}")
else:
    print("DETAIL no_safe_test_candidate_found=1")

if dropped_test_candidate_count:
    print("DETAIL dropped_test_candidates:")
    for candidate in safe_test_candidates[len(selected_test_candidates):]:
        print(f"- {candidate.relative_to(root).as_posix()}")

if unsafe_test_candidates:
    print("ADVISORY unsafe_test_candidates_not_run:")
    for candidate in unsafe_test_candidates:
        print(f"- {candidate.relative_to(root).as_posix()}")

if details:
    print("DETAIL failed_checks:")
    for detail in details:
        print(f"- {detail}")

if test_outputs:
    print("DETAIL command_failures:")
    for label, code, output in test_outputs:
        print(f"- {label}: exit_code={code}")
        if output:
            for line in output.splitlines()[-30:]:
                print(f"  {line}")

raise SystemExit(0 if passed else 1)
PY
}

accept_backend_runtime() {
  ACCEPT_SAFE_TIMEOUT_SECONDS="$SAFE_TIMEOUT_SECONDS" python3 - <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path

root = Path(os.environ["HARNESS_ROOT_DIR"])
safe_timeout = int(os.environ.get("ACCEPT_SAFE_TIMEOUT_SECONDS", "90"))

def read_first_line(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text().splitlines()[0].strip()

def run_command(command: list[str], timeout_seconds: int = safe_timeout) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root / 'src'}:{env.get('PYTHONPATH', '')}".rstrip(":")
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + f"\nTIMEOUT after {timeout_seconds}s"
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return completed.returncode, completed.stdout.strip()

def python_command(args: list[str]) -> tuple[list[str], str]:
    code, names = run_command(["docker", "ps", "--format", "{{.Names}}"], timeout_seconds=10)
    if code == 0 and "agent_trading-app-1" in set(names.splitlines()):
        return (
            [
                "docker",
                "exec",
                "-e",
                "PYTHONPATH=/app/src",
                "-w",
                "/app",
                "agent_trading-app-1",
                "python3",
                *args,
            ],
            "agent_trading-app-1",
        )
    return (["python3", *args], "host-python3")

def parse_env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            keys.add(key)
    return keys

expected_python = read_first_line(root / ".python-version")
required_files = [
    root / "src" / "AGENTS.md",
    root / "src" / "agent_trading" / "__init__.py",
    root / "src" / "agent_trading" / "api" / "app.py",
    root / "src" / "agent_trading" / "config" / "settings.py",
    root / "src" / "agent_trading" / "runtime" / "bootstrap.py",
    root / "src" / "agent_trading" / "db" / "connection.py",
    root / "pyproject.toml",
    root / "Dockerfile",
    root / "requirements.lock",
    root / ".python-version",
    root / ".env.example",
]
missing_files = [path for path in required_files if not path.exists()]

pyproject = (root / "pyproject.toml").read_text() if (root / "pyproject.toml").exists() else ""
dockerfile = (root / "Dockerfile").read_text() if (root / "Dockerfile").exists() else ""
requirements_lock = (root / "requirements.lock").read_text() if (root / "requirements.lock").exists() else ""
env_example_keys = parse_env_keys(root / ".env.example")
required_env_example_keys = {
    "INSPECTION_API_TOKEN",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
}

static_checks = [
    ("pyproject_python_range", 'requires-python = ">=3.14,<3.15"' in pyproject),
    ("dockerfile_python_pin", bool(expected_python) and f"FROM python:{expected_python}-slim" in dockerfile),
    ("dockerfile_uses_requirements_lock", "requirements.lock" in dockerfile and "--constraint requirements.lock" in dockerfile),
    ("pyproject_dev_ruff_pin", '"ruff==0.16.0"' in pyproject),
    ("requirements_lock_ruff_pin", re.search(r"(?m)^ruff==0\.16\.0$", requirements_lock) is not None),
    ("pyproject_ruff_config", "[tool.ruff]" in pyproject and "[tool.ruff.lint]" in pyproject),
    ("env_example_backend_keys", required_env_example_keys.issubset(env_example_keys)),
]
ruff_command, _ruff_source = python_command(["-m", "ruff", "--version"])
ruff_code, ruff_output = run_command(ruff_command)
static_checks.append(("ruff_executable", ruff_code == 0 and ruff_output.strip() == "ruff 0.16.0"))
failed_static_checks = [name for name, ok in static_checks if not ok]
missing_env_example_keys = sorted(required_env_example_keys - env_example_keys)

runtime_probe_code = r'''
import importlib
import json
import os
import platform

for key in (
    "API_RUNTIME_MODE",
    "INSPECTION_API_TOKEN",
    "INSPECTION_API_ROLE",
    "CORS_ALLOWED_ORIGINS",
    "KIS_APP_KEY",
    "KIS_API_KEY",
    "KIS_APP_SECRET",
    "KIS_API_SECRET",
    "KIS_LIVE_INFO_APP_KEY",
    "KIS_LIVE_INFO_APP_SECRET",
    "KIS_REALTIME_QUOTE_APP_KEY",
    "KIS_REALTIME_QUOTE_APP_SECRET",
):
    os.environ.pop(key, None)

os.environ["API_RUNTIME_MODE"] = "in_memory"
os.environ["INSPECTION_API_TOKEN"] = "harness-redacted-token"
os.environ["INSPECTION_API_ROLE"] = "viewer"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["LLM_PROVIDER"] = "deepseek"
os.environ["DEEPSEEK_API_KEY"] = ""

modules = [
    "agent_trading",
    "agent_trading.api.app",
    "agent_trading.config.settings",
    "agent_trading.runtime.bootstrap",
    "agent_trading.db.connection",
    "agent_trading.repositories.bootstrap",
    "agent_trading.repositories.postgres.bootstrap",
    "agent_trading.services.decision_orchestrator",
]

import_failures = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:
        import_failures.append({"module": name, "error": f"{type(exc).__name__}: {exc}"})

factory_checks = {}
factory_error = ""
route_count = 0
required_route_hits = {}
try:
    app_module = importlib.import_module("agent_trading.api.app")
    factory = getattr(app_module, "create_app_from_env")
    app = factory()
    routes = {getattr(route, "path", "") for route in app.routes}
    route_types = [type(route).__name__ for route in app.routes]
    route_count = len(app.routes)
    required_route_hits = {
        "/openapi.json": "/openapi.json" in routes,
        "/docs": "/docs" in routes,
        "_IncludedRouter": "_IncludedRouter" in route_types,
    }
    factory_checks = {
        "factory_callable": callable(factory),
        "app_has_routes": route_count > 0,
        "required_routes_present": all(required_route_hits.values()),
    }
except Exception as exc:
    factory_error = f"{type(exc).__name__}: {exc}"

print(json.dumps({
    "python": platform.python_version(),
    "import_failures": import_failures,
    "factory_checks": factory_checks,
    "factory_error": factory_error,
    "route_count": route_count,
    "required_route_hits": required_route_hits,
}, ensure_ascii=False, sort_keys=True))
'''

command, runtime_source = python_command(["-c", runtime_probe_code])
probe_code, probe_output = run_command(command)
probe_payload: dict[str, object] = {}
probe_parse_failed = False
if probe_code == 0:
    try:
        probe_payload = json.loads(probe_output.splitlines()[-1])
    except Exception:
        probe_parse_failed = True

runtime_python = str(probe_payload.get("python", "")) if probe_payload else ""
runtime_version_mismatches = []
if runtime_python != expected_python:
    runtime_version_mismatches.append(("python", expected_python or "<missing>", runtime_python or "<missing>", runtime_source))

import_failures = probe_payload.get("import_failures", []) if isinstance(probe_payload, dict) else []
factory_checks = probe_payload.get("factory_checks", {}) if isinstance(probe_payload, dict) else {}
factory_error = str(probe_payload.get("factory_error", "")) if isinstance(probe_payload, dict) else ""
failed_factory_checks = [
    name for name in ("factory_callable", "app_has_routes", "required_routes_present")
    if not isinstance(factory_checks, dict) or factory_checks.get(name) is not True
]

metrics = {
    "required_file_missing_count": len(missing_files),
    "static_contract_failed_count": len(failed_static_checks),
    "runtime_version_mismatch_count": len(runtime_version_mismatches),
    "runtime_probe_failed_count": 0 if probe_code == 0 and not probe_parse_failed else 1,
    "import_failed_count": len(import_failures) if isinstance(import_failures, list) else 1,
    "factory_check_failed_count": len(failed_factory_checks),
    "env_example_missing_key_count": len(missing_env_example_keys),
}

passed = all(value == 0 for value in metrics.values())
print(f"ACCEPT backend-runtime: {'PASS' if passed else 'FAIL'}")
for key, value in metrics.items():
    print(f"- {key}={value}")
print(f"- python={runtime_python or '<missing>'} source={runtime_source}")
if isinstance(probe_payload, dict):
    print(f"- route_count={probe_payload.get('route_count', '<missing>')}")
print("- app_server_started=0")
print("- database_connection_run=0")
print("- external_network_run=0")
print("- full_test_run=0")

if missing_files:
    print("DETAIL missing_files:")
    for path in missing_files:
        print(f"- {path.relative_to(root)}")
if failed_static_checks:
    print("DETAIL failed_static_checks:")
    for name in failed_static_checks:
        print(f"- {name}")
if missing_env_example_keys:
    print("DETAIL missing_env_example_keys:")
    for key in missing_env_example_keys:
        print(f"- {key}")
if runtime_version_mismatches:
    print("DETAIL runtime_version_mismatches:")
    for name, expected, actual, source in runtime_version_mismatches:
        print(f"- {name}: expected={expected} actual={actual} source={source}")
if probe_code != 0 or probe_parse_failed:
    print("DETAIL runtime_probe_failure:")
    print(f"- exit_code={probe_code}")
    for line in probe_output.splitlines()[-30:]:
        print(f"  {line}")
if isinstance(import_failures, list) and import_failures:
    print("DETAIL import_failures:")
    for item in import_failures:
        if isinstance(item, dict):
            print(f"- {item.get('module')}: {item.get('error')}")
if failed_factory_checks:
    print("DETAIL failed_factory_checks:")
    for name in failed_factory_checks:
        print(f"- {name}")
if factory_error:
    print("DETAIL factory_error:")
    print(f"- {factory_error}")

raise SystemExit(0 if passed else 1)
PY
}

accept_db_structure() {
  timeout "$SAFE_TIMEOUT_SECONDS" python3 scripts/harness/check_db_structure.py
}

accept_architecture() {
  timeout "$SAFE_TIMEOUT_SECONDS" python3 scripts/harness/check_architecture.py
}

parse_ruff_found_count() {
  local output_file="$1"
  local found
  found="$(grep -Eo 'Found [0-9]+ errors?' "$output_file" | tail -n 1 | grep -Eo '[0-9]+' || true)"
  echo "${found:-0}"
}

accept_style() {
  local ruff_default_output
  local ruff_f_output
  local ruff_default_exit_code=0
  local ruff_f_exit_code=0
  local ruff_default_violation_count=0
  local ruff_f_violation_count=0
  local ruff_f_baseline="${HARNESS_STYLE_RUFF_F_BASELINE:-0}"
  local ruff_f_excess_count=0
  local failed_count=0

  ruff_default_output="$(mktemp)"
  ruff_f_output="$(mktemp)"

  if run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m ruff check src/agent_trading >"$ruff_default_output" 2>&1; then
    ruff_default_exit_code=0
  else
    ruff_default_exit_code=$?
    failed_count=$((failed_count + 1))
  fi
  ruff_default_violation_count="$(parse_ruff_found_count "$ruff_default_output")"

  if run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m ruff check --select F src/agent_trading >"$ruff_f_output" 2>&1; then
    ruff_f_exit_code=0
  else
    ruff_f_exit_code=$?
  fi
  ruff_f_violation_count="$(parse_ruff_found_count "$ruff_f_output")"

  if (( ruff_f_violation_count > ruff_f_baseline )); then
    ruff_f_excess_count=$((ruff_f_violation_count - ruff_f_baseline))
    failed_count=$((failed_count + 1))
  fi

  if [[ "$failed_count" -eq 0 ]]; then
    echo "ACCEPT style: PASS"
  else
    echo "ACCEPT style: FAIL"
  fi
  echo "- ruff_default_exit_code=$ruff_default_exit_code"
  echo "- ruff_default_violation_count=$ruff_default_violation_count"
  echo "- ruff_f_exit_code=$ruff_f_exit_code"
  echo "- ruff_f_violation_count=$ruff_f_violation_count"
  echo "- ruff_f_baseline=$ruff_f_baseline"
  echo "- ruff_f_baseline_enforced=1"
  echo "- ruff_f_excess_count=$ruff_f_excess_count"
  echo "- database_connection_run=0"
  echo "- external_network_run=0"
  echo "- full_test_run=0"
  if [[ "$ruff_default_exit_code" -ne 0 ]]; then
    echo "DETAIL ruff_default_tail:"
    tail -n 20 "$ruff_default_output"
  fi
  if [[ "$ruff_f_excess_count" -gt 0 ]]; then
    echo "DETAIL ruff_f_tail:"
    tail -n 40 "$ruff_f_output"
  fi

  rm -f "$ruff_default_output" "$ruff_f_output"
  [[ "$failed_count" -eq 0 ]]
}

accept_no_bypass() {
  timeout "$SAFE_TIMEOUT_SECONDS" python3 scripts/harness/check_no_bypass.py
}

accept_frontend() {
  ACCEPT_SAFE_TIMEOUT_SECONDS="$SAFE_TIMEOUT_SECONDS" python3 - <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path

root = Path(os.environ["HARNESS_ROOT_DIR"])
admin_root = root / "admin_ui"
safe_timeout = int(os.environ.get("ACCEPT_SAFE_TIMEOUT_SECONDS", "90"))

def read_first_line(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text().splitlines()[0].strip()

def run_command(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=safe_timeout,
            check=False,
        )
    except Exception:
        return 1, ""
    return completed.returncode, completed.stdout.strip()

def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

expected_node = read_first_line(admin_root / ".nvmrc")
expected_npm = read_first_line(admin_root / ".npm-version")

required_files = [
    admin_root / "AGENTS.md",
    admin_root / "Dockerfile",
    admin_root / "package.json",
    admin_root / "package-lock.json",
    admin_root / ".nvmrc",
    admin_root / ".npm-version",
    admin_root / ".npmrc",
    admin_root / "vite.config.ts",
    admin_root / "nginx.frontend.conf",
    admin_root / "src" / "api" / "client.ts",
    admin_root / "src" / "types" / "api.ts",
    admin_root / "src" / "__tests__" / "setup.ts",
]
missing_files = [path for path in required_files if not path.exists()]

package_json = read_json(admin_root / "package.json")
package_lock = read_json(admin_root / "package-lock.json")
package_engines = package_json.get("engines", {})
lock_root = package_lock.get("packages", {}).get("", {})
lock_engines = lock_root.get("engines", {})
scripts = package_json.get("scripts", {})

dockerfile = (admin_root / "Dockerfile").read_text() if (admin_root / "Dockerfile").exists() else ""
npmrc = (admin_root / ".npmrc").read_text().strip() if (admin_root / ".npmrc").exists() else ""
vite_config = (admin_root / "vite.config.ts").read_text() if (admin_root / "vite.config.ts").exists() else ""
api_client = (admin_root / "src" / "api" / "client.ts").read_text() if (admin_root / "src" / "api" / "client.ts").exists() else ""
agents = (admin_root / "AGENTS.md").read_text() if (admin_root / "AGENTS.md").exists() else ""

static_checks = [
    ("package_json_node_engine", package_engines.get("node") == expected_node),
    ("package_json_npm_engine", package_engines.get("npm") == expected_npm),
    ("package_lock_node_engine", lock_engines.get("node") == expected_node),
    ("package_lock_npm_engine", lock_engines.get("npm") == expected_npm),
    ("npm_engine_strict", npmrc == "engine-strict=true"),
    ("dockerfile_node_pin", f"FROM node:{expected_node}-slim AS build" in dockerfile),
    ("dockerfile_uses_npm_ci", "RUN npm ci" in dockerfile),
    ("vite_uses_jsdom", 'environment: "jsdom"' in vite_config or "environment: 'jsdom'" in vite_config),
    ("vite_has_test_setup", "setupFiles" in vite_config and "setup.ts" in vite_config),
    ("api_client_exists", bool(api_client.strip())),
    ("admin_agents_load_limit", "전체 테스트와 전체 빌드 실행을 기본 금지" in agents),
    ("admin_agents_state_display_policy", "loading, empty, error, stale" in agents),
]

dependencies = package_json.get("dependencies", {})
dev_dependencies = package_json.get("devDependencies", {})
lock_dependencies = lock_root.get("dependencies", {})
lock_dev_dependencies = lock_root.get("devDependencies", {})
dependency_drift = []
for name, version in sorted(dependencies.items()):
    if lock_dependencies.get(name) != version:
        dependency_drift.append(("dependencies", name, version, lock_dependencies.get(name, "<missing>")))
for name, version in sorted(dev_dependencies.items()):
    if lock_dev_dependencies.get(name) != version:
        dependency_drift.append(("devDependencies", name, version, lock_dev_dependencies.get(name, "<missing>")))

test_files = sorted((admin_root / "src" / "__tests__").glob("*.test.*")) if (admin_root / "src" / "__tests__").exists() else []
component_files = sorted((admin_root / "src" / "components").rglob("*.tsx")) if (admin_root / "src" / "components").exists() else []
common_state_components = [
    admin_root / "src" / "components" / "common" / "ErrorBanner.tsx",
    admin_root / "src" / "components" / "common" / "LoadingSpinner.tsx",
    admin_root / "src" / "components" / "common" / "StatusBadge.tsx",
    admin_root / "src" / "components" / "common" / "WarningBanner.tsx",
]
missing_state_components = [path for path in common_state_components if not path.exists()]

runtime_versions: dict[str, str] = {}
runtime_sources: dict[str, str] = {}
pinned_node_image = f"node:{expected_node}-slim" if expected_node else "node:20-slim"

code, output = run_command(["docker", "run", "--rm", pinned_node_image, "node", "--version"])
if code == 0 and output:
    runtime_versions["node"] = output.removeprefix("v")
    runtime_sources["node"] = pinned_node_image
else:
    code, output = run_command(["node", "--version"])
    runtime_versions["node"] = output.removeprefix("v") if code == 0 else ""
    runtime_sources["node"] = "host-node"

code, output = run_command(["docker", "run", "--rm", pinned_node_image, "npm", "--version"])
if code == 0 and output:
    runtime_versions["npm"] = output
    runtime_sources["npm"] = pinned_node_image
else:
    code, output = run_command(["npm", "--version"])
    runtime_versions["npm"] = output if code == 0 else ""
    runtime_sources["npm"] = "host-npm"

runtime_mismatches = []
if runtime_versions.get("node") != expected_node:
    runtime_mismatches.append(("node", expected_node or "<missing>", runtime_versions.get("node") or "<missing>", runtime_sources.get("node", "<unknown>")))
if runtime_versions.get("npm") != expected_npm:
    runtime_mismatches.append(("npm", expected_npm or "<missing>", runtime_versions.get("npm") or "<missing>", runtime_sources.get("npm", "<unknown>")))

failed_static_checks = [name for name, ok in static_checks if not ok]

metrics = {
    "required_file_missing_count": len(missing_files),
    "runtime_version_mismatch_count": len(runtime_mismatches),
    "static_contract_failed_count": len(failed_static_checks),
    "dependency_drift_count": len(dependency_drift),
    "test_file_count": len(test_files),
    "component_file_count": len(component_files),
    "state_component_missing_count": len(missing_state_components),
}

passed = (
    metrics["required_file_missing_count"] == 0
    and metrics["runtime_version_mismatch_count"] == 0
    and metrics["static_contract_failed_count"] == 0
    and metrics["dependency_drift_count"] == 0
    and metrics["test_file_count"] > 0
    and metrics["component_file_count"] > 0
    and metrics["state_component_missing_count"] == 0
)

print(f"ACCEPT frontend: {'PASS' if passed else 'FAIL'}")
for key, value in metrics.items():
    print(f"- {key}={value}")
print(f"- node={runtime_versions.get('node', '<missing>')} source={runtime_sources.get('node', '<unknown>')}")
print(f"- npm={runtime_versions.get('npm', '<missing>')} source={runtime_sources.get('npm', '<unknown>')}")
print("- full_build_run=0")
print("- full_test_run=0")

if missing_files:
    print("DETAIL missing_files:")
    for path in missing_files:
        print(f"- {path.relative_to(root)}")

if runtime_mismatches:
    print("DETAIL runtime_version_mismatches:")
    for name, expected, actual, source in runtime_mismatches:
        print(f"- {name}: expected={expected} actual={actual} source={source}")

if failed_static_checks:
    print("DETAIL failed_static_checks:")
    for name in failed_static_checks:
        print(f"- {name}")

if dependency_drift:
    print("DETAIL dependency_drift:")
    for group, name, package_value, lock_value in dependency_drift:
        print(f"- {group}.{name}: package_json={package_value} package_lock={lock_value}")

if missing_state_components:
    print("DETAIL missing_state_components:")
    for path in missing_state_components:
        print(f"- {path.relative_to(root)}")

raise SystemExit(0 if passed else 1)
PY
}

accept_ops_report() {
  local summary_json="${1:-}"
  require_arg "$summary_json" "summary_json"
  python3 - "$summary_json" <<'PY'
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

root = Path(os.environ["HARNESS_ROOT_DIR"])
raw_arg = sys.argv[1]

class InputResolutionError(Exception):
    pass

def resolve_input(raw: str) -> tuple[str, str]:
    if raw.lstrip().startswith(("{", "[")):
        return raw, "<inline-json>"
    candidate = (root / raw).resolve() if not raw.startswith("/") else Path(raw).resolve()
    if str(candidate).startswith(str(root) + "/") and candidate.is_file():
        return candidate.read_text(), str(candidate.relative_to(root))
    if raw.startswith("/") or "/" in raw or raw.endswith(".json"):
        raise InputResolutionError(f"summary_json 파일을 찾을 수 없거나 프로젝트 밖 경로입니다: {raw}")
    raise InputResolutionError("inline JSON은 '{' 또는 '['로 시작해야 합니다.")

def load_payload(raw: str) -> dict[str, Any]:
    try:
        text, source = resolve_input(raw)
    except InputResolutionError as exc:
        print("ACCEPT ops-report: FAIL")
        print("- input_resolution_error_count=1")
        print(f"DETAIL input_resolution_error: {exc}")
        raise SystemExit(1) from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        print("ACCEPT ops-report: FAIL")
        print("- json_parse_error_count=1")
        print(f"DETAIL json_parse_error: source={source} line={exc.lineno} column={exc.colno}")
        raise SystemExit(1) from exc
    if not isinstance(parsed, dict):
        print("ACCEPT ops-report: FAIL")
        print("- json_object_error_count=1")
        print(f"DETAIL json_object_error: source={source}")
        raise SystemExit(1)
    for wrapper_key in ("summary_json", "operations_day_summary_json"):
        wrapped = parsed.get(wrapper_key)
        if isinstance(wrapped, dict):
            return wrapped
    return parsed

def get_path(payload: dict[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value

def is_int_like(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)

def is_non_trading_session(payload: dict[str, Any]) -> bool:
    is_trading_day = payload.get("is_trading_day")
    if is_trading_day is False:
        return True
    session_reason = str(payload.get("session_reason") or "").lower()
    return any(marker in session_reason for marker in ("non-trading", "non trading", "holiday", "주말", "휴장"))

def collect_secret_key_hits(value: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    secret_pattern = re.compile(r"(secret|password|passwd|authorization|approval_key|access_token|refresh_token|bearer_token|appkey|appsecret|api_key|client_secret)", re.I)
    value_patterns = [
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I),
        re.compile(r"\b(?:appkey|appsecret|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[A-Za-z0-9._~+/=-]{8,}", re.I),
        re.compile(r"\bPS[A-Za-z0-9]{12,}\b"),
    ]
    if isinstance(value, dict):
        for key, nested in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if secret_pattern.search(str(key)) and nested not in (None, "", [], {}):
                hits.append(child_path)
            hits.extend(collect_secret_key_hits(nested, child_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            hits.extend(collect_secret_key_hits(nested, f"{path}[{index}]"))
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in value_patterns):
            hits.append(path or "<root>")
    return hits

payload = load_payload(raw_arg)
session_profile = "non_trading_day" if is_non_trading_session(payload) else "decision_loop"
allowed_failed_count = int(os.environ.get("HARNESS_OPS_ALLOWED_FAILED_COUNT", "0"))
allowed_timed_out_count = int(os.environ.get("HARNESS_OPS_ALLOWED_TIMED_OUT_COUNT", "0"))

required_top_level_paths = [
    "command_results_count",
    "ok_count",
    "failed_count",
    "timed_out_count",
    "command_health",
]
if session_profile == "decision_loop":
    required_top_level_paths.extend(["decision_loop", "command_health.decision_loop"])
missing_required_paths = [
    dotted_path for dotted_path in required_top_level_paths
    if get_path(payload, dotted_path) is None
]

counter_paths = [
    "command_results_count",
    "ok_count",
    "failed_count",
    "timed_out_count",
]
counter_type_failures = [
    dotted_path for dotted_path in counter_paths
    if not is_int_like(get_path(payload, dotted_path))
]

counter_inconsistencies: list[str] = []
command_results_count = get_path(payload, "command_results_count")
ok_count = get_path(payload, "ok_count")
failed_count = get_path(payload, "failed_count")
timed_out_count = get_path(payload, "timed_out_count")
if all(is_int_like(value) for value in (command_results_count, ok_count, failed_count, timed_out_count)):
    if ok_count + failed_count != command_results_count:
        counter_inconsistencies.append("ok_count+failed_count!=command_results_count")
    if timed_out_count > command_results_count:
        counter_inconsistencies.append("timed_out_count>command_results_count")
    if command_results_count <= 0 and session_profile != "non_trading_day":
        counter_inconsistencies.append("command_results_count<=0")

command_failure_policy_failures: list[str] = []
if is_int_like(failed_count) and failed_count > allowed_failed_count:
    command_failure_policy_failures.append(f"failed_count>{allowed_failed_count}")
if is_int_like(timed_out_count) and timed_out_count > allowed_timed_out_count:
    command_failure_policy_failures.append(f"timed_out_count>{allowed_timed_out_count}")

decision_loop = get_path(payload, "decision_loop")
command_health_decision_loop = get_path(payload, "command_health.decision_loop")
decision_metrics = decision_loop.get("metrics") if isinstance(decision_loop, dict) else None
health_metrics = command_health_decision_loop.get("last_metrics") if isinstance(command_health_decision_loop, dict) else None

required_decision_metric_keys = [
    "universe_symbol_count",
    "processed_symbol_count",
    "held_position_count",
    "held_position_processed_count",
]

decision_metric_failures: list[str] = []
if session_profile == "decision_loop":
    for metric_source_name, metrics in (
        ("decision_loop.metrics", decision_metrics),
        ("command_health.decision_loop.last_metrics", health_metrics),
    ):
        if not isinstance(metrics, dict):
            decision_metric_failures.append(metric_source_name)
            continue
        for key in required_decision_metric_keys:
            if not is_int_like(metrics.get(key)):
                decision_metric_failures.append(f"{metric_source_name}.{key}")

coverage_failures: list[str] = []
if isinstance(decision_metrics, dict):
    universe_symbol_count = decision_metrics.get("universe_symbol_count")
    processed_symbol_count = decision_metrics.get("processed_symbol_count")
    held_position_count = decision_metrics.get("held_position_count")
    held_position_processed_count = decision_metrics.get("held_position_processed_count")
    if all(is_int_like(value) for value in (universe_symbol_count, processed_symbol_count)):
        if processed_symbol_count > universe_symbol_count:
            coverage_failures.append("processed_symbol_count>universe_symbol_count")
        if universe_symbol_count > 0 and processed_symbol_count <= 0:
            coverage_failures.append("universe_symbol_count>0 but processed_symbol_count<=0")
    if all(is_int_like(value) for value in (held_position_count, held_position_processed_count)):
        if held_position_processed_count > held_position_count:
            coverage_failures.append("held_position_processed_count>held_position_count")
        if held_position_count > 0 and held_position_processed_count <= 0:
            coverage_failures.append("held_position_count>0 but held_position_processed_count<=0")

health_failures: list[str] = []
if session_profile == "non_trading_day":
    pass
elif isinstance(command_health_decision_loop, dict):
    count = command_health_decision_loop.get("count")
    last_ok = command_health_decision_loop.get("last_ok")
    timed_out = command_health_decision_loop.get("timed_out_count")
    if not is_int_like(count) or count <= 0:
        health_failures.append("command_health.decision_loop.count<=0")
    if last_ok is not True:
        health_failures.append("command_health.decision_loop.last_ok!=true")
    if is_int_like(timed_out) and timed_out > 0:
        health_failures.append("command_health.decision_loop.timed_out_count>0")
else:
    health_failures.append("command_health.decision_loop")

secret_key_hits = collect_secret_key_hits(payload)

metrics = {
    "required_path_missing_count": len(missing_required_paths),
    "counter_type_failed_count": len(counter_type_failures),
    "counter_inconsistency_count": len(counter_inconsistencies),
    "command_failure_policy_failed_count": len(command_failure_policy_failures),
    "decision_metric_missing_count": len(decision_metric_failures),
    "decision_coverage_failed_count": len(coverage_failures),
    "decision_health_failed_count": len(health_failures),
    "secret_key_hit_count": len(secret_key_hits),
}

passed = all(value == 0 for value in metrics.values())
print(f"ACCEPT ops-report: {'PASS' if passed else 'FAIL'}")
print(f"- session_profile={session_profile}")
for key, value in metrics.items():
    print(f"- {key}={value}")
print(f"- allowed_failed_count={allowed_failed_count}")
print(f"- allowed_timed_out_count={allowed_timed_out_count}")
if isinstance(decision_metrics, dict):
    for key in required_decision_metric_keys:
        print(f"- {key}={decision_metrics.get(key, '<missing>')}")
print("- full_test_run=0")
print("- external_network_run=0")

if missing_required_paths:
    print("DETAIL missing_required_paths:")
    for dotted_path in missing_required_paths:
        print(f"- {dotted_path}")
if counter_type_failures:
    print("DETAIL counter_type_failures:")
    for dotted_path in counter_type_failures:
        print(f"- {dotted_path}")
if counter_inconsistencies:
    print("DETAIL counter_inconsistencies:")
    for item in counter_inconsistencies:
        print(f"- {item}")
if command_failure_policy_failures:
    print("DETAIL command_failure_policy_failures:")
    for item in command_failure_policy_failures:
        print(f"- {item}")
if decision_metric_failures:
    print("DETAIL decision_metric_failures:")
    for item in decision_metric_failures:
        print(f"- {item}")
if coverage_failures:
    print("DETAIL coverage_failures:")
    for item in coverage_failures:
        print(f"- {item}")
if health_failures:
    print("DETAIL health_failures:")
    for item in health_failures:
        print(f"- {item}")
if secret_key_hits:
    print("DETAIL secret_key_hits:")
    for item in secret_key_hits:
        print(f"- {item}")

raise SystemExit(0 if passed else 1)
PY
}

dump_ops_report() {
  local target_date="${1:-}"
  require_ops_dump_allowed
  TARGET_DATE="$target_date" ACCEPT_SAFE_TIMEOUT_SECONDS="$SAFE_TIMEOUT_SECONDS" python3 - <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

root = Path(os.environ["HARNESS_ROOT_DIR"])
target_date = os.environ.get("TARGET_DATE", "").strip()
safe_timeout = int(os.environ.get("ACCEPT_SAFE_TIMEOUT_SECONDS", "90"))
output_dir = root / "tmp" / "harness" / "ops-report"

def fail(message: str) -> None:
    print("DUMP ops-report: FAIL")
    print(f"DETAIL dump_error: {message}")
    raise SystemExit(1)

def run_command(command: list[str], timeout_seconds: int = safe_timeout) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + f"\nTIMEOUT after {timeout_seconds}s"
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return completed.returncode, completed.stdout.strip()

def collect_secret_hits(value: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    key_pattern = re.compile(r"(secret|password|passwd|authorization|approval_key|access_token|refresh_token|bearer_token|appkey|appsecret|api_key|client_secret)", re.I)
    value_patterns = [
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I),
        re.compile(r"\b(?:appkey|appsecret|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[A-Za-z0-9._~+/=-]{8,}", re.I),
        re.compile(r"\bPS[A-Za-z0-9]{12,}\b"),
    ]
    if isinstance(value, dict):
        for key, nested in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key_pattern.search(str(key)) and nested not in (None, "", [], {}):
                hits.append(child_path)
            hits.extend(collect_secret_hits(nested, child_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            hits.extend(collect_secret_hits(nested, f"{path}[{index}]"))
    elif isinstance(value, str) and any(pattern.search(value) for pattern in value_patterns):
        hits.append(path or "<root>")
    return hits

if target_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target_date):
    fail("날짜는 YYYY-MM-DD 형식이어야 합니다.")

code, names = run_command(["docker", "ps", "--format", "{{.Names}}"], timeout_seconds=10)
if code != 0 or "trading_db" not in set(names.splitlines()):
    fail("trading_db 컨테이너가 실행 중이어야 합니다.")

if target_date:
    where_clause = f"WHERE run_date = DATE '{target_date}'"
    output_name = f"ops-report-{target_date}.json"
else:
    where_clause = ""
    output_name = "ops-report-latest.json"

sql = f"""
WITH target AS (
  SELECT run_date, is_trading_day, scheduler_status, session_source, market_phase, summary_json
  FROM trading.operations_day_runs
  {where_clause}
  ORDER BY COALESCE(last_heartbeat_at, updated_at, created_at) DESC NULLS LAST
  LIMIT 1
)
SELECT (
  jsonb_build_object(
    'run_date', run_date,
    'is_trading_day', is_trading_day,
    'scheduler_status', scheduler_status,
    'session_source', session_source,
    'market_phase', market_phase
  ) || COALESCE(summary_json, '{{}}'::jsonb)
)::text
FROM target;
"""

code, output = run_command([
    "docker",
    "exec",
    "trading_db",
    "psql",
    "-U",
    "trading",
    "-d",
    "trading",
    "-tA",
    "-c",
    sql,
])
if code != 0:
    fail(f"operations_day_runs 조회 실패: exit_code={code}")
if not output:
    fail("해당 operations_day_runs row가 없습니다.")

try:
    payload = json.loads(output.splitlines()[-1])
except json.JSONDecodeError as exc:
    fail(f"summary_json 파싱 실패: line={exc.lineno} column={exc.colno}")
if not isinstance(payload, dict):
    fail("덤프 payload가 JSON object가 아닙니다.")

secret_hits = collect_secret_hits(payload)
if secret_hits:
    print("DUMP ops-report: FAIL")
    print(f"- payload_secret_hit_count={len(secret_hits)}")
    print("DETAIL secret_key_hits:")
    for item in secret_hits:
        print(f"- {item}")
    raise SystemExit(1)

output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / output_name
output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

print("DUMP ops-report: PASS")
print(f"- output_file={output_path.relative_to(root).as_posix()}")
print(f"- run_date={payload.get('run_date', '<missing>')}")
print("- database_query_run=1")
print("- external_network_run=0")
print("- payload_values_printed=0")
print("- payload_secret_hit_count=0")
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
    check)
      local profile="${1:-}"
      require_arg "$profile" "check_profile"
      case "$profile" in
        quick)
          check_quick
          ;;
        changed)
          check_changed
          ;;
        *)
          fail "지원하지 않는 check profile입니다: $profile"
          ;;
      esac
      ;;
    type-check)
      local profile="${1:-}"
      require_arg "$profile" "type_check_profile"
      case "$profile" in
        backend)
          type_check_backend
          ;;
        frontend)
          type_check_frontend
          ;;
        *)
          fail "지원하지 않는 type-check profile입니다: $profile"
          ;;
      esac
      ;;
    security)
      local profile="${1:-}"
      require_arg "$profile" "security_profile"
      case "$profile" in
        scan)
          security_scan
          ;;
        *)
          fail "지원하지 않는 security profile입니다: $profile"
          ;;
      esac
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
      local normalized_target
      normalized_target="$(repo_relative_from_resolved "$file_path")"
      run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m py_compile "$normalized_target"
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
      local normalized_target
      normalized_target="$(repo_relative_from_resolved "$resolved_path")"
      run_python_with_timeout "$SAFE_TIMEOUT_SECONDS" -m ruff check "$normalized_target"
      ;;
    docs-check)
      accept_docs
      ;;
    accept)
      local profile="${1:-}"
      require_arg "$profile" "accept_profile"
      case "$profile" in
        docs)
          accept_docs
          ;;
        ci)
          accept_ci
          ;;
        env)
          accept_env
          ;;
        db-structure)
          accept_db_structure
          ;;
        architecture)
          accept_architecture
          ;;
        style)
          accept_style
          ;;
        no-bypass)
          accept_no_bypass
          ;;
        backend-file)
          accept_backend_file "${2:-}"
          ;;
        backend-runtime)
          accept_backend_runtime
          ;;
        frontend)
          accept_frontend
          ;;
        ops-report)
          accept_ops_report "${2:-}"
          ;;
        *)
          fail "지원하지 않는 accept profile입니다: $profile"
          ;;
      esac
      ;;
    dump)
      local profile="${1:-}"
      require_arg "$profile" "dump_profile"
      case "$profile" in
        ops-report)
          dump_ops_report "${2:-}"
          ;;
        *)
          fail "지원하지 않는 dump profile입니다: $profile"
          ;;
      esac
      ;;
    run)
      local profile="${1:-}"
      require_arg "$profile" "run_profile"
      case "$profile" in
        api-inmemory)
          run_api_inmemory
          ;;
        api-postgres)
          run_api_postgres
          ;;
        *)
          fail "지원하지 않는 run profile입니다: $profile"
          ;;
      esac
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
