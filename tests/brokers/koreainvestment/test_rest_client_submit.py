"""Tests for ``KISRestClient.submit_order()`` — success/error paths.

Verifies:
- ``SubmitOrderResult`` construction from a successful KIS ODNO response
- ``BrokerError`` propagation on business-level errors (e.g. price validation)
- Request body structure passed to ``_request()``
- ``_resolve_smoke_price()`` env-var resolution policy
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agent_trading.brokers.errors import BrokerError, BrokerErrorType
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.rate_limit import BucketType
from agent_trading.domain.enums import BrokerName, OrderSide, OrderStatus, OrderType
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
        assert body["ORD_DVSN"] in ("00", "03")  # LIMIT → "00" (지정가)
        assert body["CANO"] == "12345678"
        assert body["ACNT_PRDT_CD"] == "01"

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
        assert mock_request.call_args[1].get("skip_global_rest") is True

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
        assert call_kwargs.get("skip_global_rest") is True
        assert call_kwargs.get("bucket") == BucketType.ORDER


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
