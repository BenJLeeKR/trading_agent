"""Tests for translation.py — pure transform functions."""
from decimal import Decimal
from agent_trading.services.translation import (
    resolve_decision_type, resolve_order_side, resolve_entry_style,
    decimal_or_none, calculate_max_order_value,
)
from agent_trading.domain.enums import DecisionType, OrderSide, EntryStyle


class TestResolveDecisionType:
    def test_buy(self) -> None:
        assert resolve_decision_type("buy") == DecisionType.BUY
        assert resolve_decision_type("BUY") == DecisionType.BUY
        assert resolve_decision_type("strong_buy") == DecisionType.BUY

    def test_sell(self) -> None:
        assert resolve_decision_type("sell") == DecisionType.SELL
        assert resolve_decision_type("strong_sell") == DecisionType.SELL

    def test_hold(self) -> None:
        assert resolve_decision_type("hold") == DecisionType.HOLD
        assert resolve_decision_type("neutral") == DecisionType.HOLD
        assert resolve_decision_type("review") == DecisionType.HOLD

    def test_close(self) -> None:
        assert resolve_decision_type("close") == DecisionType.CLOSE

    def test_reduce(self) -> None:
        assert resolve_decision_type("reduce") == DecisionType.REDUCE

    def test_approve(self) -> None:
        assert resolve_decision_type("approve") == DecisionType.APPROVE
        assert resolve_decision_type("APPROVE") == DecisionType.APPROVE
        assert resolve_decision_type("Approve") == DecisionType.APPROVE

    def test_exit(self) -> None:
        assert resolve_decision_type("exit") == DecisionType.EXIT
        assert resolve_decision_type("EXIT") == DecisionType.EXIT

    def test_watch(self) -> None:
        assert resolve_decision_type("watch") == DecisionType.WATCH
        assert resolve_decision_type("WATCH") == DecisionType.WATCH

    def test_reject(self) -> None:
        assert resolve_decision_type("reject") == DecisionType.REJECT
        assert resolve_decision_type("REJECT") == DecisionType.REJECT

    def test_none_fallback(self) -> None:
        assert resolve_decision_type(None) == DecisionType.HOLD

    def test_unknown_fallback(self) -> None:
        assert resolve_decision_type("garbage") == DecisionType.HOLD


class TestResolveOrderSide:
    def test_buy_from_decision(self) -> None:
        assert resolve_order_side("buy", OrderSide.BUY) == OrderSide.BUY

    def test_sell_from_decision(self) -> None:
        assert resolve_order_side("sell", OrderSide.BUY) == OrderSide.SELL

    def test_fallback(self) -> None:
        assert resolve_order_side("hold", OrderSide.BUY) == OrderSide.BUY

    def test_none_fallback(self) -> None:
        assert resolve_order_side(None, OrderSide.SELL) == OrderSide.SELL

    def test_empty_string_fallback_to_sell(self) -> None:
        """2026-08-21: FDC(held_position)의 실제 fallback 출력값은
        ``None``이 아니라 빈 문자열(``""``)이다(``FinalDecisionComposerOutput``
        의 dataclass 기본값). held_position의 기본 ``request.side``가
        ``SELL``로 바뀐 뒤, FDC output이 비어 있으면 이 SELL이 그대로
        최종 side로 살아남아야 한다 — 실제 프로덕션 값 형태(빈 문자열)로
        정확히 재현해 검증한다."""
        assert resolve_order_side("", OrderSide.SELL) == OrderSide.SELL

    def test_explicit_sell_from_fdc_wins_over_sell_fallback(self) -> None:
        """held_position REDUCE/EXIT 정상 경로 회귀 확인: FDC가 명시적으로
        ``SELL``을 반환하면(성공 경로) fallback 값과 무관하게 그 값이
        그대로 사용돼야 한다 — 이번 수정이 이 경로를 바꾸지 않았음을
        확인."""
        assert resolve_order_side("SELL", OrderSide.SELL) == OrderSide.SELL
        assert resolve_order_side("SELL", OrderSide.BUY) == OrderSide.SELL


class TestResolveEntryStyle:
    def test_limit(self) -> None:
        assert resolve_entry_style("limit", EntryStyle.MARKET) == EntryStyle.LIMIT

    def test_market(self) -> None:
        assert resolve_entry_style("market", EntryStyle.LIMIT) == EntryStyle.MARKET

    def test_none_fallback(self) -> None:
        assert resolve_entry_style(None, EntryStyle.LIMIT) == EntryStyle.LIMIT

    def test_unknown_fallback(self) -> None:
        assert resolve_entry_style("garbage", EntryStyle.MARKET) == EntryStyle.MARKET


class TestDecimalOrNone:
    def test_decimal(self) -> None:
        assert decimal_or_none("123.45") == Decimal("123.45")

    def test_none(self) -> None:
        assert decimal_or_none(None) is None

    def test_invalid(self) -> None:
        assert decimal_or_none("abc") is None

    def test_int(self) -> None:
        assert decimal_or_none(42) == Decimal("42")


class TestCalculateMaxOrderValue:
    def test_positive(self) -> None:
        assert calculate_max_order_value(Decimal("100"), Decimal("5")) == Decimal("500")

    def test_zero(self) -> None:
        assert calculate_max_order_value(Decimal("0"), Decimal("5")) == Decimal("0")

    def test_negative_clamped(self) -> None:
        assert calculate_max_order_value(Decimal("-100"), Decimal("5")) == Decimal("0")
