from __future__ import annotations

from scripts.harness.check_no_bypass import AddedLine, find_bypass_candidates


def _line(path: str, text: str) -> AddedLine:
    return AddedLine(path=path, line_number=10, text=text, source="test")


def test_safety_invariant_bypass_is_hard_failure() -> None:
    text = "risk_" + "gate " + "bypass enabled"

    hard_findings, review_findings, allowlisted_count = find_bypass_candidates(
        [_line("scripts/run_agent_subprocess.py", text)],
        ["scripts/run_agent_subprocess.py"],
    )

    assert [finding.rule for finding in hard_findings] == ["safety_invariant_bypass"]
    assert review_findings == []
    assert allowlisted_count == 0


def test_env_direct_change_is_hard_failure_without_added_lines() -> None:
    hard_findings, review_findings, allowlisted_count = find_bypass_candidates([], [".env.local"])

    assert [finding.rule for finding in hard_findings] == ["env_direct_change"]
    assert review_findings == []
    assert allowlisted_count == 0


def test_review_patterns_do_not_fail_hard() -> None:
    text = "except " + "Exception as exc:"

    hard_findings, review_findings, allowlisted_count = find_bypass_candidates(
        [_line("scripts/run_agent_subprocess.py", text)],
        ["scripts/run_agent_subprocess.py"],
    )

    assert hard_findings == []
    assert [finding.rule for finding in review_findings] == ["broad_exception"]
    assert allowlisted_count == 0


def test_policy_docs_are_allowlisted_for_explanatory_patterns() -> None:
    text = "risk_" + "gate " + "bypass must stay documented"

    hard_findings, review_findings, allowlisted_count = find_bypass_candidates(
        [_line("scripts/harness/README.md", text)],
        ["scripts/harness/README.md"],
    )

    assert hard_findings == []
    assert review_findings == []
    assert allowlisted_count == 1
