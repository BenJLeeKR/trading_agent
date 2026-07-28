from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "src" / "agent_trading"
ADMIN_ROOT = ROOT / "admin_ui" / "src"
DIRECT_FETCH_PATTERN = re.compile(r"\bfetch\s*\(")
BROKER_FORBIDDEN_IMPORT_BASELINE = 7
LEGACY_DIRECT_DB_IMPORT_BASELINE = 0
API_DB_BOUNDARY_FILES = frozenset({"src/agent_trading/api/deps.py"})


@dataclass(frozen=True)
class CheckResult:
    metrics: dict[str, int]
    details: dict[str, list[str]]

    @property
    def passed(self) -> bool:
        failure_keys = {
            "required_directory_missing_count",
            "domain_forbidden_import_count",
            "repository_forbidden_import_count",
            "service_api_import_violation_count",
            "db_forbidden_import_count",
            "frontend_direct_fetch_observed_count",
            "broker_forbidden_import_excess_count",
            "legacy_direct_db_import_excess_count",
        }
        return all(self.metrics.get(key, 0) == 0 for key in failure_keys)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )


def frontend_files(root: Path) -> list[Path]:
    return sorted(
        path
        for pattern in ("*.ts", "*.tsx")
        for path in root.rglob(pattern)
        if path.is_file()
    )


def imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                modules.append((node.lineno, node.module))
    return modules


def starts_any(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value == prefix or value.startswith(f"{prefix}.") for prefix in prefixes)


def add_violation(details: dict[str, list[str]], name: str, path: Path, line: int, module: str) -> None:
    details.setdefault(name, []).append(f"{relative(path)}:{line}: {module}")


def check_backend_imports(files: list[Path]) -> tuple[dict[str, int], dict[str, list[str]]]:
    details: dict[str, list[str]] = {
        "domain_forbidden_imports": [],
        "repository_forbidden_imports": [],
        "service_api_import_violations": [],
        "broker_forbidden_imports": [],
        "db_forbidden_imports": [],
        "legacy_direct_db_imports": [],
        "api_db_boundary_imports": [],
    }
    import_checked_count = 0
    for path in files:
        rel = relative(path)
        for line, module in imported_modules(path):
            if not module.startswith("agent_trading") and module != "asyncpg":
                continue
            import_checked_count += 1
            if rel.startswith("src/agent_trading/domain/") and starts_any(
                module,
                (
                    "agent_trading.api",
                    "agent_trading.brokers",
                    "agent_trading.db",
                    "agent_trading.repositories",
                    "agent_trading.runtime",
                    "agent_trading.services",
                ),
            ):
                add_violation(details, "domain_forbidden_imports", path, line, module)
            if rel.startswith("src/agent_trading/repositories/") and starts_any(
                module,
                (
                    "agent_trading.api",
                    "agent_trading.brokers",
                    "agent_trading.runtime",
                    "agent_trading.services",
                ),
            ):
                add_violation(details, "repository_forbidden_imports", path, line, module)
            if rel.startswith("src/agent_trading/services/") and starts_any(module, ("agent_trading.api",)):
                add_violation(details, "service_api_import_violations", path, line, module)
            if rel.startswith("src/agent_trading/brokers/") and starts_any(
                module,
                (
                    "agent_trading.api",
                    "agent_trading.repositories",
                    "agent_trading.services",
                ),
            ):
                add_violation(details, "broker_forbidden_imports", path, line, module)
            if rel.startswith("src/agent_trading/db/") and starts_any(
                module,
                (
                    "agent_trading.api",
                    "agent_trading.brokers",
                    "agent_trading.services",
                ),
            ):
                add_violation(details, "db_forbidden_imports", path, line, module)
            if rel.startswith(("src/agent_trading/services/", "src/agent_trading/api/")) and (
                module == "asyncpg" or starts_any(module, ("agent_trading.db",))
            ):
                if rel in API_DB_BOUNDARY_FILES:
                    add_violation(details, "api_db_boundary_imports", path, line, module)
                else:
                    add_violation(details, "legacy_direct_db_imports", path, line, module)

    metrics = {
        "python_source_file_count": len(files),
        "backend_import_checked_count": import_checked_count,
        "domain_forbidden_import_count": len(details["domain_forbidden_imports"]),
        "repository_forbidden_import_count": len(details["repository_forbidden_imports"]),
        "service_api_import_violation_count": len(details["service_api_import_violations"]),
        "broker_forbidden_import_observed_count": len(details["broker_forbidden_imports"]),
        "db_forbidden_import_count": len(details["db_forbidden_imports"]),
        "legacy_direct_db_import_observed_count": len(details["legacy_direct_db_imports"]),
        "api_db_boundary_import_observed_count": len(details["api_db_boundary_imports"]),
    }
    return metrics, details


