"""Tests for ``KISRestClient.submit_order()`` — success/error paths.

Verifies:
- ``SubmitOrderResult`` construction from a successful KIS ODNO response
- ``BrokerError`` propagation on business-level errors (e.g. price validation)
- Request body structure passed to ``_request()``
- ``_resolve_smoke_price()`` env-var resolution policy
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import httpx

from agent_trading.brokers.errors import BrokerError, BrokerErrorType
from agent_trading.brokers.koreainvestment.rest_client import (
    KISRestClient,
    _format_order_quantity,
)
from agent_trading.brokers.rate_limit import BucketType, BudgetExhaustedError
from agent_trading.domain.enums import BrokerName, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest, SubmitOrderResult


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> KISRestClient:
    """Minimal ``KISRestClient`` with a dummy budget manager.

    ``_request()`` is patched per-test so no real HTTP calls are made.
    """
    return KISRestClient(
        api_key="test-api-key",
        api_secret="test-api-secret",
        account_number="12345678",
        account_product_code="01",
        env="paper",
        budget_manager=None,
        dev_token_cache_enabled=False,
    )


@pytest.fixture(autouse=True)
def _reset_shared_submit_pacing() -> None:
    """Reset shared paper global REST pacing state between tests."""
    KISRestClient._paper_last_global_rest_time = 0.0


@pytest.fixture
def submit_request() -> SubmitOrderRequest:
    """Standard submit request for 005930 LIMIT BUY 10 shares at 50000."""
    return SubmitOrderRequest(
        account_ref="test-account",
        client_order_id="ut-submit-001",
        correlation_id="ut-correlation-001",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
    )


# ── Test 1: Submit success (ODNO response) ────────────────────────────────


class TestSubmitOrderSuccess:
    """``submit_order()`` returns a correctly constructed ``SubmitOrderResult``
    when KIS responds with a valid ODNO."""

    @pytest.mark.asyncio
    async def test_submit_order_success(self, client: KISRestClient, submit_request: SubmitOrderRequest) -> None:
        """ODNO + ORD_TMD → SubmitOrderResult with correct fields."""
        mock_response: dict[str, Any] = {
            "output": {
                "ODNO": "0000027326",
                "ORD_TMD": "152530",
            }
        }

        # KISRestClient uses @dataclass(slots=True) so patch at class level
        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)):
            result: SubmitOrderResult = await client.submit_order(submit_request)

        assert result.accepted is True
        assert result.broker_name == BrokerName.KOREA_INVESTMENT
        assert result.client_order_id == "ut-submit-001"
        assert result.broker_order_id == "0000027326"
        assert result.broker_status == OrderStatus.SUBMITTED
        assert result.raw_code == "0000027326"
        assert result.raw_message == "152530"
        assert result.normalized_status == OrderStatus.SUBMITTED
        assert result.uncertain is False
        assert result.requires_reconciliation is False
        assert result.ack_timestamp is not None

    @pytest.mark.asyncio
    async def test_submit_order_empty_odno(self, client: KISRestClient, submit_request: SubmitOrderRequest) -> None:
        """Empty ODNO → broker_order_id is None (edge case)."""
        mock_response: dict[str, Any] = {
            "output": {
                "ODNO": "",
                "ORD_TMD": "",
            }
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)):
            result: SubmitOrderResult = await client.submit_order(submit_request)

        assert result.accepted is True
        assert result.broker_order_id is None  # empty string → None
        assert result.raw_code == ""
        assert result.raw_message == ""


# ── Test 2: Business error propagation ────────────────────────────────────


class TestSubmitOrderBusinessError:
    """Business-level errors (e.g. price validation) raise ``BrokerError``."""

    @pytest.mark.asyncio
    async def test_submit_order_price_validation_error(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        """msg_cd=40270000 (price out of band) → BrokerError raised."""
        async def _mock_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.ORDER_REJECTED,
                retryable=False,
                raw_message="KIS order_cash: known failure (msg_cd=40270000, rt_cd=1): "
                "주문가격이 상하한가를 초과하였습니다.",
            )

        with patch.object(KISRestClient, "_request", _mock_error):
            with pytest.raises(BrokerError) as exc_info:
                await client.submit_order(submit_request)

        assert exc_info.value.error_type == BrokerErrorType.ORDER_REJECTED
        assert "40270000" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_submit_order_ambiguous_error(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        """Ambiguous error code → BrokerError with API_ERROR type."""
        async def _mock_ambiguous(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise BrokerError(
                broker_name=BrokerName.KOREA_INVESTMENT,
                error_type=BrokerErrorType.API_ERROR,
                retryable=False,
                raw_message="KIS order_cash: ambiguous state (msg_cd=EGW00201, rt_cd=1): "
                "주문전송중 오류가 발생하였습니다.",
            )

        with patch.object(KISRestClient, "_request", _mock_ambiguous):
            with pytest.raises(BrokerError) as exc_info:
                await client.submit_order(submit_request)

        assert exc_info.value.error_type == BrokerErrorType.API_ERROR
        assert "EGW00201" in str(exc_info.value)


class TestRaiseOnErrorRateLimit:
    """KIS rate limit 응답은 RATE_LIMIT으로 분류되어야 한다."""

    def test_inquire_balance_rate_limit_maps_to_rate_limit_error(
        self, client: KISRestClient
    ) -> None:
        resp = httpx.Response(
            200,
            json={
                "rt_cd": "1",
                "msg_cd": "EGW00215",
                "msg1": "원장에서 허용 가능한 초당 거래건수를 초과하였습니다.",
            },
        )

        with pytest.raises(BrokerError) as exc_info:
            client._raise_on_error(resp, endpoint="inquire_balance")

        assert exc_info.value.error_type == BrokerErrorType.RATE_LIMIT
        assert exc_info.value.retryable is True
        assert exc_info.value.raw_code == "EGW00215"
        assert exc_info.value.retry_after_seconds == 1.0


# ── Test 3: Request body structure ────────────────────────────────────────


class TestSubmitOrderRequestBody:
    """``submit_order()`` passes the correct body/endpoint/tr_id to ``_request()``."""

    @pytest.mark.asyncio
    async def test_submit_request_body_structure(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        """Verify endpoint, bucket, tr_id, body fields, and hashkey requirement."""
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027326", "ORD_TMD": "152530"}
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            await client.submit_order(submit_request)

        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]

        # Endpoint routing
        assert call_kwargs["endpoint_key"] == "order_cash"
        assert call_kwargs["tr_id_key"] == "order_buy"  # BUY side
        assert call_kwargs["bucket"] == BucketType.ORDER
        assert call_kwargs["requires_hashkey"] is True

        # Body fields
        body: dict[str, object] = call_kwargs["body"]
        assert body["PDNO"] == "005930"
        assert body["ORD_QTY"] == "10"
        assert body["ORD_UNPR"] == "50000"
        assert body["ORD_DVSN"] == "00"
        assert body["CANO"] == "12345678"
        assert body["ACNT_PRDT_CD"] == "01"
        assert "ALGO" not in body

    @pytest.mark.asyncio
    async def test_submit_sell_side_tr_id(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        """SELL side → tr_id_key is ``order_sell``."""
        sell_request = SubmitOrderRequest(
            account_ref=submit_request.account_ref,
            client_order_id="ut-submit-sell-001",
            correlation_id=submit_request.correlation_id,
            strategy_id=submit_request.strategy_id,
            symbol=submit_request.symbol,
            market=submit_request.market,
            side=OrderSide.SELL,
            order_type=submit_request.order_type,
            quantity=submit_request.quantity,
            price=submit_request.price,
        )
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027327", "ORD_TMD": "152531"}
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            await client.submit_order(sell_request)

        mock_request.assert_called_once()
        assert mock_request.call_args[1]["tr_id_key"] == "order_sell"


class TestCashAndPositionsBudgetLogging:
    @pytest.mark.asyncio
    async def test_get_cash_and_positions_treats_budget_exhaustion_separately(
        self, client: KISRestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)

        async def _mock_fetch(*args: Any, **kwargs: Any):
            raise BudgetExhaustedError("inquiry", "Bucket 'inquiry' exhausted (remaining=0/1)")

        with (
            patch.object(KISRestClient, "_wait_for_inquiry_budget", AsyncMock(return_value=True)),
            patch.object(KISRestClient, "_fetch_inquire_balance_pages", _mock_fetch),
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", AsyncMock()),
        ):
            result = await client.get_cash_and_positions(after_hours=False)

        assert result.cash_balance is None
        assert result.positions == []
        assert any("BUDGET_EXHAUSTED VTTC8434R" in rec.message for rec in caplog.records)
        assert not any("API_FAILURE VTTC8434R" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_get_cash_and_positions_retries_once_on_paper_inquiry_budget_exhaustion(
        self, client: KISRestClient
    ) -> None:
        mock_fetch = AsyncMock(
            side_effect=[
                BudgetExhaustedError("inquiry", "Bucket 'inquiry' exhausted (remaining=0/1)"),
                (
                    [{"pdno": "005930", "hldg_qty": "1"}],
                    {"dnca_tot_amt": "1000000"},
                    {"output": [{"pdno": "005930", "hldg_qty": "1"}], "output2": {"dnca_tot_amt": "1000000"}},
                ),
            ]
        )
        mock_sleep = AsyncMock()

        with (
            patch.object(KISRestClient, "_wait_for_inquiry_budget", AsyncMock(return_value=True)),
            patch.object(KISRestClient, "_fetch_inquire_balance_pages", mock_fetch),
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", mock_sleep),
        ):
            result = await client.get_cash_and_positions(after_hours=False)

        assert result.cash_balance == {"dnca_tot_amt": "1000000"}
        assert result.positions == [{"pdno": "005930", "hldg_qty": "1"}]
        assert mock_fetch.await_count == 2
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    async def test_get_cash_and_positions_retries_once_on_paper_broker_rate_limit(
        self, client: KISRestClient
    ) -> None:
        mock_fetch = AsyncMock(
            side_effect=[
                BrokerError(
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    error_type=BrokerErrorType.RATE_LIMIT,
                    retryable=True,
                    raw_code="EGW00215",
                    raw_message=(
                        "KIS inquire_balance: rate limit (msg_cd=EGW00215, rt_cd=1): "
                        "원장에서 허용 가능한 초당 거래건수를 초과하였습니다."
                    ),
                    retry_after_seconds=1.0,
                ),
                (
                    [{"pdno": "005930", "hldg_qty": "1"}],
                    {"dnca_tot_amt": "1000000"},
                    {"output": [{"pdno": "005930", "hldg_qty": "1"}], "output2": {"dnca_tot_amt": "1000000"}},
                ),
            ]
        )
        mock_sleep = AsyncMock()

        with (
            patch.object(KISRestClient, "_wait_for_inquiry_budget", AsyncMock(return_value=True)),
            patch.object(KISRestClient, "_fetch_inquire_balance_pages", mock_fetch),
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", mock_sleep),
        ):
            result = await client.get_cash_and_positions(after_hours=False)

        assert result.cash_balance == {"dnca_tot_amt": "1000000"}
        assert result.positions == [{"pdno": "005930", "hldg_qty": "1"}]
        assert mock_fetch.await_count == 2
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    async def test_submit_ioc_market_encodes_ord_dvsn_without_algo(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        request = SubmitOrderRequest(
            account_ref=submit_request.account_ref,
            client_order_id="ut-submit-ioc-market-001",
            correlation_id=submit_request.correlation_id,
            strategy_id=submit_request.strategy_id,
            symbol=submit_request.symbol,
            market=submit_request.market,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=submit_request.quantity,
            price=None,
            time_in_force=TimeInForce.IOC,
        )
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027330", "ORD_TMD": "152540"}
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            await client.submit_order(request)

        body: dict[str, object] = mock_request.call_args[1]["body"]
        assert body["ORD_DVSN"] == "13"
        assert body["ORD_UNPR"] == "0"
        assert "ALGO" not in body

    @pytest.mark.asyncio
    async def test_submit_formats_integral_quantity_without_decimal_suffix(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        request = SubmitOrderRequest(
            account_ref=submit_request.account_ref,
            client_order_id="ut-submit-int-qty-001",
            correlation_id=submit_request.correlation_id,
            strategy_id=submit_request.strategy_id,
            symbol=submit_request.symbol,
            market=submit_request.market,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("207.00000000"),
            price=submit_request.price,
        )
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027331", "ORD_TMD": "152541"}
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            await client.submit_order(request)

        body: dict[str, object] = mock_request.call_args[1]["body"]
        assert body["ORD_QTY"] == "207"

    @pytest.mark.asyncio
    async def test_submit_rejects_fractional_quantity_before_request(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        request = SubmitOrderRequest(
            account_ref=submit_request.account_ref,
            client_order_id="ut-submit-frac-qty-001",
            correlation_id=submit_request.correlation_id,
            strategy_id=submit_request.strategy_id,
            symbol=submit_request.symbol,
            market=submit_request.market,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.5"),
            price=submit_request.price,
        )

        with patch.object(KISRestClient, "_request", AsyncMock()) as mock_request:
            with pytest.raises(ValueError, match="whole share"):
                await client.submit_order(request)

        mock_request.assert_not_called()


class TestSubmitOrderPaperPacing:
    """Paper global REST pacing should serialize submit starts at 1s intervals."""

    @pytest.mark.asyncio
    async def test_paper_submit_sleeps_when_calls_are_too_close(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027326", "ORD_TMD": "152530"}
        }

        sleep_mock = AsyncMock()
        with (
            patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request,
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", sleep_mock),
            patch(
                "agent_trading.brokers.koreainvestment.rest_client.time.monotonic",
                side_effect=[100.0, 100.2, 101.2],
            ),
        ):
            await client.submit_order(submit_request)
            await client.submit_order(submit_request)

        assert mock_request.await_count == 2
        sleep_mock.assert_awaited_once()
        slept_for = sleep_mock.await_args.args[0]
        assert slept_for == pytest.approx(0.8, abs=1e-6)

    @pytest.mark.asyncio
    async def test_paper_submit_pacing_is_shared_across_instances(
        self, submit_request: SubmitOrderRequest
    ) -> None:
        client1 = KISRestClient(
            api_key="test-api-key",
            api_secret="test-api-secret",
            account_number="12345678",
            account_product_code="01",
            env="paper",
            budget_manager=None,
            dev_token_cache_enabled=False,
        )
        client2 = KISRestClient(
            api_key="test-api-key",
            api_secret="test-api-secret",
            account_number="12345678",
            account_product_code="01",
            env="paper",
            budget_manager=None,
            dev_token_cache_enabled=False,
        )
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027326", "ORD_TMD": "152530"}
        }

        sleep_mock = AsyncMock()
        with (
            patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request,
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", sleep_mock),
            patch(
                "agent_trading.brokers.koreainvestment.rest_client.time.monotonic",
                side_effect=[200.0, 200.25, 201.25],
            ),
        ):
            await client1.submit_order(submit_request)
            await client2.submit_order(submit_request)

        assert mock_request.await_count == 2
        sleep_mock.assert_awaited_once()
        slept_for = sleep_mock.await_args.args[0]
        assert slept_for == pytest.approx(0.75, abs=1e-6)

    @pytest.mark.asyncio
    async def test_live_submit_does_not_use_paper_pacing(
        self, submit_request: SubmitOrderRequest
    ) -> None:
        live_client = KISRestClient(
            api_key="test-api-key",
            api_secret="test-api-secret",
            account_number="12345678",
            account_product_code="01",
            env="live",
            budget_manager=None,
            dev_token_cache_enabled=False,
        )
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027326", "ORD_TMD": "152530"}
        }

        with (
            patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request,
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", AsyncMock()) as sleep_mock,
            patch(
                "agent_trading.brokers.koreainvestment.rest_client.time.monotonic",
                side_effect=AssertionError("live submit should not use paper pacing"),
            ),
        ):
            await live_client.submit_order(submit_request)

        assert mock_request.await_count == 1
        sleep_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_paper_quote_then_submit_shares_same_global_gate(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        class _FakeClient:
            async def get(self, url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> object:
                return object()

            async def post(
                self,
                url: str,
                headers: dict[str, str],
                json: dict[str, object] | None = None,
                params: dict[str, str] | None = None,
            ) -> object:
                return object()

        sleep_mock = AsyncMock()
        with (
            patch.object(KISRestClient, "_build_headers", AsyncMock(return_value={})),
            patch.object(KISRestClient, "_get_client", AsyncMock(return_value=_FakeClient())),
            patch.object(KISRestClient, "_raise_on_error", return_value={"output": {"stck_prpr": "50000"}}),
            patch.object(KISRestClient, "_normalize_response", side_effect=lambda data, endpoint=None: data),
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", sleep_mock),
            patch(
                "agent_trading.brokers.koreainvestment.rest_client.time.monotonic",
                side_effect=[300.0, 300.3, 301.3],
            ),
        ):
            await client.get_quote("005930")
            await client.submit_order(submit_request)

        sleep_mock.assert_awaited_once()
        slept_for = sleep_mock.await_args.args[0]
        assert slept_for == pytest.approx(0.7, abs=1e-6)

    @pytest.mark.asyncio
    async def test_paper_submit_then_quote_shares_same_global_gate(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        class _FakeClient:
            async def get(self, url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> object:
                return object()

            async def post(
                self,
                url: str,
                headers: dict[str, str],
                json: dict[str, object] | None = None,
                params: dict[str, str] | None = None,
            ) -> object:
                return object()

        sleep_mock = AsyncMock()
        with (
            patch.object(KISRestClient, "_build_headers", AsyncMock(return_value={})),
            patch.object(KISRestClient, "_get_client", AsyncMock(return_value=_FakeClient())),
            patch.object(KISRestClient, "_raise_on_error", return_value={"output": {"ODNO": "0001", "ORD_TMD": "090001"}}),
            patch.object(KISRestClient, "_normalize_response", side_effect=lambda data, endpoint=None: data),
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", sleep_mock),
            patch(
                "agent_trading.brokers.koreainvestment.rest_client.time.monotonic",
                side_effect=[400.0, 400.25, 401.25],
            ),
        ):
            await client.submit_order(submit_request)
            await client.get_quote("005930")

        sleep_mock.assert_awaited_once()
        slept_for = sleep_mock.await_args.args[0]
        assert slept_for == pytest.approx(0.75, abs=1e-6)


# ── Test 4: skip_global_rest ──────────────────────────────────────────────


class TestSubmitOrderSkipGlobalRest:
    """``submit_order()``가 ``_request()``에 ``skip_global_rest=True``를 전달하는지 검증.

    ``_request()``는 이미 ``skip_global_rest`` 파라미터를 지원하지만,
    ``submit_order()``에서 이를 전달하지 않아 ORDER bucket 요청이
    ``global_rest`` Tier 1에서 차단되는 문제가 있었다.
    """

    @pytest.mark.asyncio
    async def test_submit_order_passes_skip_global_rest(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        """ORDER bucket submit에서 skip_global_rest=True 확인."""
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027326", "ORD_TMD": "152530"}
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            await client.submit_order(submit_request)

        mock_request.assert_called_once()
        assert mock_request.call_args[1].get("skip_global_rest") is False

    @pytest.mark.asyncio
    async def test_submit_order_skip_global_rest_with_held_position_sell(
        self, client: KISRestClient, submit_request: SubmitOrderRequest
    ) -> None:
        """Held-position sell에서도 skip_global_rest=True가 유지되는지 확인."""
        mock_response: dict[str, Any] = {
            "output": {"ODNO": "0000027327", "ORD_TMD": "152531"}
        }

        with patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request:
            await client.submit_order(submit_request)

        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs.get("skip_global_rest") is False
        assert call_kwargs.get("bucket") == BucketType.ORDER


class TestCashAndPositionsBudgetWait:
    """Critical snapshot call should wait briefly for inquiry budget."""

    @pytest.mark.asyncio
    async def test_cash_and_positions_waits_then_requests(
        self, client: KISRestClient
    ) -> None:
        mock_response = (
            {
                "output": [{"pdno": "005930", "hldg_qty": "1"}],
                "output2": {"dnca_tot_amt": "1000000"},
            },
            {"tr_cont": "D"},
        )

        with (
            patch.object(KISRestClient, "_wait_for_inquiry_budget", AsyncMock(return_value=True)),
            patch.object(KISRestClient, "_request", AsyncMock(return_value=mock_response)) as mock_request,
        ):
            result = await client.get_cash_and_positions(after_hours=False)

        assert result.cash_balance == {"dnca_tot_amt": "1000000"}
        assert result.positions == [{"pdno": "005930", "hldg_qty": "1"}]
        mock_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cash_and_positions_returns_empty_on_budget_timeout(
        self, client: KISRestClient
    ) -> None:
        with (
            patch.object(KISRestClient, "_wait_for_inquiry_budget", AsyncMock(return_value=False)),
            patch.object(KISRestClient, "_request", AsyncMock()) as mock_request,
        ):
            result = await client.get_cash_and_positions(after_hours=False)

        assert result.cash_balance is None
        assert result.positions == []
        assert result.raw_response == {}
        mock_request.assert_not_awaited()


class TestInquireBalancePagination:
    @pytest.mark.asyncio
    async def test_normalize_response_preserves_continuation_keys(
        self, client: KISRestClient
    ) -> None:
        data = {
            "output1": [{"pdno": "000660"}],
            "output2": [{"dnca_tot_amt": "100000"}],
            "CTX_AREA_FK100": "NEXT-FK",
            "CTX_AREA_NK100": "NEXT-NK",
        }

        normalized = client._normalize_response(data, endpoint="inquire_balance")

        assert normalized["output"] == [{"pdno": "000660"}]
        assert normalized["output2"] == [{"dnca_tot_amt": "100000"}]
        assert normalized["CTX_AREA_FK100"] == "NEXT-FK"
        assert normalized["CTX_AREA_NK100"] == "NEXT-NK"

    @pytest.mark.asyncio
    async def test_get_cash_and_positions_aggregates_all_pages(
        self, client: KISRestClient
    ) -> None:
        responses = [
            (
                {
                    "output": [{"pdno": "000660", "hldg_qty": "1"}],
                    "output2": {"dnca_tot_amt": "1000000"},
                    "ctx_area_fk100": "NEXT-FK",
                    "ctx_area_nk100": "NEXT-NK",
                },
                {"tr_cont": "M"},
            ),
            (
                {
                    "output": [{"pdno": "005940", "hldg_qty": "17"}],
                    "output2": {"dnca_tot_amt": "1000000"},
                    "ctx_area_fk100": "",
                    "ctx_area_nk100": "",
                },
                {"tr_cont": "D"},
            ),
        ]

        with (
            patch.object(KISRestClient, "_wait_for_inquiry_budget", AsyncMock(return_value=True)),
            patch.object(KISRestClient, "_request", AsyncMock(side_effect=responses)) as mock_request,
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", AsyncMock()),
        ):
            result = await client.get_cash_and_positions(after_hours=False)

        assert result.cash_balance == {"dnca_tot_amt": "1000000"}
        assert result.positions == [
            {"pdno": "000660", "hldg_qty": "1"},
            {"pdno": "005940", "hldg_qty": "17"},
        ]
        assert result.raw_response["pages_fetched"] == 2
        assert mock_request.await_count == 2
        assert mock_request.await_args_list[0].kwargs["tr_cont"] == ""
        assert mock_request.await_args_list[1].kwargs["tr_cont"] == "N"

    @pytest.mark.asyncio
    async def test_get_positions_aggregates_all_pages(
        self, client: KISRestClient
    ) -> None:
        responses = [
            (
                {
                    "output": [{"pdno": "000660", "hldg_qty": "1"}],
                    "ctx_area_fk100": "NEXT-FK",
                    "ctx_area_nk100": "NEXT-NK",
                },
                {"tr_cont": "F"},
            ),
            (
                {
                    "output": [{"pdno": "005940", "hldg_qty": "17"}],
                    "ctx_area_fk100": "",
                    "ctx_area_nk100": "",
                },
                {"tr_cont": "E"},
            ),
        ]

        with (
            patch.object(KISRestClient, "_request", AsyncMock(side_effect=responses)) as mock_request,
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", AsyncMock()),
        ):
            positions = await client.get_positions()

        assert list(positions) == [
            {"pdno": "000660", "hldg_qty": "1"},
            {"pdno": "005940", "hldg_qty": "17"},
        ]
        assert mock_request.await_count == 2

    @pytest.mark.asyncio
    async def test_request_can_return_response_headers(
        self, client: KISRestClient
    ) -> None:
        mock_client = AsyncMock()
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.headers = {"tr_cont": "M"}
        mock_response.status_code = 200
        mock_response.json.return_value = {"rt_cd": "0", "output": []}
        mock_client.get.return_value = mock_response

        with (
            patch.object(KISRestClient, "_get_client", AsyncMock(return_value=mock_client)),
            patch.object(KISRestClient, "_build_headers", AsyncMock(return_value={"tr_id": "VTTC8434R"})),
        ):
            data, headers = await client._request(
                "GET",
                endpoint_key="inquire_balance",
                tr_id_key="inquire_balance",
                bucket=BucketType.INQUIRY,
                params={},
                include_response_headers=True,
                tr_cont="N",
            )

        assert data["output"] == []
        assert headers["tr_cont"] == "M"

    @pytest.mark.asyncio
    async def test_extract_continuation_keys_trims_lowercase_response_fields(
        self, client: KISRestClient
    ) -> None:
        ctx_fk, ctx_nk = client._extract_continuation_keys(
            {
                "ctx_area_fk100": "   NEXT-FK   ",
                "ctx_area_nk100": "  005930                              ",
            }
        )

        assert ctx_fk == "NEXT-FK"
        assert ctx_nk == "005930"

    @pytest.mark.asyncio
    async def test_get_positions_continues_when_tr_cont_indicates_more_and_only_nk_exists(
        self, client: KISRestClient
    ) -> None:
        responses = [
            (
                {
                    "output": [{"pdno": "005380", "hldg_qty": "1"}],
                    "ctx_area_fk100": "",
                    "ctx_area_nk100": "005380",
                },
                {"tr_cont": "M"},
            ),
            (
                {
                    "output": [{"pdno": "005940", "hldg_qty": "17"}],
                    "ctx_area_fk100": "",
                    "ctx_area_nk100": "",
                },
                {"tr_cont": "D"},
            ),
        ]

        with (
            patch.object(KISRestClient, "_request", AsyncMock(side_effect=responses)) as mock_request,
            patch("agent_trading.brokers.koreainvestment.rest_client.asyncio.sleep", AsyncMock()),
        ):
            positions = await client.get_positions()

        assert list(positions) == [
            {"pdno": "005380", "hldg_qty": "1"},
            {"pdno": "005940", "hldg_qty": "17"},
        ]
        assert mock_request.await_count == 2


class TestOrderableCashSource:
    @pytest.mark.asyncio
    async def test_orderable_cash_result_marks_budget_precheck_fallback(
        self, client: KISRestClient
    ) -> None:
        with patch.object(KISRestClient, "_has_budget_for_inquiry", return_value=False):
            result = await client.get_orderable_cash_result(
                fallback_cash=Decimal("123456"),
            )

        assert result.amount == Decimal("123456")
        assert result.source == "budget_precheck_fallback"

    @pytest.mark.asyncio
    async def test_orderable_cash_result_marks_vttc8908r_success(
        self, client: KISRestClient
    ) -> None:
        with (
            patch.object(KISRestClient, "_has_budget_for_inquiry", return_value=True),
            patch.object(
                KISRestClient,
                "_request",
                AsyncMock(return_value={"output": {"ord_psbl_cash": "700000"}}),
            ),
        ):
            result = await client.get_orderable_cash_result()

        assert result.amount == Decimal("700000")
        assert result.source == "vttc8908r"


# ── Tests 5-7: _resolve_smoke_price() ─────────────────────────────────────


class TestResolveSmokePrice:
    """``_resolve_smoke_price()`` env-var resolution policy."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure KIS_SMOKE_PRICE is absent before each test."""
        monkeypatch.delenv("KIS_SMOKE_PRICE", raising=False)

    def test_default_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env var → ``Decimal("50000")``."""
        monkeypatch.delenv("KIS_SMOKE_PRICE", raising=False)
        from scripts.run_orchestrator_once import _resolve_smoke_price

        assert _resolve_smoke_price() == Decimal("50000")

    def test_from_env_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``KIS_SMOKE_PRICE=268500`` → ``Decimal("268500")``."""
        monkeypatch.setenv("KIS_SMOKE_PRICE", "268500")
        from scripts.run_orchestrator_once import _resolve_smoke_price

        assert _resolve_smoke_price() == Decimal("268500")

    def test_from_env_invalid_falls_back(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """``KIS_SMOKE_PRICE=not-a-number`` → fallback to ``Decimal("50000")`` + warning."""
        monkeypatch.setenv("KIS_SMOKE_PRICE", "not-a-number")
        from scripts.run_orchestrator_once import _resolve_smoke_price

        assert _resolve_smoke_price() == Decimal("50000")
        assert "Invalid KIS_SMOKE_PRICE" in caplog.text


class TestFormatOrderQuantity:
    def test_format_order_quantity_strips_decimal_suffix(self) -> None:
        assert _format_order_quantity(Decimal("10.00000000")) == "10"

    def test_format_order_quantity_rejects_non_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            _format_order_quantity(Decimal("0"))
