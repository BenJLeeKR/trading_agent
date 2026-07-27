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
  bash scripts/harness/run.sh accept docs
  bash scripts/harness/run.sh accept env
  bash scripts/harness/run.sh accept backend-file <src/agent_trading/file.py>
  bash scripts/harness/run.sh accept backend-runtime
  bash scripts/harness/run.sh accept frontend
  bash scripts/harness/run.sh accept ops-report <summary_json>
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

accept_docs() {
  python3 - <<'PY'
import re
from pathlib import Path

root = Path("/workspace/agent_trading")
core_docs = [
    root / "README.md",
    root / "AGENTS.md",
    root / "CLAUDE.md",
    root / "src" / "AGENTS.md",
    root / "admin_ui" / "AGENTS.md",
    root / "docs" / "99_meta_handover" / "agent_workspace_guide.md",
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

def contains(path: Path, *needles: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text()
    return all(needle in text for needle in needles)

semantic_checks = [
    ("readme_routes_to_agents", contains(root / "README.md", "AGENTS.md", "CLAUDE.md", "agent_workspace_guide.md")),
    ("claude_routes_to_nested_agents", contains(root / "CLAUDE.md", "AGENTS.md", "src/AGENTS.md", "admin_ui/AGENTS.md")),
    ("root_agents_requires_harness", contains(root / "AGENTS.md", "scripts/harness/run.sh", "검증 부하 제한")),
    ("root_agents_env_secret_policy", contains(root / "AGENTS.md", ".env", "직접 수정하지 않는다", "노출하지 않는다")),
    ("workspace_guide_declares_project_root", contains(root / "docs" / "99_meta_handover" / "agent_workspace_guide.md", "/workspace/agent_trading/", "문서 역할 분리")),
    ("fixture_policy_present", contains(root / "tests" / "fixtures" / "README.md", "data/", "logs/", "tmp/")),
]
failed_semantic_checks = [name for name, ok in semantic_checks if not ok]

metrics = {
    "required_file_missing_count": len(missing_files),
    "markdown_link_missing_count": len(missing_links),
    "deprecated_reference_count": len(deprecated_hits),
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

if failed_semantic_checks:
    print("DETAIL failed_semantic_checks:")
    for name in failed_semantic_checks:
        print(f"- {name}")

raise SystemExit(0 if passed else 1)
PY
}

accept_env() {
  python3 - <<'PY'
import json
import re
import subprocess
from pathlib import Path

root = Path("/workspace/agent_trading")

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
            timeout=30,
            check=False,
        )
    except Exception:
        return 1, ""
    return completed.returncode, completed.stdout.strip()

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

code, output = run_command(["docker", "run", "--rm", "node:20-slim", "node", "--version"])
if code == 0 and output:
    runtime_versions["node"] = output.removeprefix("v")
    runtime_sources["node"] = "node:20-slim"
else:
    code, output = run_command(["node", "--version"])
    runtime_versions["node"] = output.removeprefix("v") if code == 0 else ""
    runtime_sources["node"] = "host-node"

code, output = run_command(["docker", "run", "--rm", "node:20-slim", "npm", "--version"])
if code == 0 and output:
    runtime_versions["npm"] = output
    runtime_sources["npm"] = "node:20-slim"
else:
    code, output = run_command(["npm", "--version"])
    runtime_versions["npm"] = output if code == 0 else ""
    runtime_sources["npm"] = "host-npm"

code, output = run_command(["docker", "exec", "trading_db", "psql", "-U", "trading", "-d", "trading", "-tAc", "SHOW server_version;"])
runtime_versions["postgres"] = output.replace(" ", "") if code == 0 else ""
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

static_checks.append(("pyproject_python_range", 'requires-python = ">=3.14,<3.15"' in pyproject))
static_checks.append(("dockerfile_python_pin", f"FROM python:{expected['python']}-slim" in dockerfile))
static_checks.append(("dockerfile_uses_requirements_lock", "requirements.lock" in dockerfile and "--constraint requirements.lock" in dockerfile))
static_checks.append(("admin_dockerfile_node_pin", f"FROM node:{expected['node']}-slim AS build" in admin_dockerfile))
static_checks.append(("npm_engine_strict", npmrc == "engine-strict=true"))
static_checks.append(("gitignore_excludes_env", re.search(r"(?m)^\.env$", gitignore) is not None))

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

root = Path("/workspace/agent_trading")
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

root = Path("/workspace/agent_trading")
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
    ("env_example_backend_keys", required_env_example_keys.issubset(env_example_keys)),
]
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

accept_frontend() {
  python3 - <<'PY'
import json
import re
import subprocess
from pathlib import Path

root = Path("/workspace/agent_trading")
admin_root = root / "admin_ui"

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
            timeout=30,
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
code, output = run_command(["docker", "run", "--rm", "node:20-slim", "node", "--version"])
if code == 0 and output:
    runtime_versions["node"] = output.removeprefix("v")
    runtime_sources["node"] = "node:20-slim"
else:
    code, output = run_command(["node", "--version"])
    runtime_versions["node"] = output.removeprefix("v") if code == 0 else ""
    runtime_sources["node"] = "host-node"

code, output = run_command(["docker", "run", "--rm", "node:20-slim", "npm", "--version"])
if code == 0 and output:
    runtime_versions["npm"] = output
    runtime_sources["npm"] = "node:20-slim"
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
import re
import sys
from pathlib import Path
from typing import Any

root = Path("/workspace/agent_trading")
raw_arg = sys.argv[1]

def resolve_input(raw: str) -> tuple[str, str]:
    if raw.lstrip().startswith(("{", "[")):
        return raw, "<inline-json>"
    candidate = (root / raw).resolve() if not raw.startswith("/") else Path(raw).resolve()
    if str(candidate).startswith(str(root) + "/") and candidate.is_file():
        return candidate.read_text(), str(candidate.relative_to(root))
    return raw, "<inline-json>"

def load_payload(raw: str) -> dict[str, Any]:
    text, source = resolve_input(raw)
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

def collect_secret_key_hits(value: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    secret_pattern = re.compile(r"(secret|password|passwd|authorization|approval_key|access_token|refresh_token|bearer_token|appkey|appsecret|api_key|client_secret)", re.I)
    if isinstance(value, dict):
        for key, nested in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if secret_pattern.search(str(key)) and nested not in (None, "", [], {}):
                hits.append(child_path)
            hits.extend(collect_secret_key_hits(nested, child_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            hits.extend(collect_secret_key_hits(nested, f"{path}[{index}]"))
    return hits

payload = load_payload(raw_arg)

required_top_level_paths = [
    "command_results_count",
    "ok_count",
    "failed_count",
    "timed_out_count",
    "command_health",
    "decision_loop",
    "command_health.decision_loop",
]
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
    if command_results_count <= 0:
        counter_inconsistencies.append("command_results_count<=0")

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
if isinstance(command_health_decision_loop, dict):
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
    "decision_metric_missing_count": len(decision_metric_failures),
    "decision_coverage_failed_count": len(coverage_failures),
    "decision_health_failed_count": len(health_failures),
    "secret_key_hit_count": len(secret_key_hits),
}

passed = all(value == 0 for value in metrics.values())
print(f"ACCEPT ops-report: {'PASS' if passed else 'FAIL'}")
for key, value in metrics.items():
    print(f"- {key}={value}")
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
    accept)
      local profile="${1:-}"
      require_arg "$profile" "accept_profile"
      case "$profile" in
        docs)
          accept_docs
          ;;
        env)
          accept_env
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
