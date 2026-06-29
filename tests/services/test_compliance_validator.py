from __future__ import annotations

from datetime import datetime, timezone

from agent_trading.services.compliance_validator import (
    ComplianceValidationInput,
    evaluate_compliance_rules,
)
from agent_trading.services.validators import ValidationContext


def test_reconciliation_overlay_flat_buy_is_blocked_by_compliance_validator() -> None:
    result = evaluate_compliance_rules(
        context=ValidationContext(source_type="reconciliation_overlay"),
        validation_input=ComplianceValidationInput(
            source_type="reconciliation_overlay",
            has_position=False,
            intent_action="new_buy",
            account_ref="paper",
            symbol="005930",
            market="KRX",
            strategy_id="strat-1",
            client_order_id="cid-1",
            side="buy",
            order_type="limit",
            quantity="1",
            price="50000",
        ),
    )

    assert result.rule_set_version == "compliance_validator_v1"
    assert result.is_blocking is True
    assert result.stop_reason == "source_policy_buy_blocked"
    assert result.blocking_rule_codes == (
        "source_policy_buy_blocked",
        "policy_reconciliation_overlay_flat_buy_blocked",
    )
    assert result.rule_results["validator_bundle"] == "compliance_validator_v1"
    assert (
        result.rule_results["rule_outcomes"]["reconciliation_overlay_flat_buy_blocked"][
            "passed"
        ]
        is False
    )


def test_limit_order_without_price_is_blocked_by_compliance_validator() -> None:
    result = evaluate_compliance_rules(
        context=ValidationContext(source_type="core"),
        validation_input=ComplianceValidationInput(
            source_type="core",
            has_position=False,
            intent_action="other",
            account_ref="paper",
            symbol="005930",
            market="KRX",
            strategy_id="strat-1",
            client_order_id="cid-1",
            side="buy",
            order_type="limit",
            quantity="1",
            price=None,
        ),
    )

    assert result.rule_set_version == "compliance_validator_v1"
    assert result.is_blocking is True
    assert "compliance_invalid_order_shape" in result.blocking_rule_codes
    assert result.rule_results["validator_bundle"] == "compliance_validator_v1"


def test_restricted_symbol_and_unsupported_order_type_are_blocked() -> None:
    result = evaluate_compliance_rules(
        context=ValidationContext(source_type="core"),
        validation_input=ComplianceValidationInput(
            source_type="core",
            has_position=False,
            intent_action="other",
            account_ref="paper",
            symbol="005930",
            market="KRX",
            strategy_id="strat-1",
            client_order_id="cid-1",
            side="buy",
            order_type="stop",
            quantity="1",
            price="50000",
            blocked_reason_codes=("operator_blocked_symbol",),
            supported_order_types=("market", "limit"),
        ),
    )

    assert result.is_blocking is True
    assert "compliance_restricted_symbol_fallback" in result.blocking_rule_codes
    assert "compliance_broker_capability_blocked" in result.blocking_rule_codes


def test_status_snapshot_blocks_new_buy_before_fallback() -> None:
    result = evaluate_compliance_rules(
        context=ValidationContext(source_type="core"),
        validation_input=ComplianceValidationInput(
            source_type="core",
            has_position=False,
            intent_action="new_buy",
            account_ref="paper",
            symbol="005930",
            market="KRX",
            strategy_id="strat-1",
            client_order_id="cid-1",
            side="buy",
            order_type="limit",
            quantity="1",
            price="50000",
            tr_stop_yn="Y",
            status_reason_codes=("trading_halt",),
            status_snapshot_at=datetime.now(timezone.utc),
            status_source_type="kis_stock_basic_info",
        ),
    )

    assert result.is_blocking is True
    assert "compliance_instrument_status_blocked" in result.blocking_rule_codes


def test_status_snapshot_sell_override_keeps_position_reduction_open() -> None:
    result = evaluate_compliance_rules(
        context=ValidationContext(source_type="held_position"),
        validation_input=ComplianceValidationInput(
            source_type="held_position",
            has_position=True,
            intent_action="other",
            account_ref="paper",
            symbol="005930",
            market="KRX",
            strategy_id="strat-1",
            client_order_id="cid-1",
            side="sell",
            order_type="market",
            quantity="10",
            tr_stop_yn="Y",
            status_reason_codes=("trading_halt",),
            status_snapshot_at=datetime.now(timezone.utc),
            status_source_type="kis_stock_basic_info",
        ),
    )

    assert result.is_blocking is False
