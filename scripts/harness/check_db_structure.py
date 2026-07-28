from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src" / "agent_trading"
REPOSITORIES_ROOT = SRC_ROOT / "repositories"
MIGRATIONS_ROOT = ROOT / "db" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class CheckResult:
    metrics: dict[str, int]
    details: dict[str, list[str]]

    @property
    def passed(self) -> bool:
        failure_keys = {
            "required_file_missing_count",
            "migration_filename_violation_count",
            "migration_duplicate_number_count",
            "migration_sequence_gap_count",
            "container_missing_protocol_count",
            "memory_missing_protocol_count",
            "postgres_class_missing_protocol_count",
            "postgres_bootstrap_missing_protocol_count",
            "container_extra_protocol_count",
            "memory_extra_repository_count",
            "postgres_extra_repository_count",
        }
        return all(self.metrics.get(key, 0) == 0 for key in failure_keys)


def read_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def class_names(path: Path) -> set[str]:
    tree = read_tree(path)
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def repository_protocols(path: Path) -> set[str]:
    tree = read_tree(path)
    protocols: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.endswith("Repository"):
            protocols.add(node.name)
    return protocols


def annotation_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return annotation_name(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def container_repository_annotations(path: Path) -> set[str]:
    tree = read_tree(path)
    annotations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RepositoryContainer":
            for item in node.body:
                if isinstance(item, ast.AnnAssign):
                    name = annotation_name(item.annotation)
                    if name.endswith("Repository"):
                        annotations.add(name)
    return annotations


def postgres_repository_classes(root: Path) -> set[str]:
    classes: set[str] = set()
    for path in sorted(root.glob("*.py")):
        if path.name == "__init__.py":
            continue
        for name in class_names(path):
            if name.startswith("Postgres") and name.endswith("Repository"):
                classes.add(name)
    return classes


def postgres_bootstrap_wiring(path: Path) -> set[str]:
    tree = read_tree(path)
    wired: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if annotation_name(node.value.func) != "RepositoryContainer":
            continue
        for keyword in node.value.keywords:
            value = keyword.value
            if not isinstance(value, ast.Call):
                continue
            name = annotation_name(value.func)
            if name.startswith("Postgres") and name.endswith("Repository"):
                wired.add(name)
    return wired


def migration_result(root: Path) -> tuple[dict[str, int], dict[str, list[str]]]:
    details: dict[str, list[str]] = {
        "migration_filename_violations": [],
        "migration_duplicate_numbers": [],
        "migration_sequence_gaps": [],
    }
    files = sorted(path for path in root.glob("*.sql") if path.is_file())
    numbers: list[int] = []
    number_to_files: dict[int, list[str]] = {}
    for path in files:
        match = MIGRATION_PATTERN.match(path.name)
        if not match:
            details["migration_filename_violations"].append(path.name)
            continue
        number = int(match.group(1))
        numbers.append(number)
        number_to_files.setdefault(number, []).append(path.name)

    for number, names in sorted(number_to_files.items()):
        if len(names) > 1:
            details["migration_duplicate_numbers"].append(f"{number:04d}: {', '.join(names)}")

    gaps: list[int] = []
    if numbers:
        present = set(numbers)
        gaps = [number for number in range(min(present), max(present) + 1) if number not in present]
        details["migration_sequence_gaps"] = [f"{number:04d}" for number in gaps]

    metrics = {
        "migration_file_count": len(files),
        "migration_filename_violation_count": len(details["migration_filename_violations"]),
        "migration_duplicate_number_count": len(details["migration_duplicate_numbers"]),
        "migration_sequence_gap_count": len(gaps),
    }
    return metrics, details


def repository_result() -> tuple[dict[str, int], dict[str, list[str]]]:
    contracts_path = REPOSITORIES_ROOT / "contracts.py"
    container_path = REPOSITORIES_ROOT / "container.py"
    memory_path = REPOSITORIES_ROOT / "memory.py"
    postgres_root = REPOSITORIES_ROOT / "postgres"
    postgres_bootstrap_path = postgres_root / "bootstrap.py"

    protocols = repository_protocols(contracts_path)
    container_annotations = container_repository_annotations(container_path)
    memory_classes = {name.removeprefix("InMemory") for name in class_names(memory_path) if name.startswith("InMemory") and name.endswith("Repository")}
    postgres_classes = {name.removeprefix("Postgres") for name in postgres_repository_classes(postgres_root)}
    postgres_wiring = {name.removeprefix("Postgres") for name in postgres_bootstrap_wiring(postgres_bootstrap_path)}

    details = {
        "container_missing_protocols": sorted(protocols - container_annotations),
        "memory_missing_protocols": sorted(protocols - memory_classes),
        "postgres_class_missing_protocols": sorted(protocols - postgres_classes),
        "postgres_bootstrap_missing_protocols": sorted(protocols - postgres_wiring),
        "container_extra_protocols": sorted(container_annotations - protocols),
        "memory_extra_repositories": sorted(memory_classes - protocols),
        "postgres_extra_repositories": sorted(postgres_classes - protocols),
    }
    metrics = {
        "repository_protocol_count": len(protocols),
        "container_bound_protocol_count": len(protocols & container_annotations),
        "memory_bound_protocol_count": len(protocols & memory_classes),
        "postgres_class_bound_protocol_count": len(protocols & postgres_classes),
        "postgres_bootstrap_bound_protocol_count": len(protocols & postgres_wiring),
        "container_missing_protocol_count": len(details["container_missing_protocols"]),
        "memory_missing_protocol_count": len(details["memory_missing_protocols"]),
        "postgres_class_missing_protocol_count": len(details["postgres_class_missing_protocols"]),
        "postgres_bootstrap_missing_protocol_count": len(details["postgres_bootstrap_missing_protocols"]),
        "container_extra_protocol_count": len(details["container_extra_protocols"]),
        "memory_extra_repository_count": len(details["memory_extra_repositories"]),
        "postgres_extra_repository_count": len(details["postgres_extra_repositories"]),
    }
    return metrics, details


def run() -> CheckResult:
    required_files = [
        REPOSITORIES_ROOT / "contracts.py",
        REPOSITORIES_ROOT / "container.py",
        REPOSITORIES_ROOT / "memory.py",
        REPOSITORIES_ROOT / "postgres" / "bootstrap.py",
        MIGRATIONS_ROOT,
    ]
    missing_files = [str(path.relative_to(ROOT)) for path in required_files if not path.exists()]

    metrics: dict[str, int] = {"required_file_missing_count": len(missing_files)}
    details: dict[str, list[str]] = {"missing_files": missing_files}

    if not missing_files:
        migration_metrics, migration_details = migration_result(MIGRATIONS_ROOT)
        repository_metrics, repository_details = repository_result()
        metrics.update(migration_metrics)
        metrics.update(repository_metrics)
        details.update(migration_details)
        details.update(repository_details)
    else:
        metrics.update(
            {
                "migration_file_count": 0,
                "migration_filename_violation_count": 0,
                "migration_duplicate_number_count": 0,
                "migration_sequence_gap_count": 0,
                "repository_protocol_count": 0,
                "container_bound_protocol_count": 0,
                "memory_bound_protocol_count": 0,
                "postgres_class_bound_protocol_count": 0,
                "postgres_bootstrap_bound_protocol_count": 0,
                "container_missing_protocol_count": 0,
                "memory_missing_protocol_count": 0,
                "postgres_class_missing_protocol_count": 0,
                "postgres_bootstrap_missing_protocol_count": 0,
                "container_extra_protocol_count": 0,
                "memory_extra_repository_count": 0,
                "postgres_extra_repository_count": 0,
            }
        )

    metrics.update(
        {
            "database_connection_run": 0,
            "external_network_run": 0,
            "full_test_run": 0,
        }
    )
    return CheckResult(metrics=metrics, details=details)


def main() -> int:
    result = run()
    print(f"ACCEPT db-structure: {'PASS' if result.passed else 'FAIL'}")
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