def check_frontend_files(files: list[Path]) -> tuple[dict[str, int], dict[str, list[str]]]:
    direct_fetches: list[str] = []
    for path in files:
        rel = relative(path)
        if rel.startswith("admin_ui/src/api/") or rel.startswith("admin_ui/src/__tests__/"):
            continue
        for index, line in enumerate(path.read_text().splitlines(), start=1):
            if DIRECT_FETCH_PATTERN.search(line):
                direct_fetches.append(f"{rel}:{index}")
    metrics = {
        "frontend_source_file_count": len(files),
        "frontend_direct_fetch_observed_count": len(direct_fetches),
    }
    return metrics, {"frontend_direct_fetches": direct_fetches}


def run() -> CheckResult:
    required_directories = [
        BACKEND_ROOT / "domain",
        BACKEND_ROOT / "services",
        BACKEND_ROOT / "repositories",
        BACKEND_ROOT / "api",
        BACKEND_ROOT / "brokers",
        BACKEND_ROOT / "db",
        BACKEND_ROOT / "runtime",
        ADMIN_ROOT,
    ]
    missing_directories = [relative(path) for path in required_directories if not path.is_dir()]
    metrics: dict[str, int] = {"required_directory_missing_count": len(missing_directories)}
    details: dict[str, list[str]] = {"missing_directories": missing_directories}

    if not missing_directories:
        backend_metrics, backend_details = check_backend_imports(python_files(BACKEND_ROOT))
        frontend_metrics, frontend_details = check_frontend_files(frontend_files(ADMIN_ROOT))
        metrics.update(backend_metrics)
        metrics.update(frontend_metrics)
        details.update(backend_details)
        details.update(frontend_details)
    else:
        metrics.update(
            {
                "python_source_file_count": 0,
                "backend_import_checked_count": 0,
                "domain_forbidden_import_count": 0,
                "repository_forbidden_import_count": 0,
                "service_api_import_violation_count": 0,
                "broker_forbidden_import_observed_count": 0,
                "db_forbidden_import_count": 0,
                "legacy_direct_db_import_observed_count": 0,
                "api_db_boundary_import_observed_count": 0,
                "frontend_source_file_count": 0,
                "frontend_direct_fetch_observed_count": 0,
            }
        )

    enforced_violation_count = sum(
        metrics.get(key, 0)
        for key in (
            "required_directory_missing_count",
            "domain_forbidden_import_count",
            "repository_forbidden_import_count",
            "service_api_import_violation_count",
            "db_forbidden_import_count",
            "frontend_direct_fetch_observed_count",
        )
    )
    broker_excess_count = max(
        0,
        metrics.get("broker_forbidden_import_observed_count", 0) - BROKER_FORBIDDEN_IMPORT_BASELINE,
    )
    legacy_db_excess_count = max(
        0,
        metrics.get("legacy_direct_db_import_observed_count", 0) - LEGACY_DIRECT_DB_IMPORT_BASELINE,
    )
    enforced_violation_count += broker_excess_count + legacy_db_excess_count
    metrics.update(
        {
            "architecture_violation_count": enforced_violation_count,
            "frontend_direct_fetch_enforced": 1,
            "broker_forbidden_import_baseline": BROKER_FORBIDDEN_IMPORT_BASELINE,
            "broker_forbidden_import_baseline_enforced": 1,
            "broker_forbidden_import_excess_count": broker_excess_count,
            "legacy_direct_db_import_baseline": LEGACY_DIRECT_DB_IMPORT_BASELINE,
            "legacy_direct_db_import_baseline_enforced": 1,
            "legacy_direct_db_import_excess_count": legacy_db_excess_count,
            "database_connection_run": 0,
            "external_network_run": 0,
            "full_test_run": 0,
        }
    )
    return CheckResult(metrics=metrics, details=details)


def main() -> int:
    result = run()
    print(f"ACCEPT architecture: {'PASS' if result.passed else 'FAIL'}")
    for key, value in result.metrics.items():
        print(f"- {key}={value}")
    for name, values in result.details.items():
        if not values:
            continue
        print(f"DETAIL {name}:")
        for value in values:
            print(f"- {value}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
