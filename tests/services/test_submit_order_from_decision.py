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
    metadata: dict[str, object] | None = None,
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
        metadata=metadata,
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
            expected_return_bps=Decimal("50.00"),
            expected_downside_bps=Decimal("15.00"),
            net_expected_value_bps=Decimal("35.00"),
            final_trade_score=Decimal("0.75"),
            minimum_required_edge_bps=Decimal("5.00"),
            edge_after_cost_bps=Decimal("20.00"),
            estimated_round_trip_cost_bps=Decimal("7.00"),
            slippage_buffer_bps=Decimal("8.00"),
            expected_value_gate_passed=True,
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

    def test_held_position_buy_is_not_submitted(self) -> None:
        """held_position + BUY side는 제출 request를 만들지 않아야 함."""
        ctx_id = uuid4()
        intent = OrderIntent(
            decision_context_id=ctx_id,
            order_intent_id=uuid4(),
            request=_make_submit_request(
                side=OrderSide.BUY,
                metadata={"source_type": "held_position"},
            ),
            context=AssembledContext(),
            ai_backend_inputs=AIDecisionInputs(
                decision_type="APPROVE",
                side="buy",
                expected_return_bps=Decimal("50.00"),
                expected_downside_bps=Decimal("15.00"),
                net_expected_value_bps=Decimal("35.00"),
                final_trade_score=Decimal("0.75"),
                minimum_required_edge_bps=Decimal("10.00"),
                edge_after_cost_bps=Decimal("18.00"),
                estimated_round_trip_cost_bps=Decimal("9.00"),
                slippage_buffer_bps=Decimal("8.00"),
                expected_value_gate_passed=True,
            ),
        )
        assert build_submit_order_request_from_decision(intent) is None

    def test_held_position_reduce_sell_still_submits(self) -> None:
        """held_position + SELL side는 기존대로 제출 가능해야 함."""
        ctx_id = uuid4()
        intent = OrderIntent(
            decision_context_id=ctx_id,
            order_intent_id=uuid4(),
            request=_make_submit_request(
                side=OrderSide.SELL,
                metadata={"source_type": "held_position"},
            ),
            context=AssembledContext(),
            ai_backend_inputs=AIDecisionInputs(
                decision_type="REDUCE",
                side="sell",
                expected_return_bps=Decimal("30.00"),
                expected_downside_bps=Decimal("10.00"),
                net_expected_value_bps=Decimal("20.00"),
                final_trade_score=Decimal("0.62"),
                minimum_required_edge_bps=Decimal("5.00"),
                edge_after_cost_bps=Decimal("9.00"),
                estimated_round_trip_cost_bps=Decimal("5.00"),
                slippage_buffer_bps=Decimal("6.00"),
                expected_value_gate_passed=True,
            ),
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.SELL

    def test_reduce_sell_with_failed_expected_value_anchor_returns_none(self) -> None:
        """REDUCE/SELL은 expected_value_anchor 실패 시 submit 차단되어야 함."""
        intent = OrderIntent(
            decision_context_id=uuid4(),
            order_intent_id=uuid4(),
            request=_make_submit_request(
                side=OrderSide.SELL,
                metadata={
                    "source_type": "held_position",
                    "expected_value_anchor": {
                        "anchor_required": True,
                        "anchor_passed": False,
                        "decision_type": "REDUCE",
                    },
                },
            ),
            context=AssembledContext(),
            ai_backend_inputs=AIDecisionInputs(
                decision_type="REDUCE",
                side="sell",
                expected_return_bps=Decimal("30.00"),
                expected_downside_bps=Decimal("10.00"),
                net_expected_value_bps=Decimal("20.00"),
                final_trade_score=Decimal("0.62"),
                minimum_required_edge_bps=Decimal("5.00"),
                edge_after_cost_bps=Decimal("9.00"),
                estimated_round_trip_cost_bps=Decimal("5.00"),
                slippage_buffer_bps=Decimal("6.00"),
                expected_value_gate_passed=True,
            ),
        )
        assert build_submit_order_request_from_decision(intent) is None

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
