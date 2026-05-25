from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agent_trading.brokers.base import BrokerAdapter, SubscriptionBudget
from agent_trading.brokers.errors import UnsupportedCapabilityError
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.koreainvestment.websocket_client import KISWebSocketClient
from agent_trading.brokers.rate_limit import (
    BudgetExhaustedError,
    RateLimitBudgetManager,
)
from agent_trading.domain.enums import (
    AssetClass,
    BrokerErrorType,
    BrokerName,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import (
    AmendOrderRequest,
    AmendOrderResult,
    BrokerCapability,
    BrokerHealth,
    BrokerSession,
    CancelOrderRequest,
    CancelOrderResult,
    CashBalance,
    FillEvent,
    MarketDataSubscription,
    OrderBook,
    OrderBookLevel,
    OrderStatusResult,
    Position,
    Quote,
    RateLimitProfile,
    SubmitOrderRequest,
    SubmitOrderResult,
)

logger = logging.getLogger(__name__)


class KoreaInvestmentAdapter(BrokerAdapter):
    """KIS broker adapter with REST client + WebSocket integration.

    Milestone 8
    -----------
    * Wires ``KISRestClient`` for all HTTP operations (Stream A).
    * Wires ``KISWebSocketClient`` for real-time market data and order
      event streaming (Stream B).
    * Applies ``RateLimitBudgetManager`` budget checks before each operation.
    * Provides ``resolve_unknown_state()`` for reconciliation recovery.
    * Pre-validation and normalisation retained from Milestone 6.

    WebSocket events are **append-only ingest** — they are NOT the source
    of truth.  Order state changes are handled by ``OrderManager`` /
    ``ReconciliationService``.
    """

    broker_name = BrokerName.KOREA_INVESTMENT

    def __init__(
        self,
        rest_client: KISRestClient,
        mode: str = "paper",
        subscription_budget: SubscriptionBudget | None = None,
        ws_url: str = "",
    ) -> None:
        self._rest = rest_client
        self._mode = mode
        self._ws_url = ws_url
        self._ws: KISWebSocketClient | None = None
        self._ws_connected = False
        self._ws_approval_key: str | None = None
        self._subscription_budget = subscription_budget or SubscriptionBudget(max_subscriptions=41)
        self._market_data_subscriptions: dict[str, set[str]] = {}  # channel -> {tr_keys}
        self._order_event_accounts: set[str] = set()

    # ------------------------------------------------------------------
    # BrokerAdapter interface
    # ------------------------------------------------------------------

    async def get_capabilities(self) -> BrokerCapability:
        return BrokerCapability(
            broker_name=self.broker_name,
            supports_paper_trading=True,
            supports_live_trading=True,
            supports_websocket=True,
            supported_asset_classes=(AssetClass.KR_STOCK, AssetClass.KR_ETF),
            supported_order_types=(OrderType.MARKET, OrderType.LIMIT),
            supported_time_in_force=(TimeInForce.DAY, TimeInForce.IOC, TimeInForce.FOK),
            supports_order_amend=True,
            supports_order_cancel=True,
            rate_limit_profile=RateLimitProfile(
                requests_per_second=None,
                burst_limit=None,
                notes="Confirm against latest KIS documentation before production use.",
            ),
        )

    async def health_check(self) -> BrokerHealth:
        """Check adapter health including WebSocket connectivity."""
        ws_healthy = self._ws_connected
        return BrokerHealth(
            broker_name=self.broker_name,
            healthy=ws_healthy,
            checked_at=datetime.now(tz=timezone.utc),
            message=f"REST client OK, WebSocket {'connected' if ws_healthy else 'disconnected'}",
        )

    async def authenticate(self) -> BrokerSession:
        """Authenticate REST API and obtain WebSocket approval key."""
        token = await self._rest.authenticate()
        approval_key = await self._rest.get_approval_key()
        self._ws_approval_key = approval_key
        return BrokerSession(
            broker_name=self.broker_name,
            authenticated_at=datetime.now(tz=timezone.utc),
            metadata={
                "mode": self._mode,
                "token_prefix": token[:16] if len(token) > 16 else token,
                "approval_key_prefix": approval_key[:8] if len(approval_key) > 8 else approval_key,
            },
        )

    async def get_quote(self, symbol: str, market: str) -> Quote:
        raw = await self._rest.get_quote(symbol)

        def _decimal(key: str) -> Decimal | None:
            val = raw.get(key)
            if val is None:
                return None
            try:
                cleaned = str(val).replace(",", "").strip()
                if not cleaned:
                    return None
                return Decimal(cleaned)
            except (ValueError, TypeError, ArithmeticError):
                return None

        return Quote(
            symbol=symbol,
            market=market,
            bid=_decimal("stck_bidp"),
            ask=_decimal("stck_askp"),
            last=_decimal("stck_prpr"),
            as_of=datetime.now(tz=timezone.utc),
        )

    async def get_orderbook(self, symbol: str, market: str) -> OrderBook:
        raw = await self._rest.get_orderbook(symbol)

        def _decimal(key: str) -> Decimal | None:
            val = raw.get(key)
            if val is None:
                return None
            try:
                cleaned = str(val).replace(",", "").strip()
                if not cleaned:
                    return None
                return Decimal(cleaned)
            except (ValueError, TypeError, ArithmeticError):
                return None

        def _levels(prefix: str) -> tuple[OrderBookLevel, ...]:
            levels: list[OrderBookLevel] = []
            for i in range(1, 11):
                price = _decimal(f"{prefix}{i}")
                qty = _decimal(f"{prefix}_rsqn{i}")
                if price is not None and qty is not None:
                    levels.append(OrderBookLevel(price=price, quantity=qty))
            return tuple(levels)

        return OrderBook(
            symbol=symbol,
            market=market,
            bids=_levels("bidp"),
            asks=_levels("askp"),
            as_of=datetime.now(tz=timezone.utc),
        )

    async def get_positions(self, account_ref: str) -> Sequence[Position]:
        raw_positions = await self._rest.get_positions()
        return [
            Position(
                account_ref=account_ref,
                symbol=p.get("symbol", ""),
                market=p.get("market", ""),
                quantity=Decimal(str(p.get("quantity", 0))),
                avg_price=Decimal(str(p.get("avg_price", 0))),
                as_of=datetime.now(tz=timezone.utc),
            )
            for p in raw_positions
        ]

    async def get_cash_balance(self, account_ref: str) -> CashBalance:
        raw = await self._rest.get_cash_balance()
        return CashBalance(
            account_ref=account_ref,
            available_cash=Decimal(str(raw.get("available_cash", 0))),
            settled_cash=Decimal(str(raw.get("settled_cash", 0))),
            as_of=datetime.now(tz=timezone.utc),
        )

    async def submit_order(self, request: SubmitOrderRequest) -> SubmitOrderResult:
        """Submit an order with pre-validation and result normalisation.

        Pre-validation (Milestone 6)
        -----------------------------
        * Price band check (if ``price_band_lower`` / ``price_band_upper`` set).
        * Max slippage check (if ``max_slippage_bps`` set).
        * Partial fill policy check.

        Budget check (Milestone 7)
        ---------------------------
        * ``KISRestClient.submit_order()`` consumes 1 token from ORDER bucket.
        * If budget is exhausted, ``BudgetExhaustedError`` is raised.

        Circuit breaker (Milestone 7)
        ------------------------------
        * If the order circuit breaker is OPEN, the result is
          ``requires_reconciliation=True``.
        """
        # --- Pre-validation ---
        validation_errors = self._validate_order_request(request)
        if validation_errors:
            return SubmitOrderResult(
                accepted=False,
                broker_name=self.broker_name,
                client_order_id=request.client_order_id,
                broker_order_id=None,
                broker_status=OrderStatus.REJECTED,
                ack_timestamp=None,
                raw_code="VALIDATION_ERROR",
                raw_message="; ".join(validation_errors),
                normalized_status=OrderStatus.REJECTED,
                uncertain=False,
                requires_reconciliation=False,
            )

        # --- Submit via REST client (with budget check + circuit breaker) ---
        try:
            result = await self._rest.submit_order(request)
        except BudgetExhaustedError:
            # Held-position sell special lane: retry with reserved budget
            if self._is_held_position_sell(request):
                logger.info(
                    "Held-position sell detected for symbol=%s — "
                    "retrying with reserved budget lane",
                    request.symbol,
                )
                try:
                    result = await self._rest.submit_order(
                        request,
                        _held_position_sell=True,
                    )
                    return self._normalize_submit_result(result)
                except BudgetExhaustedError:
                    # Reserve also exhausted — fall through to normal error
                    logger.warning(
                        "Held-position sell reserve also exhausted for symbol=%s",
                        request.symbol,
                    )

            # Budget exhausted — return a requires_reconciliation result.
            return SubmitOrderResult(
                accepted=False,
                broker_name=self.broker_name,
                client_order_id=request.client_order_id,
                broker_order_id=None,
                broker_status=OrderStatus.RECONCILE_REQUIRED,
                ack_timestamp=None,
                raw_code="BUDGET_EXHAUSTED",
                raw_message="Order budget exhausted — cannot submit.",
                normalized_status=OrderStatus.RECONCILE_REQUIRED,
                uncertain=False,
                requires_reconciliation=True,
            )

        return self._normalize_submit_result(result)

    @staticmethod
    def _is_held_position_sell(request: SubmitOrderRequest) -> bool:
        """Check if the request is a held-position sell order.

        ``SubmitOrderRequest.metadata``에 ``source_type`` 키가 있고
        값이 ``"held_position"``이며, side가 SELL이면 held_position sell로 간주한다.
        """
        if request.side != OrderSide.SELL:
            return False
        metadata = request.metadata or {}
        source_type = metadata.get("source_type", "")
        return str(source_type).lower() == "held_position"

    def _validate_order_request(self, request: SubmitOrderRequest) -> list[str]:
        """Run pre-validation checks on the order request.

        Returns a list of validation error messages. An empty list means
        the request passed all checks.
        """
        errors: list[str] = []

        # --- Price band check ---
        if request.price is not None:
            if request.price_band_lower is not None and request.price < request.price_band_lower:
                errors.append(
                    f"Price {request.price} is below lower band {request.price_band_lower}"
                )
            if request.price_band_upper is not None and request.price > request.price_band_upper:
                errors.append(
                    f"Price {request.price} is above upper band {request.price_band_upper}"
                )

        # --- Max slippage check (market orders) ---
        if request.order_type == OrderType.MARKET and request.max_slippage_bps is not None:
            if request.max_slippage_bps <= 0:
                errors.append(
                    f"max_slippage_bps must be positive, got {request.max_slippage_bps}"
                )

        # --- Partial fill policy ---
        if not request.allow_partial_fill and request.order_type == OrderType.MARKET:
            errors.append(
                "Market order with allow_partial_fill=False is not supported"
            )

        return errors

    def _normalize_submit_result(
        self, result: SubmitOrderResult
    ) -> SubmitOrderResult:
        """Normalise a raw broker response into a structured result.

        Detects ``uncertain`` and ``requires_reconciliation`` conditions.
        """
        uncertain = False
        requires_reconciliation = False

        # If no broker_order_id was returned, the result is uncertain.
        if result.broker_order_id is None and result.accepted:
            uncertain = True

        # If the broker returned a RECONCILE_REQUIRED status, flag it.
        if result.broker_status == OrderStatus.RECONCILE_REQUIRED:
            requires_reconciliation = True

        # If raw_code indicates an ambiguous state, flag as uncertain.
        if result.raw_code is not None:
            ambiguous_codes = {"UNKNOWN", "TIMEOUT", "PENDING", "CIRCUIT_OPEN"}
            if result.raw_code.upper() in ambiguous_codes:
                uncertain = True

        return SubmitOrderResult(
            accepted=result.accepted,
            broker_name=result.broker_name,
            client_order_id=result.client_order_id,
            broker_order_id=result.broker_order_id,
            broker_status=result.broker_status,
            ack_timestamp=result.ack_timestamp,
            raw_code=result.raw_code,
            raw_message=result.raw_message,
            idempotency_key=result.idempotency_key,
            normalized_status=result.normalized_status or result.broker_status,
            exchange_timestamp=result.exchange_timestamp,
            raw_payload_uri=result.raw_payload_uri,
            uncertain=uncertain,
            requires_reconciliation=requires_reconciliation,
        )

    async def cancel_order(self, request: CancelOrderRequest) -> CancelOrderResult:
        try:
            return await self._rest.cancel_order(
                account_ref=request.account_ref,
                client_order_id=request.client_order_id,
                broker_order_id=request.broker_order_id,
                correlation_id=request.correlation_id,
                quantity=request.quantity,
            )
        except BudgetExhaustedError:
            return CancelOrderResult(
                accepted=False,
                broker_name=self.broker_name,
                client_order_id=request.client_order_id,
                broker_order_id=request.broker_order_id,
                broker_status=OrderStatus.RECONCILE_REQUIRED,
                raw_message="Cancel budget exhausted.",
            )

    async def amend_order(self, request: AmendOrderRequest) -> AmendOrderResult:
        raise UnsupportedCapabilityError(
            broker_name=self.broker_name,
            error_type=BrokerErrorType.UNSUPPORTED_CAPABILITY,
            retryable=False,
            correlation_id=request.correlation_id,
            raw_message="Amend implementation is not available in the scaffold.",
        )

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
    ) -> OrderStatusResult:
        try:
            return await self._rest.get_order_status(
                account_ref,
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
            )
        except BudgetExhaustedError:
            return OrderStatusResult(
                broker_name=self.broker_name,
                client_order_id=client_order_id,
                broker_order_id=broker_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                remaining_quantity=None,
                last_updated_at=datetime.now(tz=timezone.utc),
                raw_message="Inquiry budget exhausted.",
            )

    async def get_fills(
        self,
        account_ref: str,
        broker_order_id: str,
        from_ts: str | datetime | None = None,
    ) -> Sequence[FillEvent]:
        try:
            # datetime 객체가 전달되면 str로 변환
            if isinstance(from_ts, datetime):
                from_ts = from_ts.strftime("%Y%m%d")
            return await self._rest.get_fills(account_ref, broker_order_id, from_ts=from_ts)
        except BudgetExhaustedError:
            return ()

    async def subscribe_market_data(
        self,
        subscriptions: Sequence[MarketDataSubscription],
    ) -> None:
        """Subscribe to real-time market data channels via WebSocket.

        Each ``MarketDataSubscription`` is mapped to a KIS channel:
        - ``trade`` → ``H0STCNT0`` (실시간체결가)
        - ``orderbook`` → ``H0STASP0`` (실시간호가)

        Subscriptions are registered as **optional** in the budget —
        they may be evicted if critical capacity is needed.
        """
        if not subscriptions:
            return

        await self._ensure_ws_connected()

        for sub in subscriptions:
            channel = self._market_data_channel(sub.channel)
            if channel is None:
                logger.warning("Unknown market data channel: %s", sub.channel)
                continue

            # Track for budget management
            if channel not in self._market_data_subscriptions:
                self._market_data_subscriptions[channel] = set()
            self._market_data_subscriptions[channel].add(sub.symbol)

            # Subscribe via WebSocket (optional budget)
            await self._ws.subscribe(channel, sub.symbol, critical=False)

    async def subscribe_order_events(self, account_ref: str) -> None:
        """Subscribe to real-time order fill notifications via WebSocket.

        Uses ``H0STCNI0`` (실시간체결통보) channel with **critical**
        budget — fill notifications are protected from eviction.
        """
        await self._ensure_ws_connected()

        self._order_event_accounts.add(account_ref)

        # H0STCNI0 uses the account number as the tr_key
        await self._ws.subscribe("H0STCNI0", account_ref, critical=True)

    # ------------------------------------------------------------------
    # WebSocket lifecycle
    # ------------------------------------------------------------------

    async def _ensure_ws_connected(self) -> None:
        """Ensure the WebSocket client is connected.

        Lazily creates and connects the ``KISWebSocketClient`` if not
        already connected.  Requires ``authenticate()`` to have been
        called first (to obtain the approval key).
        """
        if self._ws is not None and self._ws_connected:
            return

        if self._ws_approval_key is None:
            logger.warning("WebSocket approval key not set — call authenticate() first")
            return

        self._ws = KISWebSocketClient(
            rest_client=self._rest,
            approval_key=self._ws_approval_key,
            env=self._mode,
            subscription_budget=self._subscription_budget,
            ws_url=self._ws_url,
        )
        await self._ws.connect()
        self._ws_connected = True
        logger.info("KIS WebSocket connected via adapter")

    async def _disconnect_ws(self) -> None:
        """Disconnect the WebSocket client."""
        if self._ws is not None:
            await self._ws.disconnect()
            self._ws = None
            self._ws_connected = False
            logger.info("KIS WebSocket disconnected via adapter")

    async def ws_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed WebSocket messages for downstream event loop.

        Usage::

            async for msg in adapter.ws_messages():
                # process msg
        """
        if self._ws is None:
            return
        async for msg in self._ws.messages():
            yield msg

    # ------------------------------------------------------------------
    # Reconciliation / Unknown State Recovery
    # ------------------------------------------------------------------

    async def resolve_unknown_state(
        self,
        account_ref: str,
        *,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
        symbol: str | None = None,
    ) -> OrderStatusResult:
        """Resolve an unknown order state by inquiring KIS.

        This is the **broker-specific recovery path** for reconciliation.
        Delegates to ``KISRestClient.resolve_unknown_state()`` which
        uses the INQUIRY bucket with reconciliation reserve fallback.
        """
        return await self._rest.resolve_unknown_state(
            broker_order_id=broker_order_id or "",
            symbol=symbol or None,  # 빈 문자열 → None으로 정규화하여 post-fetch filtering 통과
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _market_data_channel(channel: str) -> str | None:
        """Map a generic market data channel name to a KIS WebSocket TR ID.

        Parameters
        ----------
        channel : str
            Generic channel name (``"trade"``, ``"orderbook"``).

        Returns
        -------
        str | None
            KIS WebSocket TR ID or ``None`` if unknown.
        """
        mapping: dict[str, str] = {
            "trade": "H0STCNT0",
            "orderbook": "H0STASP0",
        }
        return mapping.get(channel)

