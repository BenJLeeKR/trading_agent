from __future__ import annotations

from agent_trading.services.source_policy import (
    allowed_fdc_decision_types,
    evaluate_action_envelope,
)


def test_reconciliation_overlay_flat_buy_is_blocked() -> None:
    result = evaluate_action_envelope(
        source_type="reconciliation_overlay",
        has_position=False,
    )

    assert result.allow_new_buy is False
    assert result.reason_codes == ("policy_reconciliation_overlay_flat_buy_blocked",)


def test_reconciliation_overlay_with_position_does_not_block_new_buy_by_itself() -> None:
    result = evaluate_action_envelope(
        source_type="reconciliation_overlay",
        has_position=True,
    )

    assert result.allow_new_buy is True


def test_held_position_buy_is_always_blocked() -> None:
    result = evaluate_action_envelope(
        source_type="held_position",
        has_position=True,
    )

    assert result.allow_new_buy is False
    assert result.reason_codes == ("policy_held_position_buy_blocked",)


def test_allowed_fdc_decision_types_held_position_excludes_buy_lane() -> None:
    """held_position은 APPROVE/BUY/SELL이 제외되고 REDUCE/EXIT/HOLD/WATCH만
    허용돼야 한다(2026-08-18 KST — FDC 선택지 제한)."""
    allowed = allowed_fdc_decision_types("held_position")

    assert allowed == ("REDUCE", "EXIT", "HOLD", "WATCH")
    assert "APPROVE" not in allowed
    assert "BUY" not in allowed
    assert "SELL" not in allowed


def test_allowed_fdc_decision_types_core_unchanged() -> None:
    """core/기타 source_type은 기존 7종 전체를 그대로 허용해야 한다."""
    for source_type in ("core", "event_overlay", "market_overlay", None):
        allowed = allowed_fdc_decision_types(source_type)
        assert allowed == ("APPROVE", "BUY", "SELL", "HOLD", "WATCH", "EXIT", "REDUCE")


def test_allowed_fdc_decision_types_case_insensitive() -> None:
    assert allowed_fdc_decision_types("HELD_POSITION") == (
        "REDUCE", "EXIT", "HOLD", "WATCH",
    )
