from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.guardrail_audit import (
    persist_blocking_guardrail_evaluation,
    persist_validation_result,
)
from agent_trading.services.validators import (
    RuleOutcome,
    ValidationContext,
    ValidationResult,
    ValidationRule,
    build_validation_context,
    run_validation_rules,
)


def test_validation_result_to_guardrail_evaluation_merges_context_fields() -> None:
    decision_context_id = uuid4()
    trade_decision_id = uuid4()
    order_request_id = uuid4()
    account_id = uuid4()

    result = ValidationResult.blocked(
        rule_set_version="execution_validator_v1",
        blocking_rule_codes=["recent_active_buy_order"],
        rule_results={"existing_order_id": "ord-123"},
        stop_reason="recent_active_buy_order",
        message="최근 활성 매수 주문 존재",
    )

    evaluation = result.to_guardrail_evaluation(
        context=ValidationContext(
            decision_context_id=decision_context_id,
            trade_decision_id=trade_decision_id,
            order_request_id=order_request_id,
            account_id=account_id,
            symbol="005930",
            market="KRX",
            side="buy",
            source_type="core",
        )
    )

    assert evaluation.rule_set_version == "execution_validator_v1"
    assert evaluation.overall_passed is False
    assert evaluation.decision_context_id == decision_context_id
    assert evaluation.trade_decision_id == trade_decision_id
    assert evaluation.order_request_id == order_request_id
    assert evaluation.blocking_rule_codes == ["recent_active_buy_order"]
    assert evaluation.rule_results["existing_order_id"] == "ord-123"
    assert evaluation.rule_results["account_id"] == str(account_id)
    assert evaluation.rule_results["symbol"] == "005930"
    assert evaluation.rule_results["market"] == "KRX"
    assert evaluation.rule_results["side"] == "buy"
    assert evaluation.rule_results["source_type"] == "core"


def test_run_validation_rules_collects_rule_outcomes_and_stop_reason() -> None:
    context = ValidationContext(
        symbol="000227",
        source_type="core",
        metadata={"submit_budget_consumed_count": 1},
    )
    result = run_validation_rules(
        rule_set_version="submit_lane_gate_v1",
        context=context,
        rules=(
            ValidationRule(
                name="budget_available",
                evaluator=lambda _context: RuleOutcome(
                    code="submit_budget_consumed_core",
                    passed=False,
                    details={"consumed": 1},
                ),
            ),
            ValidationRule(
                name="downstream_note",
                evaluator=lambda _context: RuleOutcome(
                    code="advisory_only",
                    passed=True,
                    details={"note": "not blocking"},
                ),
            ),
        ),
    )

    assert result.is_blocking is True
    assert result.stop_reason == "submit_budget_consumed_core"
    assert result.rule_results["rule_outcomes"]["budget_available"]["passed"] is False
    assert (
        result.rule_results["rule_outcomes"]["budget_available"]["details"]["consumed"]
        == 1
    )


def test_build_validation_context_populates_fields_from_rule_results() -> None:
    decision_context_id = uuid4()
    trade_decision_id = uuid4()
    account_id = uuid4()

    context = build_validation_context(
        decision_context_id=decision_context_id,
        trade_decision_id=trade_decision_id,
        rule_results={
            "account_id": str(account_id),
            "symbol": "005930",
            "market": "KRX",
            "side": "buy",
            "source_type": "core",
        },
        metadata={"gate_phase": "execution"},
    )

    assert context.decision_context_id == decision_context_id
    assert context.trade_decision_id == trade_decision_id
    assert context.account_id == account_id
    assert context.symbol == "005930"
    assert context.market == "KRX"
    assert context.side == "buy"
    assert context.source_type == "core"
    assert context.metadata["gate_phase"] == "execution"


@pytest.mark.asyncio
async def test_persist_validation_result_records_guardrail_row() -> None:
    repos = build_in_memory_repositories()
    decision_context_id = uuid4()
    trade_decision_id = uuid4()

    await persist_validation_result(
        repos,
        validation_context=ValidationContext(
            decision_context_id=decision_context_id,
            trade_decision_id=trade_decision_id,
            symbol="003490",
            market="KRX",
            side="sell",
            source_type="held_position",
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version="sell_guard_v1",
            blocking_rule_codes=["sell_guard_blocked"],
            rule_results={"available_sell_qty": "0"},
        ),
    )

    rows = await repos.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.rule_set_version == "sell_guard_v1"
    assert row.blocking_rule_codes == ["sell_guard_blocked"]
    assert row.rule_results["available_sell_qty"] == "0"
    assert row.rule_results["symbol"] == "003490"
    assert row.rule_results["market"] == "KRX"
    assert row.rule_results["side"] == "sell"
    assert row.rule_results["source_type"] == "held_position"


