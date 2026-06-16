from __future__ import annotations

from agent_trading.domain.enums import OrderSide


def is_held_position_sell_path(
    *,
    source_type: str | None,
    decision_type: str | None,
    side: OrderSide | str | None,
) -> bool:
    """Return whether the path is a held-position risk-reducing SELL.

    Canonical definition:
    - source_type == ``held_position``
    - decision_type in ``REDUCE`` / ``EXIT``
    - side == ``SELL``
    """
    normalized_source_type = (source_type or "").strip().lower()
    normalized_decision_type = (decision_type or "").strip().lower()
    normalized_side = getattr(side, "value", side)
    normalized_side = (normalized_side or "").strip().lower()
    return (
        normalized_source_type == "held_position"
        and normalized_decision_type in ("reduce", "exit")
        and normalized_side == "sell"
    )
