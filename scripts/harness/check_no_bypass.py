from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SELF_PATH = Path(__file__).resolve()

TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

ALLOWLIST_PATH_PREFIXES = (
    "docs/",
    "scripts/harness/README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "src/AGENTS.md",
    "admin_ui/AGENTS.md",
)

SAFETY_TERMS = (
    r"risk[_ -]?gate",
    r"sell[_ -]?guard",
    r"submit[_ -]?lane",
    r"reconciliation[_ -]?lock",
    r"broker[_ -]?contract",
)
BYPASS_TERMS = r"bypass|disable|ignore|skip|force|override|pass"
SAFETY_BYPASS_PATTERN = re.compile(
    rf"(?i)({'|'.join(SAFETY_TERMS)}).*\b({BYPASS_TERMS})\b|\b({BYPASS_TERMS})\b.*({'|'.join(SAFETY_TERMS)})"
)
HEAVY_IN_SAFE_PATTERN = re.compile(r"\bHARNESS_ALLOW_HEAVY\s*=\s*1\b")
REVIEW_PATTERNS = {
    "static_checker_exception": re.compile(r"(?i)#\s*noqa|type:\s*ignore|pragma:\s*no cover"),
    "test_skip_or_xfail": re.compile(r"(?i)pytest\.skip|pytest\.mark\.skip|pytest\.mark\.xfail|\bxfail\b"),
    "harness_allow_flag": re.compile(r"\bHARNESS_ALLOW_[A-Z0-9_]+\b"),
    "mock_or_monkeypatch": re.compile(r"\b(mock\.patch|monkeypatch|MagicMock|AsyncMock)\b"),
    "broad_exception": re.compile(r"\bexcept\s+(Exception|BaseException)\b|\bexcept\s*:"),
    "forced_boolean_success": re.compile(r"\breturn\s+True\b"),
}


@dataclass(frozen=True)
class AddedLine:
    path: str
    line_number: int
    text: str
    source: str


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    path: str
    line_number: int
    text: str


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_stdout(args: list[str]) -> str:
    result = run_git(args)
    return result.stdout if result.returncode == 0 else ""


