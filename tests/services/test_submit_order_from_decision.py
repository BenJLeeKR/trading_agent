"""Tests for REDUCE/EXIT decision → sell SubmitOrderRequest conversion.

Verifies that ``build_submit_order_request_from_decision()`` correctly
propagates the ``side`` field from ``OrderIntent.request``, which is
set by ``assemble()`` based on FDC's ``side`` output.

The side override logic (REDUCE/EXIT + side="sell" → OrderSide.SELL)
lives in ``DecisionOrchestratorService.assemble()``, not in
``build_submit_order_request_from_decision()``.  These tests verify
that the translation function faithfully passes through whatever
``side`` was set on the intent's request.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4, UUID

import pytest

from agent_trading.domain.enums import OrderSide, DecisionType
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.decision_orchestrator import (
    build_submit_order_request_from_decision,
    OrderIntent,
    AssembledContext,
    AIDecisionInputs,
)
from agent_trading.services.sizing_engine import SizingResult


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_submit_request(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("10"),
    symbol: str = "AAPL",
    market: str = "NASDAQ",
) -> SubmitOrderRequest:
    """Build a minimal ``SubmitOrderRequest`` for testing."""
    return SubmitOrderRequest(
        account_ref="test-account",
        client_order_id="test-client-order-id",
        correlation_id="test-correlation-id",
        strategy_id="test-strategy",
        symbol=symbol,
        market=market,
        side=side,
        order_type="market",
        quantity=quantity,
    )


def _make_intent(
    *,
    decision_type: str = "REDUCE",
    side: str = "sell",
    request_side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("10"),
) -> OrderIntent:
    """Build an ``OrderIntent`` with the given AI decision inputs and request side.

    Parameters
    ----------
    decision_type
        The FDC decision type (e.g. ``"REDUCE"``, ``"EXIT"``, ``"BUY"``).
    side
        The FDC ``side`` field (e.g. ``"sell"``, ``"buy"``, ``""``).
    request_side
        The ``SubmitOrderRequest.side`` as set by ``assemble()``
        (after any REDUCE/EXIT override).
    quantity
        The order quantity.
    """
    ctx_id = uuid4()
    return OrderIntent(
        decision_context_id=ctx_id,
        order_intent_id=uuid4(),
        request=_make_submit_request(side=request_side, quantity=quantity),
        context=AssembledContext(),
        ai_backend_inputs=AIDecisionInputs(
            decision_type=decision_type,
            side=side,
        ),
    )


# ── Tests ────────────────────────────────────────────────────────────────


class TestBuildSubmitOrderRequestSide:
    """``build_submit_order_request_from_decision()`` side pass-through."""

    def test_passes_through_sell_side(self) -> None:
        """``request.side == OrderSide.SELL`` → result.side == OrderSide.SELL."""
        intent = _make_intent(
            decision_type="REDUCE", side="sell", request_side=OrderSide.SELL
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.SELL, (
            f"Expected SELL pass-through, got {result.side}"
        )

    def test_passes_through_buy_side(self) -> None:
        """``request.side == OrderSide.BUY`` → result.side == OrderSide.BUY."""
        intent = _make_intent(
            decision_type="BUY", side="buy", request_side=OrderSide.BUY
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.BUY, (
            f"Expected BUY pass-through, got {result.side}"
        )

    def test_reduce_sell_with_zero_quantity(self) -> None:
        """REDUCE + sell + zero quantity → returns None (skipped)."""
        intent = _make_intent(
            decision_type="REDUCE",
            side="sell",
            request_side=OrderSide.SELL,
            quantity=Decimal("0"),
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is None, "Expected None for zero-quantity order"

    def test_exit_sell_with_positive_quantity(self) -> None:
        """EXIT + sell + positive quantity → result.side == OrderSide.SELL."""
        intent = _make_intent(
            decision_type="EXIT",
            side="sell",
            request_side=OrderSide.SELL,
            quantity=Decimal("50"),
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.SELL, (
            f"Expected SELL for EXIT+sell, got {result.side}"
        )
        assert result.quantity == Decimal("50")

    def test_approve_buy_preserves_buy(self) -> None:
        """APPROVE + buy → result.side == OrderSide.BUY."""
        intent = _make_intent(
            decision_type="APPROVE", side="buy", request_side=OrderSide.BUY
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.BUY, (
            f"Expected BUY for APPROVE+buy, got {result.side}"
        )

    def test_reduce_empty_side_fallback(self) -> None:
        """REDUCE + side="" (empty) → original side preserved (BUY)."""
        intent = _make_intent(
            decision_type="REDUCE", side="", request_side=OrderSide.BUY
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.BUY, (
            f"Expected BUY preserved for empty side, got {result.side}"
        )

    def test_reduce_SELL_uppercase_conversion(self) -> None:
        """REDUCE + side="SELL" (uppercase from FDC) → SELL."""
        intent = _make_intent(
            decision_type="REDUCE", side="SELL", request_side=OrderSide.SELL
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.SELL, (
            f"Expected SELL for REDUCE+SELL (uppercase), got {result.side}"
        )

    def test_exit_SELL_uppercase_conversion(self) -> None:
        """EXIT + side="SELL" (uppercase from FDC) → SELL."""
        intent = _make_intent(
            decision_type="EXIT", side="SELL", request_side=OrderSide.SELL
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.SELL, (
            f"Expected SELL for EXIT+SELL (uppercase), got {result.side}"
        )