@pytest.mark.asyncio
async def test_legacy_blocking_guardrail_api_uses_validation_contract() -> None:
    repos = build_in_memory_repositories()
    decision_context_id = uuid4()

    await persist_blocking_guardrail_evaluation(
        repos,
        rule_set_version="stale_snapshot_guard_v1",
        blocking_rule_codes=["stale_snapshot_account"],
        rule_results={"snapshot_age_seconds": 1900},
        decision_context_id=decision_context_id,
    )

    rows = await repos.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(rows) == 1
    assert rows[0].rule_set_version == "stale_snapshot_guard_v1"
    assert rows[0].blocking_rule_codes == ["stale_snapshot_account"]
    assert rows[0].rule_results["snapshot_age_seconds"] == 1900


@pytest.mark.asyncio
async def test_persist_validation_result_stamps_policy_git_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage A(2026-08-20): persist_validation_result()이 단일 진입점에서
    policy_git_sha를 주입해야 한다 — 모든 guardrail 기록 호출부(pre-AI
    gate/scheduler gate/Pass 2 drop 등)에 자동으로 반영됨을 증명."""
    import agent_trading.services.guardrail_audit as guardrail_audit_module

    monkeypatch.setattr(
        guardrail_audit_module, "resolve_policy_git_sha", lambda: "deadbeef123"
    )
    repos = build_in_memory_repositories()
    decision_context_id = uuid4()

    await persist_validation_result(
        repos,
        validation_context=ValidationContext(
            decision_context_id=decision_context_id,
            symbol="005930",
            market="KRX",
            source_type="core",
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version="pre_ai_gate_v1",
            blocking_rule_codes=["general_buy_budget_exhausted"],
        ),
    )

    rows = await repos.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(rows) == 1
    assert rows[0].policy_git_sha == "deadbeef123"


@pytest.mark.asyncio
async def test_persist_validation_result_policy_git_sha_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """policy_git_sha가 없으면(env 미설정) None으로 저장돼 기존 동작과
    동일해야 한다(하위 호환)."""
    import agent_trading.services.guardrail_audit as guardrail_audit_module

    monkeypatch.setattr(
        guardrail_audit_module, "resolve_policy_git_sha", lambda: None
    )
    repos = build_in_memory_repositories()
    decision_context_id = uuid4()

    await persist_validation_result(
        repos,
        validation_context=ValidationContext(
            decision_context_id=decision_context_id,
            symbol="005930",
            market="KRX",
            source_type="core",
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version="pre_ai_gate_v1",
            blocking_rule_codes=["general_buy_budget_exhausted"],
        ),
    )

    rows = await repos.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(rows) == 1
    assert rows[0].policy_git_sha is None


def test_build_validation_context_carries_decision_cycle_id() -> None:
    """Stage A-1b(2026-08-20): ``build_validation_context()``가
    ``decision_cycle_id``를 ``ValidationContext``에 그대로 담아야
    한다."""
    context = build_validation_context(
        symbol="005930",
        market="KRX",
        source_type="core",
        decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00#1",
    )
    assert context.decision_cycle_id == (
        "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    )


def test_to_guardrail_evaluation_carries_decision_cycle_id() -> None:
    """``ValidationResult.to_guardrail_evaluation()``이 context의
    ``decision_cycle_id``를 entity에 그대로 옮겨야 한다."""
    result = ValidationResult.blocked(
        rule_set_version="pass2_general_lane_drop_v1",
        blocking_rule_codes=["submit_budget_consumed_core"],
    )
    evaluation = result.to_guardrail_evaluation(
        context=ValidationContext(
            symbol="005930",
            market="KRX",
            source_type="core",
            decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00#1",
        )
    )
    assert evaluation.decision_cycle_id == (
        "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    )


@pytest.mark.asyncio
async def test_persist_validation_result_stamps_decision_cycle_id() -> None:
    """``persist_validation_result()``를 거친 실제 저장 row에도
    ``decision_cycle_id``가 남는지 end-to-end로 검증한다(in-memory
    repos)."""
    repos = build_in_memory_repositories()
    decision_context_id = uuid4()

    await persist_validation_result(
        repos,
        validation_context=build_validation_context(
            decision_context_id=decision_context_id,
            symbol="005930",
            market="KRX",
            source_type="core",
            decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00#1",
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version="pre_ai_gate_v1",
            blocking_rule_codes=["general_buy_budget_exhausted"],
        ),
    )

    rows = await repos.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(rows) == 1
    assert rows[0].decision_cycle_id == (
        "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    )


@pytest.mark.asyncio
async def test_persist_validation_result_decision_cycle_id_none_by_default() -> None:
    """``decision_cycle_id``를 안 넘기면 기존과 동일하게 None으로
    저장돼야 한다(하위 호환)."""
    repos = build_in_memory_repositories()
    decision_context_id = uuid4()

    await persist_validation_result(
        repos,
        validation_context=build_validation_context(
            decision_context_id=decision_context_id,
            symbol="005930",
            market="KRX",
            source_type="core",
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version="pre_ai_gate_v1",
            blocking_rule_codes=["general_buy_budget_exhausted"],
        ),
    )

    rows = await repos.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(rows) == 1
    assert rows[0].decision_cycle_id is None
