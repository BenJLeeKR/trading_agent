from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.rate_limit import RateLimitBudgetManager
from agent_trading.domain.enums import BrokerName, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest


@pytest.fixture
def adapter() -> KoreaInvestmentAdapter:
    budget = RateLimitBudgetManager()
    rest_client = KISRestClient(
        api_key="dummy",
        api_secret="dummy",
        account_number="12345678",
        account_product_code="01",
        budget_manager=budget,
    )
    return KoreaInvestmentAdapter(rest_client=rest_client)


@pytest.fixture
def base_request() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-001",
        correlation_id="corr-001",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )


class TestValidateOrderRequest:
    """Tests for ``KoreaInvestmentAdapter._validate_order_request()``."""

    def test_valid_request_returns_no_errors(self, adapter, base_request):
        errors = adapter._validate_order_request(base_request)
        assert errors == []

    def test_price_below_lower_band(self, adapter, base_request):
        request = base_request
        request = SubmitOrderRequest(
            **{**{f.name: getattr(request, f.name) for f in request.__dataclass_fields__.values()},
                "price_band_lower": Decimal("55000")}
        )
        # Reconstruct properly
        request = SubmitOrderRequest(
            account_ref=base_request.account_ref,
            client_order_id=base_request.client_order_id,
            correlation_id=base_request.correlation_id,
            strategy_id=base_request.strategy_id,
            symbol=base_request.symbol,
            market=base_request.market,
            side=base_request.side,
            order_type=base_request.order_type,
            quantity=base_request.quantity,
            price=Decimal("50000"),
            time_in_force=base_request.time_in_force,
            price_band_lower=Decimal("55000"),
            price_band_upper=Decimal("60000"),
        )
        errors = adapter._validate_order_request(request)
        assert len(errors) == 1
        assert "below lower band" in errors[0]

    def test_price_above_upper_band(self, adapter, base_request):
        request = SubmitOrderRequest(
            account_ref=base_request.account_ref,
            client_order_id=base_request.client_order_id,
            correlation_id=base_request.correlation_id,
            strategy_id=base_request.strategy_id,
            symbol=base_request.symbol,
            market=base_request.market,
            side=base_request.side,
            order_type=base_request.order_type,
            quantity=base_request.quantity,
            price=Decimal("65000"),
            time_in_force=base_request.time_in_force,
            price_band_lower=Decimal("50000"),
            price_band_upper=Decimal("60000"),
        )
        errors = adapter._validate_order_request(request)
        assert len(errors) == 1
        assert "above upper band" in errors[0]

    def test_negative_max_slippage(self, adapter, base_request):
        request = SubmitOrderRequest(
            account_ref=base_request.account_ref,
            client_order_id=base_request.client_order_id,
            correlation_id=base_request.correlation_id,
            strategy_id=base_request.strategy_id,
            symbol=base_request.symbol,
            market=base_request.market,
            side=base_request.side,
            order_type=OrderType.MARKET,
            quantity=base_request.quantity,
            time_in_force=base_request.time_in_force,
            max_slippage_bps=0,
        )
        errors = adapter._validate_order_request(request)
        assert len(errors) == 1
        assert "max_slippage_bps must be positive" in errors[0]

    def test_market_order_without_partial_fill(self, adapter, base_request):
        request = SubmitOrderRequest(
            account_ref=base_request.account_ref,
            client_order_id=base_request.client_order_id,
            correlation_id=base_request.correlation_id,
            strategy_id=base_request.strategy_id,
            symbol=base_request.symbol,
            market=base_request.market,
            side=base_request.side,
            order_type=OrderType.MARKET,
            quantity=base_request.quantity,
            time_in_force=base_request.time_in_force,
            allow_partial_fill=False,
        )
        errors = adapter._validate_order_request(request)
        assert len(errors) == 1
        assert "allow_partial_fill=False" in errors[0]

    def test_multiple_validation_errors(self, adapter, base_request):
        request = SubmitOrderRequest(
            account_ref=base_request.account_ref,
            client_order_id=base_request.client_order_id,
            correlation_id=base_request.correlation_id,
            strategy_id=base_request.strategy_id,
            symbol=base_request.symbol,
            market=base_request.market,
            side=base_request.side,
            order_type=OrderType.MARKET,
            quantity=base_request.quantity,
            price=Decimal("70000"),
            time_in_force=base_request.time_in_force,
            price_band_lower=Decimal("50000"),
            price_band_upper=Decimal("60000"),
            max_slippage_bps=0,
            allow_partial_fill=False,
        )
        errors = adapter._validate_order_request(request)
        assert len(errors) >= 2


class TestNormalizeSubmitResult:
    """Tests for ``KoreaInvestmentAdapter._normalize_submit_result()``."""

    def test_normal_accepted_result(self, adapter):
        from agent_trading.domain.models import SubmitOrderResult

        result = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Order accepted",
        )
        normalized = adapter._normalize_submit_result(result)
        assert normalized.uncertain is False
        assert normalized.requires_reconciliation is False

    def test_missing_broker_order_id_sets_uncertain(self, adapter):
        from agent_trading.domain.models import SubmitOrderResult

        result = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
        )
        normalized = adapter._normalize_submit_result(result)
        assert normalized.uncertain is True

    def test_reconcile_required_sets_flag(self, adapter):
        from agent_trading.domain.models import SubmitOrderResult

        result = SubmitOrderResult(
            accepted=False,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,
            broker_status=OrderStatus.RECONCILE_REQUIRED,
            ack_timestamp=None,
        )
        normalized = adapter._normalize_submit_result(result)
        assert normalized.requires_reconciliation is True

    def test_ambiguous_raw_code_sets_uncertain(self, adapter):
        from agent_trading.domain.models import SubmitOrderResult

        result = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
        )
        normalized = adapter._normalize_submit_result(result)
        assert normalized.uncertain is True

    def test_normalized_status_fallback(self, adapter):
        from agent_trading.domain.models import SubmitOrderResult

        result = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
        )
        normalized = adapter._normalize_submit_result(result)
        assert normalized.normalized_status == OrderStatus.ACKNOWLEDGED