def unique_lines(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def repo_relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_text_candidate(path: Path) -> bool:
    if path.resolve() == SELF_PATH:
        return False
    if path.suffix in TEXT_SUFFIXES:
        return True
    return path.name in {"Makefile", "Dockerfile"}


def is_allowlisted_path(path: str) -> bool:
    return path.startswith(ALLOWLIST_PATH_PREFIXES)


def is_env_direct_change(path: str) -> bool:
    name = Path(path).name
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def local_changed_paths() -> list[str]:
    paths: list[str] = []
    paths.extend(git_stdout(["diff", "--name-only", "--diff-filter=ACMRT"]).splitlines())
    paths.extend(git_stdout(["diff", "--cached", "--name-only", "--diff-filter=ACMRT"]).splitlines())
    paths.extend(git_stdout(["ls-files", "--others", "--exclude-standard"]).splitlines())
    return unique_lines(paths)


def branch_changed_paths(base_ref: str) -> list[str]:
    return unique_lines(git_stdout(["diff", "--name-only", "--diff-filter=ACMRT", f"{base_ref}...HEAD"]).splitlines())


def current_branch_name() -> str:
    return git_stdout(["branch", "--show-current"]).strip()


def selected_base_ref() -> str:
    explicit = os.environ.get("HARNESS_NO_BYPASS_BASE_REF", "").strip()
    if explicit:
        return explicit
    if local_changed_paths():
        return ""
    github_base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if github_base_ref:
        candidate = f"origin/{github_base_ref}"
        if run_git(["rev-parse", "--verify", candidate]).returncode == 0:
            return candidate
    if os.environ.get("GITHUB_EVENT_NAME", "").strip() == "push":
        if run_git(["rev-parse", "--verify", "HEAD^"]).returncode == 0:
            return "HEAD^"
    branch = current_branch_name()
    if branch and branch not in {"main", "master"} and run_git(["rev-parse", "--verify", "origin/main"]).returncode == 0:
        return "origin/main"
    return ""


def parse_diff_added_lines(diff_text: str, source: str) -> list[AddedLine]:
    lines: list[AddedLine] = []
    current_path = ""
    next_line_number = 0
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ b/"):
            current_path = raw_line.removeprefix("+++ b/")
            continue
        if raw_line.startswith("@@ "):
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
            next_line_number = int(match.group(1)) if match else 0
            continue
        if not current_path or raw_line.startswith("+++") or raw_line.startswith("---"):
            continue
        if raw_line.startswith("+"):
            text = raw_line[1:]
            lines.append(
                AddedLine(
                    path=current_path,
                    line_number=next_line_number,
                    text=text,
                    source=source,
                )
            )
            next_line_number += 1
        elif not raw_line.startswith("-") and next_line_number:
            next_line_number += 1
    return lines


def added_lines_from_git_diff(args: list[str], source: str) -> list[AddedLine]:
    diff_text = git_stdout(args)
    return parse_diff_added_lines(diff_text, source)


def added_lines_from_untracked(paths: list[str]) -> list[AddedLine]:
    lines: list[AddedLine] = []
    for path in paths:
        absolute_path = ROOT / path
        if not absolute_path.is_file() or not is_text_candidate(absolute_path):
            continue
        try:
            text_lines = absolute_path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for index, text in enumerate(text_lines, start=1):
            lines.append(AddedLine(path=path, line_number=index, text=text, source="untracked"))
    return lines


def collect_added_lines(base_ref: str, changed_paths: list[str]) -> list[AddedLine]:
    if base_ref:
        return added_lines_from_git_diff(["diff", "--unified=0", "--diff-filter=ACMRT", f"{base_ref}...HEAD"], "base")

    lines: list[AddedLine] = []
    lines.extend(added_lines_from_git_diff(["diff", "--unified=0", "--diff-filter=ACMRT"], "unstaged"))
    lines.extend(added_lines_from_git_diff(["diff", "--cached", "--unified=0", "--diff-filter=ACMRT"], "staged"))
    untracked_paths = [
        path for path in changed_paths if run_git(["ls-files", "--error-unmatch", path]).returncode != 0
    ]
    lines.extend(added_lines_from_untracked(untracked_paths))
    return lines


def line_is_scannable(added_line: AddedLine) -> bool:
    absolute_path = ROOT / added_line.path
    return absolute_path.is_file() and is_text_candidate(absolute_path)


def find_bypass_candidates(lines: list[AddedLine], changed_paths: list[str]) -> tuple[list[Finding], list[Finding], int]:
    hard_findings: list[Finding] = []
    review_findings: list[Finding] = []
    allowlisted_count = 0

    for path in changed_paths:
        if is_env_direct_change(path):
            hard_findings.append(
                Finding(
                    severity="hard",
                    rule="env_direct_change",
                    path=path,
                    line_number=0,
                    text=".env 직접 변경은 허용하지 않는다.",
                )
            )

    for added_line in lines:
        if not line_is_scannable(added_line):
            continue
        if is_allowlisted_path(added_line.path):
            if SAFETY_BYPASS_PATTERN.search(added_line.text) or HEAVY_IN_SAFE_PATTERN.search(added_line.text) or any(
                pattern.search(added_line.text) for pattern in REVIEW_PATTERNS.values()
            ):
                allowlisted_count += 1
            continue

        if SAFETY_BYPASS_PATTERN.search(added_line.text):
            hard_findings.append(
                Finding(
                    severity="hard",
                    rule="safety_invariant_bypass",
                    path=added_line.path,
                    line_number=added_line.line_number,
                    text=added_line.text.strip(),
                )
            )
        if added_line.path.startswith(".github/workflows/") and HEAVY_IN_SAFE_PATTERN.search(added_line.text):
            hard_findings.append(
                Finding(
                    severity="hard",
                    rule="heavy_flag_in_workflow",
                    path=added_line.path,
                    line_number=added_line.line_number,
                    text=added_line.text.strip(),
                )
            )

        for rule, pattern in REVIEW_PATTERNS.items():
            if pattern.search(added_line.text):
                review_findings.append(
                    Finding(
                        severity="review",
                        rule=rule,
                        path=added_line.path,
                        line_number=added_line.line_number,
                        text=added_line.text.strip(),
                    )
                )
    return hard_findings, review_findings, allowlisted_count


def print_findings(title: str, findings: list[Finding]) -> None:
    if not findings:
        return
    print(f"DETAIL {title}:")
    for finding in findings[:50]:
        location = finding.path if finding.line_number == 0 else f"{finding.path}:{finding.line_number}"
        print(f"- {finding.rule}: {location}: {finding.text}")
    if len(findings) > 50:
        print(f"- truncated_count={len(findings) - 50}")


def run() -> int:
    base_ref = selected_base_ref()
    changed_paths = branch_changed_paths(base_ref) if base_ref else local_changed_paths()
    text_changed_paths = [
        path for path in changed_paths if (ROOT / path).is_file() and is_text_candidate(ROOT / path)
    ]
    added_lines = collect_added_lines(base_ref, changed_paths)
    hard_findings, review_findings, allowlisted_count = find_bypass_candidates(added_lines, changed_paths)
    metrics = {
        "changed_file_count": len(changed_paths),
        "scanned_file_count": len(text_changed_paths),
        "added_line_count": len(added_lines),
        "hard_bypass_count": len(hard_findings),
        "review_bypass_count": len(review_findings),
        "allowlisted_bypass_count": allowlisted_count,
        "new_bypass_candidate_count": len(hard_findings) + len(review_findings),
        "database_connection_run": 0,
        "external_network_run": 0,
        "full_test_run": 0,
    }
    passed = metrics["hard_bypass_count"] == 0
    print(f"ACCEPT no-bypass: {'PASS' if passed else 'FAIL'}")
    print(f"- source_mode={'branch' if base_ref else 'worktree'}")
    print(f"- base_ref={base_ref or 'none'}")
    for key, value in metrics.items():
        print(f"- {key}={value}")
    print_findings("hard_bypass_candidates", hard_findings)
    print_findings("review_bypass_candidates", review_findings)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(run())
