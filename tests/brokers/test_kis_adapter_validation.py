from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.base import SubscriptionBudget
from agent_trading.brokers.rate_limit import BudgetExhaustedError, RateLimitBudgetManager
from agent_trading.domain.enums import BrokerName, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest, SubmitOrderResult


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


class TestBuildKisAdapterRuntimeWiring:
    """``_build_kis_adapter()`` runtime wiring — budget manager injection."""

    def test_build_kis_adapter_injects_budget_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``_build_kis_adapter()`` creates a ``RateLimitBudgetManager`` and
        passes it to ``KISRestClient``."""
        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import _build_kis_adapter

        monkeypatch.setenv("KIS_APP_KEY", "test-key")
        monkeypatch.setenv("KIS_APP_SECRET", "test-secret")
        monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")
        monkeypatch.setenv("KIS_ENV", "paper")
        monkeypatch.delenv("KIS_REAL_REST_RPS", raising=False)
        monkeypatch.delenv("KIS_PAPER_REST_RPS", raising=False)

        settings = AppSettings()
        adapter = _build_kis_adapter(settings)

        # The adapter's internal REST client should have a budget_manager
        rest_client = adapter._rest
        assert rest_client.budget_manager is not None
        assert isinstance(rest_client.budget_manager, RateLimitBudgetManager)

        # Paper env → conservative bucket capacities
        # order=3 (Fix 3: capacity increased from 1→3)
        snap = rest_client.budget_manager.snapshot()
        assert snap["auth"]["capacity"] == 1
        assert snap["order"]["capacity"] == 3
        assert snap["inquiry"]["capacity"] == 1
        assert snap["market_data"]["capacity"] == 1
        # reconciliation=10 (기존: max(1, int(10 * total)) = max(1, 10) = 10)
        assert snap["reconciliation"]["capacity"] == 10


class TestKisAdapterSubscriptionBudget:
    """``KoreaInvestmentAdapter`` default subscription budget is ``max_subscriptions=41``."""

    def test_default_budget_max_41(self, adapter: KoreaInvestmentAdapter) -> None:
        """Adapter creates ``SubscriptionBudget`` with ``max_subscriptions=41`` by default."""
        budget = adapter._subscription_budget
        assert budget.max_subscriptions == 41
        assert budget.critical_limit == 20
        assert budget.optional_limit == 80
        assert budget.current_critical == 0
        assert budget.current_optional == 0

    def test_explicit_budget_not_overridden(self) -> None:
        """Explicitly provided ``SubscriptionBudget`` is used as-is (not overridden)."""
        budget = RateLimitBudgetManager()
        rest_client = KISRestClient(
            api_key="dummy",
            api_secret="dummy",
            account_number="12345678",
            account_product_code="01",
            budget_manager=budget,
        )
        custom_budget = SubscriptionBudget(max_subscriptions=10, critical_limit=5, optional_limit=5)
        adapter = KoreaInvestmentAdapter(rest_client=rest_client, subscription_budget=custom_budget)
        assert adapter._subscription_budget is custom_budget
        assert adapter._subscription_budget.max_subscriptions == 10
        assert adapter._subscription_budget.critical_limit == 5


class TestAdapterGetQuote:
    """``KoreaInvestmentAdapter.get_quote()`` delegates to ``KISRestClient.get_quote(symbol)``
    (single argument, no ``market``) and correctly maps KIS raw keys to ``Quote`` fields."""

    @pytest.mark.asyncio
    async def test_get_quote_calls_rest_with_symbol_only(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Adapter.get_quote(symbol, market) must call self._rest.get_quote(symbol)
        with only the symbol argument (not market) and map KIS keys correctly."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_quote = AsyncMock(
            return_value={
                "stck_prpr": "15000",
                "stck_bidp": "14900",
                "stck_askp": "15100",
            }
        )
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            quote = await adapter.get_quote("005930", "KRX")
            assert quote.last == Decimal("15000")
            assert quote.bid == Decimal("14900")
            assert quote.ask == Decimal("15100")
            assert quote.symbol == "005930"
            assert quote.market == "KRX"
            mock_rest.get_quote.assert_awaited_once_with("005930")
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_get_quote_empty_response(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Adapter.get_quote() handles empty dict from rest client."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_quote = AsyncMock(return_value={})
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            quote = await adapter.get_quote("005930", "KRX")
            assert quote.last is None
            assert quote.bid is None
            assert quote.ask is None
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_get_quote_stck_prpr_with_comma(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """KIS returns comma-formatted string numbers (e.g. "67,200")."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_quote = AsyncMock(
            return_value={
                "stck_prpr": "67,200",
                "stck_bidp": "67,100",
                "stck_askp": "67,300",
            }
        )
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            quote = await adapter.get_quote("005930", "KRX")
            assert quote.last == Decimal("67200")
            assert quote.bid == Decimal("67100")
            assert quote.ask == Decimal("67300")
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_get_quote_missing_stck_prpr(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Missing stck_prpr key → last is None."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_quote = AsyncMock(
            return_value={"stck_bidp": "14900", "stck_askp": "15100"}
        )
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            quote = await adapter.get_quote("005930", "KRX")
            assert quote.last is None
            assert quote.bid == Decimal("14900")
            assert quote.ask == Decimal("15100")
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_get_quote_stck_prpr_is_none(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """stck_prpr is None → last is None."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_quote = AsyncMock(
            return_value={"stck_prpr": None, "stck_bidp": None, "stck_askp": None}
        )
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            quote = await adapter.get_quote("005930", "KRX")
            assert quote.last is None
            assert quote.bid is None
            assert quote.ask is None
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_get_quote_stck_prpr_invalid(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """stck_prpr is non-numeric → last is None (no crash)."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_quote = AsyncMock(
            return_value={"stck_prpr": "N/A", "stck_bidp": "", "stck_askp": "---"}
        )
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            quote = await adapter.get_quote("005930", "KRX")
            assert quote.last is None
            assert quote.bid is None
            assert quote.ask is None
        finally:
            adapter._rest = original_rest


