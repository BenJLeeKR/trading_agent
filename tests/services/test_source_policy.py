from __future__ import annotations

from agent_trading.services.source_policy import evaluate_action_envelope


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