class TestAdapterGetOrderbook:
    """``KoreaInvestmentAdapter.get_orderbook()`` delegates to
    ``KISRestClient.get_orderbook(symbol)`` (single argument, no ``market``)
    and correctly maps KIS raw keys to ``OrderBook`` fields."""

    @pytest.mark.asyncio
    async def test_get_orderbook_calls_rest_with_symbol_only(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Adapter.get_orderbook(symbol, market) must call
        self._rest.get_orderbook(symbol) with only the symbol argument
        and parse KIS askp/bidp keys into OrderBookLevel tuples."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_orderbook = AsyncMock(
            return_value={
                "bidp1": "50000", "bidp_rsqn1": "10",
                "askp1": "50100", "askp_rsqn1": "5",
            }
        )
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            ob = await adapter.get_orderbook("005930", "KRX")
            assert ob.symbol == "005930"
            assert ob.market == "KRX"
            assert len(ob.bids) == 1
            assert len(ob.asks) == 1
            assert ob.bids[0].price == Decimal("50000")
            assert ob.bids[0].quantity == Decimal("10")
            assert ob.asks[0].price == Decimal("50100")
            assert ob.asks[0].quantity == Decimal("5")
            mock_rest.get_orderbook.assert_awaited_once_with("005930")
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_get_orderbook_empty_response(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Adapter.get_orderbook() handles empty dict from rest client."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_orderbook = AsyncMock(return_value={})
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            ob = await adapter.get_orderbook("005930", "KRX")
            assert len(ob.bids) == 0
            assert len(ob.asks) == 0
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_get_orderbook_partial_levels(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Only levels with both price and quantity are included."""
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.get_orderbook = AsyncMock(
            return_value={
                "bidp1": "50000", "bidp_rsqn1": "10",
                "bidp2": "49900",  # missing bidp_rsqn2 → skip
                "askp1": "50100", "askp_rsqn1": "5",
                "askp2": "50200", "askp_rsqn2": "3",
            }
        )
        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            ob = await adapter.get_orderbook("005930", "KRX")
            assert len(ob.bids) == 1  # level 2 skipped (no quantity)
            assert len(ob.asks) == 2
        finally:
            adapter._rest = original_rest


def _make_sell_request(
    metadata: dict[str, object] | None = None,
) -> SubmitOrderRequest:
    """Helper: create a SELL SubmitOrderRequest with optional metadata."""
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-held-sell",
        correlation_id="corr-held",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        metadata=metadata or {},
    )


def _make_buy_request(
    metadata: dict[str, object] | None = None,
) -> SubmitOrderRequest:
    """Helper: create a BUY SubmitOrderRequest with optional metadata."""
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-held-buy",
        correlation_id="corr-held",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        metadata=metadata or {},
    )


class TestIsHeldPositionSell:
    """``KoreaInvestmentAdapter._is_held_position_sell()`` 회귀 방지 테스트.

    ``OrderSide`` 이름이 제대로 참조되는지도 함께 검증한다
    (``NameError: name 'OrderSide' is not defined`` 재발 방지).
    """

    def test_is_held_position_sell_true(self, adapter: KoreaInvestmentAdapter) -> None:
        """SELL + metadata={"source_type": "held_position"} -> True"""
        request = _make_sell_request(metadata={"source_type": "held_position"})
        assert adapter._is_held_position_sell(request) is True

    def test_is_held_position_sell_buy_false(self, adapter: KoreaInvestmentAdapter) -> None:
        """BUY + metadata={"source_type": "held_position"} -> False"""
        request = _make_buy_request(metadata={"source_type": "held_position"})
        assert adapter._is_held_position_sell(request) is False

    def test_is_held_position_sell_no_metadata_false(self, adapter: KoreaInvestmentAdapter) -> None:
        """SELL + metadata=None -> False"""
        request = _make_sell_request(metadata=None)
        assert adapter._is_held_position_sell(request) is False

    def test_is_held_position_sell_core_source_false(self, adapter: KoreaInvestmentAdapter) -> None:
        """SELL + metadata={"source_type": "core"} -> False"""
        request = _make_sell_request(metadata={"source_type": "core"})
        assert adapter._is_held_position_sell(request) is False


class TestSubmitOrderBudgetExhausted:
    """``KoreaInvestmentAdapter.submit_order()``의 ``BudgetExhaustedError`` 분기 테스트.

    ``_is_held_position_sell()``이 ``submit_order()`` 경로에서
    올바르게 호출되는지 검증한다.
    """

    @pytest.mark.asyncio
    async def test_submit_order_budget_exhausted_returns_reconcile(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """일반 주문(held_position sell 아님)에서 BudgetExhaustedError 발생 시
        ``requires_reconciliation=True``인 결과를 반환한다."""
        request = _make_sell_request(metadata={"source_type": "core"})
        mock_rest = AsyncMock(spec=KISRestClient)
        mock_rest.submit_order = AsyncMock(side_effect=BudgetExhaustedError("budget exhausted"))
        mock_rest.get_positions = AsyncMock(return_value=[])
        mock_rest.get_cash_balance = AsyncMock(return_value={})

        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            result = await adapter.submit_order(request)
            assert result.accepted is False
            assert result.requires_reconciliation is True
            assert result.raw_code == "BUDGET_EXHAUSTED"
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_submit_order_budget_exhausted_held_position_sell_retry(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Held-position sell에서 BudgetExhaustedError 발생 시
        reserved budget lane으로 재시도하고 성공 결과를 반환한다."""
        request = _make_sell_request(metadata={"source_type": "held_position"})

        mock_rest = AsyncMock(spec=KISRestClient)
        # First call raises, second call succeeds (reserved budget lane)
        mock_rest.submit_order = AsyncMock(
            side_effect=[
                BudgetExhaustedError("budget exhausted"),
                SubmitOrderResult(
                    accepted=True,
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    client_order_id=request.client_order_id,
                    broker_order_id="RESERVED-001",
                    broker_status=OrderStatus.ACKNOWLEDGED,
                    ack_timestamp=None,
                ),
            ]
        )

        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            result = await adapter.submit_order(request)
            # Reserved budget retry should succeed
            assert result.accepted is True
            assert mock_rest.submit_order.call_count == 2
        finally:
            adapter._rest = original_rest

    @pytest.mark.asyncio
    async def test_submit_order_budget_exhausted_held_position_reserve_also_exhausted(
        self, adapter: KoreaInvestmentAdapter
    ) -> None:
        """Held-position sell에서 reserved budget lane도 소진된 경우
        ``requires_reconciliation=True``인 결과를 반환한다."""
        request = _make_sell_request(metadata={"source_type": "held_position"})

        mock_rest = AsyncMock(spec=KISRestClient)
        # Both calls raise BudgetExhaustedError
        mock_rest.submit_order = AsyncMock(
            side_effect=BudgetExhaustedError("budget exhausted")
        )

        original_rest = adapter._rest
        adapter._rest = mock_rest
        try:
            result = await adapter.submit_order(request)
            assert result.accepted is False
            assert result.requires_reconciliation is True
            assert result.raw_code == "BUDGET_EXHAUSTED"
        finally:
            adapter._rest = original_rest
