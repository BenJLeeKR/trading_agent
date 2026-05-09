"""Real-time event loop for WebSocket event consumption and gap fill.

Architecture
------------
- Consumes parsed WebSocket messages from ``KoreaInvestmentAdapter.ws_messages()``.
- **Append-only ingest**: WS events are NOT the source of truth.
  Fill events are persisted as ``FillEventEntity`` and order state changes
  are routed through ``OrderManager.transition_to()``.
- Gap fill after disconnection uses REST inquiry (``inquire-daily-ccld``)
  to recover missed events.
- Gap fill severity: order/fill channels > market data channels.

Design principles
-----------------
1. WS events are ingested and persisted, but order state is ONLY updated
   via ``OrderManager`` / ``ReconciliationService``.
2. Gap fill is triggered on reconnect — the event loop detects gaps via
   continuum keys and fills them via REST API.
3. While a gap fill is in progress for a symbol, fast execution signals
   for that symbol are marked stale.
4. Duplicate WS fill events are detected via ``dedup_key_hash`` before
   persisting ``FillEventEntity``.
5. If a broker native order ID cannot be mapped to a local
   ``OrderRequestEntity``, the external event is still persisted but
   ``OrderManager.transition_to()`` is skipped and a reconciliation
   warning is logged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.domain.entities import ExternalEventEntity, FillEventEntity
from agent_trading.domain.enums import (
    EventSource,
    OrderSide,
    OrderStatus,
    SourceReliabilityTier,
)
from agent_trading.repositories.contracts import (
    BrokerOrderRepository,
    ExternalEventRepository,
    FillEventRepository,
    OrderRepository,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import OrderSyncService
from agent_trading.services.reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Channel severity for gap fill priority
_CHANNEL_SEVERITY: dict[str, int] = {
    "H0STCNI0": 3,  # Fill notifications — highest
    "H0STCNT0": 2,  # Trade prices
    "H0STCNS0": 2,  # KOSDAQ trade prices
    "H0STASP0": 1,  # Orderbook — lowest
}

# Gap fill lookback window (seconds)
_GAP_FILL_LOOKBACK_SECONDS = 300  # 5 minutes

# Source channel values for FillEventEntity / ExternalEventEntity
_SOURCE_CHANNEL_WS = "websocket"
_SOURCE_CHANNEL_REST_POLL = "rest_poll"
_SOURCE_CHANNEL_BACKFILL = "backfill"

# Broker name constant for BrokerOrderRepository lookup
_BROKER_NAME = "koreainvestment"

# Debounce interval for WS-triggered sync (seconds).
# Prevents rapid duplicate sync_order_post_submit() calls for the same order
# when multiple fill notifications arrive in quick succession.
_WS_SYNC_DEBOUNCE_SECONDS = 5


# ---------------------------------------------------------------------------
# Event Loop
# ---------------------------------------------------------------------------


class RealTimeEventLoop:
    """Real-time event loop consuming WebSocket messages.

    Usage::

        loop = RealTimeEventLoop(adapter, order_manager, ...)
        await loop.run()

    The loop runs until ``stop()`` is called.
    """

    def __init__(
        self,
        adapter: KoreaInvestmentAdapter,
        order_manager: OrderManager,
        reconciliation_service: ReconciliationService,
        order_repo: OrderRepository,
        fill_repo: FillEventRepository,
        external_event_repo: ExternalEventRepository,
        broker_order_repo: BrokerOrderRepository,
        *,
        poll_interval: float = 0.1,
        # Optional WS-triggered sync dependencies.
        # When ``sync_service`` is ``None``, no sync trigger is fired —
        # the event loop behaves exactly as before.
        sync_service: OrderSyncService | None = None,
        account_ref: str | None = None,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._order_manager = order_manager
        self._reconciliation_service = reconciliation_service
        self._order_repo = order_repo
        self._fill_repo = fill_repo
        self._external_event_repo = external_event_repo
        self._broker_order_repo = broker_order_repo
        self._poll_interval = poll_interval

        # WS-triggered sync dependencies (optional)
        self._sync_service = sync_service
        self._account_ref = account_ref
        self._snapshot_refresh_cb = snapshot_refresh_cb

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._gap_fill_in_progress: set[str] = set()  # Symbols being gap-filled
        self._stale_symbols: set[str] = set()  # Symbols with stale fast-execution signals
        self._debounce_last_sync: dict[UUID, datetime] = {}  # broker_order_id -> last sync time
        self._filled_refresh_fired: set[str] = set()  # broker native order IDs that already triggered refresh

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the event loop until ``stop()`` is called."""
        if self._running:
            logger.warning("RealTimeEventLoop is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("RealTimeEventLoop started")

    async def stop(self) -> None:
        """Stop the event loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("RealTimeEventLoop stopped")

    async def __aenter__(self) -> RealTimeEventLoop:
        await self.run()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Gap fill status
    # ------------------------------------------------------------------

    @property
    def symbols_with_stale_signals(self) -> frozenset[str]:
        """Symbols whose fast-execution signals are stale due to gap fill."""
        return frozenset(self._stale_symbols)

    def is_gap_fill_in_progress(self, symbol: str) -> bool:
        """Check if a gap fill is in progress for a symbol."""
        return symbol in self._gap_fill_in_progress

    # ------------------------------------------------------------------
    # Internal: main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Consume WebSocket messages and dispatch to handlers."""
        try:
            async for msg in self._adapter.ws_messages():
                if not self._running:
                    break

                msg_type = msg.get("type", "")

                try:
                    if msg_type == "real_time_data":
                        await self._handle_real_time_data(msg)
                    elif msg_type == "subscription_ack":
                        logger.info("Subscription ack: %s/%s", msg.get("tr_id"), msg.get("tr_key"))
                    elif msg_type == "error":
                        logger.warning("WebSocket error: %s", msg.get("message"))
                    else:
                        logger.debug("Unhandled message type: %s", msg_type)
                except Exception as e:
                    logger.error("Error handling WebSocket message: %s", e, exc_info=True)

        except asyncio.CancelledError:
            logger.info("RealTimeEventLoop cancelled")
        except Exception as e:
            logger.error("RealTimeEventLoop crashed: %s", e, exc_info=True)
        finally:
            self._running = False

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_real_time_data(self, msg: dict[str, Any]) -> None:
        """Dispatch a real-time data message to the appropriate handler."""
        tr_id = msg.get("tr_id", "")
        data = msg.get("data", {})

        if tr_id == "H0STCNI0":
            await self._handle_fill_notification(data)
        elif tr_id in ("H0STCNT0", "H0STCNS0"):
            await self._handle_trade_price(data)
        elif tr_id == "H0STASP0":
            await self._handle_orderbook(data)

    async def _handle_fill_notification(self, data: dict[str, Any]) -> None:
        """Handle a fill notification (H0STCNI0).

        Persists the fill event and routes the order state change through
        ``OrderManager``.

        Duplicate detection
        -------------------
        Before persisting ``FillEventEntity``, the method checks whether an
        ``ExternalEventEntity`` with the same ``dedup_key_hash`` already
        exists.  If so, the fill is treated as a duplicate and skipped.

        Native ID mapping failure
        -------------------------
        If the broker native order ID cannot be mapped to a local
        ``OrderRequestEntity`` (via ``BrokerOrderRepository``), the
        ``ExternalEventEntity`` is still persisted but
        ``OrderManager.transition_to()`` is skipped and a reconciliation
        warning is logged.
        """
        broker_order_id = data.get("broker_order_id", "")
        if not broker_order_id:
            logger.warning("Fill notification missing broker_order_id")
            return

        stock_code = data.get("stock_code", "")
        filled_qty_str = data.get("filled_qty", "0")
        filled_price_str = data.get("filled_price", "0")
        filled_time = data.get("filled_time", "")
        side_raw = data.get("side", OrderSide.BUY)
        order_qty_str = data.get("order_qty", "0")

        now = datetime.now(tz=timezone.utc)
        dedup_key = f"fill:{broker_order_id}:{filled_time}"

        # --- Persist ExternalEventEntity (append-only ingest) ---
        # published_at: prefer broker event time, fall back to ingested_at
        published_at = _parse_time(filled_time) or now

        ext_event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="fill_notification",
            source_name=EventSource.BROKER_WS.value,
            published_at=published_at,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            source_event_id=f"H0STCNI0:{broker_order_id}:{filled_time}",
            symbol=stock_code,
            ingested_at=now,
            dedup_key_hash=dedup_key,
            metadata=data,
        )
        # --- Duplicate detection (check before persisting) ---
        existing = await self._external_event_repo.find_by_dedup_key(dedup_key)
        if existing is not None:
            logger.info("Duplicate fill notification skipped: %s", dedup_key)
            return

        # --- Persist ExternalEventEntity (append-only ingest) ---
        await self._external_event_repo.add(ext_event)

        # --- Check for gap fill in progress ---
        if stock_code in self._gap_fill_in_progress:
            logger.info("Skipping fill notification for %s — gap fill in progress", stock_code)
            return

        # --- Resolve broker native order ID → local OrderRequestEntity ---
        order_entity = await self._resolve_order_from_native_id(broker_order_id)
        if order_entity is None:
            logger.warning(
                "Broker native order ID %s not found locally — "
                "ExternalEvent persisted but OrderManager.transition_to skipped. "
                "Reconciliation may be required.",
                broker_order_id,
            )
            return

        # --- Persist FillEventEntity ---
        fill_qty = _safe_decimal(filled_qty_str)
        fill_price = _safe_decimal(filled_price_str)
        fill_ts = _parse_time(filled_time) or now

        fill_event = FillEventEntity(
            fill_event_id=uuid4(),
            broker_order_id=order_entity.order_request_id,
            fill_timestamp=fill_ts,
            fill_price=fill_price,
            fill_quantity=fill_qty,
            source_channel=_SOURCE_CHANNEL_WS,
            fill_fee=None,
            created_at=now,
        )
        await self._fill_repo.add(fill_event)

        # --- Guard: block optimistic state progression during reconciliation ---
        # Fill data (ExternalEvent + FillEvent) is already persisted above.
        # If the order is in RECONCILE_REQUIRED, we hold the state progression
        # until reconciliation resolves the authoritative result.
        # See plans/34_reconcile_required_fill_transition_policy.md
        if order_entity.status == OrderStatus.RECONCILE_REQUIRED:
            logger.warning(
                "Fill notification preserved for order %s — "
                "order is in RECONCILE_REQUIRED state. "
                "Fill data persisted, state progression held "
                "until reconciliation resolves.",
                order_entity.order_request_id,
            )
            return

        # --- Route order state change through OrderManager ---
        order_qty = _safe_decimal(order_qty_str)
        target_status = _resolve_fill_status(fill_qty, order_qty)

        try:
            await self._order_manager.transition_to(
                order_entity,
                target_status,
                reason_code="WS_FILL",
                reason_message=(
                    f"WS fill notification: filled_qty={filled_qty_str}, "
                    f"filled_price={filled_price_str}"
                ),
                actor_type="system",
                actor_id="event_loop",
            )
        except Exception as e:
            logger.warning(
                "OrderManager.transition_to failed for %s: %s",
                broker_order_id,
                e,
            )

        # --- Fire snapshot refresh directly if FILLED reached ---
        # The transition_to() above already updated the order status to
        # FILLED in the database.  By the time sync_order_post_submit()
        # runs (fire-and-forget), the order is already terminal, so
        # sync's own refresh trigger (which requires status_changed)
        # would not fire.  Therefore we must trigger refresh here directly.
        if (
            target_status == OrderStatus.FILLED
            and self._snapshot_refresh_cb is not None
            and broker_order_id not in self._filled_refresh_fired
        ):
            self._filled_refresh_fired.add(broker_order_id)
            try:
                await self._snapshot_refresh_cb(order_entity.account_id)
                logger.info(
                    "WS fill -> snapshot refresh triggered for account=%s "
                    "order=%s broker_order=%s",
                    order_entity.account_id,
                    order_entity.order_request_id,
                    broker_order_id,
                )
            except Exception as e:
                logger.warning(
                    "WS fill -> snapshot refresh failed for account=%s: %s",
                    order_entity.account_id,
                    e,
                )

        # --- Fire WS-triggered sync (fire-and-forget with debounce) ---
        # After the fill notification has been processed and the order state
        # has progressed via OrderManager.transition_to(), trigger a
        # sync_order_post_submit() to converge the order's broker-side status
        # and fill events as quickly as possible.
        #
        # This is a fire-and-forget task — errors are handled internally by
        # sync_order_post_submit() and logged.  If the sync fails, the
        # polling-based PostSubmitSyncRunner (30s interval) serves as the
        # eventual-convergence fallback.
        if self._sync_service is not None and self._account_ref is not None:
            try:
                # Re-resolve the BrokerOrderEntity to obtain the internal
                # broker_order_id (UUID) that sync_order_post_submit() expects.
                broker_order_entity = await self._broker_order_repo.get_by_native_order_id(
                    broker_name=_BROKER_NAME,
                    broker_native_order_id=broker_order_id,
                )
                if broker_order_entity is not None:
                    bo_uuid = broker_order_entity.broker_order_id

                    # Debounce: skip if sync was called for this order within
                    # the configured debounce window.
                    now = datetime.now(tz=timezone.utc)
                    last = self._debounce_last_sync.get(bo_uuid)
                    if last is not None and (now - last).total_seconds() < _WS_SYNC_DEBOUNCE_SECONDS:
                        logger.debug(
                            "Sync debounced for broker_order=%s (%.1fs since last)",
                            bo_uuid,
                            (now - last).total_seconds(),
                        )
                    else:
                        self._debounce_last_sync[bo_uuid] = now
                        # Fire-and-forget: do not block the WS event handler.
                        asyncio.create_task(
                            self._sync_service.sync_order_post_submit(
                                account_ref=self._account_ref,
                                broker=self._adapter,
                                broker_order_id=bo_uuid,
                                snapshot_refresh_cb=self._snapshot_refresh_cb,
                            )
                        )
            except Exception as e:
                logger.warning(
                    "Failed to trigger WS sync for native_order=%s: %s",
                    broker_order_id,
                    e,
                )

    async def _handle_trade_price(self, data: dict[str, Any]) -> None:
        """Handle a trade price update (H0STCNT0 / H0STCNS0).

        Persists as an external event for downstream processing.
        """
        stock_code = data.get("stock_code", "")
        if not stock_code:
            return

        now = datetime.now(tz=timezone.utc)
        trade_time = data.get("trade_time", "")
        trade_price = data.get("trade_price", "")
        dedup_key = f"trade:{stock_code}:{trade_time}:{trade_price}"

        # published_at: prefer broker event time, fall back to ingested_at
        published_at = _parse_time(trade_time) or now

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="trade_price",
            source_name=EventSource.BROKER_WS.value,
            published_at=published_at,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            source_event_id=f"H0STCNT0:{stock_code}:{trade_time}",
            symbol=stock_code,
            ingested_at=now,
            dedup_key_hash=dedup_key,
            metadata=data,
        )
        await self._external_event_repo.add(event)

    async def _handle_orderbook(self, data: dict[str, Any]) -> None:
        """Handle an orderbook update (H0STASP0).

        Persists as an external event for downstream processing.
        """
        stock_code = data.get("stock_code", "")
        if not stock_code:
            return

        now = datetime.now(tz=timezone.utc)
        ob_time = data.get("time", "")
        dedup_key = f"orderbook:{stock_code}:{ob_time}"

        # published_at: prefer broker event time, fall back to ingested_at
        published_at = _parse_time(ob_time) or now

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="orderbook",
            source_name=EventSource.BROKER_WS.value,
            published_at=published_at,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
            source_event_id=f"H0STASP0:{stock_code}:{ob_time}",
            symbol=stock_code,
            ingested_at=now,
            dedup_key_hash=dedup_key,
            metadata=data,
        )
        await self._external_event_repo.add(event)

    # ------------------------------------------------------------------
    # Native ID resolution
    # ------------------------------------------------------------------

    async def _resolve_order_from_native_id(
        self,
        native_order_id: str,
    ) -> Any | None:
        """Resolve a broker native order ID to a local ``OrderRequestEntity``.

        Returns ``None`` if the native ID cannot be found, in which case
        the caller should persist the external event but skip the
        ``OrderManager.transition_to()`` call.
        """
        try:
            broker_order = await self._broker_order_repo.get_by_native_order_id(
                broker_name=_BROKER_NAME,
                broker_native_order_id=native_order_id,
            )
            if broker_order is None:
                return None

            order_entity = await self._order_repo.get(broker_order.order_request_id)
            return order_entity
        except Exception as e:
            logger.error("Error resolving native order ID %s: %s", native_order_id, e)
            return None

    # ------------------------------------------------------------------
    # Gap fill
    # ------------------------------------------------------------------

    async def trigger_gap_fill(
        self,
        symbol: str,
        account_ref: str,
        from_time: datetime | None = None,
    ) -> None:
        """Trigger a gap fill for a symbol after WebSocket disconnection.

        Uses REST inquiry (``inquire-daily-ccld``) to recover missed events.
        While gap fill is in progress, fast-execution signals for the symbol
        are marked stale.

        Parameters
        ----------
        symbol : str
            Stock code to fill gaps for.
        account_ref : str
            Broker account reference (required for REST inquiry).
        from_time : datetime | None
            Start time for the gap fill window.  Defaults to 5 minutes ago.
        """
        if symbol in self._gap_fill_in_progress:
            logger.info("Gap fill already in progress for %s", symbol)
            return

        self._gap_fill_in_progress.add(symbol)
        self._stale_symbols.add(symbol)
        logger.info("Gap fill started for %s", symbol)

        try:
            if from_time is None:
                from_time = datetime.now(tz=timezone.utc)

            from_ts = int(from_time.timestamp()) - _GAP_FILL_LOOKBACK_SECONDS

            # Use REST client to fetch missed fills
            # KIS inquire-daily-ccld retrieves fill data for the account
            fills = await self._adapter.get_fills(
                account_ref=account_ref,
                broker_order_id="",  # Empty = all orders in window
                from_ts=str(from_ts),
            )

            now = datetime.now(tz=timezone.utc)

            for fill in fills:
                # Persist each fill as ExternalEventEntity
                dedup_key = f"gap_fill:{fill.broker_order_id}:{fill.fill_timestamp}"

                ext_event = ExternalEventEntity(
                    event_id=uuid4(),
                    event_type="gap_fill_fill",
                    source_name=EventSource.RECONCILIATION.value,
                    published_at=fill.fill_timestamp,
                    source_reliability_tier=SourceReliabilityTier.T1_REGULATORY.value,
                    source_event_id=f"gap_fill:{symbol}:{fill.broker_order_id}",
                    symbol=symbol,
                    ingested_at=now,
                    dedup_key_hash=dedup_key,
                    metadata={
                        "broker_order_id": fill.broker_order_id,
                        "symbol": symbol,
                        "fill_quantity": str(fill.fill_quantity),
                        "fill_price": str(fill.fill_price),
                        "fill_timestamp": fill.fill_timestamp.isoformat(),
                    },
                )
                await self._external_event_repo.add(ext_event)

            logger.info("Gap fill completed for %s (%d fills)", symbol, len(fills))

        except Exception as e:
            logger.error("Gap fill failed for %s: %s", symbol, e)
        finally:
            self._gap_fill_in_progress.discard(symbol)
            self._stale_symbols.discard(symbol)

    async def trigger_gap_fill_all(
        self,
        symbols: set[str],
        account_ref: str,
    ) -> None:
        """Trigger gap fill for multiple symbols, ordered by channel severity.

        Higher-severity channels (fill notifications) are filled first.

        Parameters
        ----------
        symbols : set[str]
            Stock codes to fill gaps for.
        account_ref : str
            Broker account reference (required for REST inquiry).
        """
        # Sort symbols by channel severity (H0STCNI0 first)
        sorted_symbols = sorted(
            symbols,
            key=lambda s: max(
                _CHANNEL_SEVERITY.get(ch, 0)
                for ch in _CHANNEL_SEVERITY
            ),
            reverse=True,
        )

        for symbol in sorted_symbols:
            await self.trigger_gap_fill(symbol, account_ref=account_ref)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_fill_status(fill_qty: Decimal, order_qty: Decimal) -> OrderStatus:
    """Resolve the order status from a fill notification.

    If the filled quantity equals or exceeds the order quantity, the order
    is fully filled.  Otherwise, it is partially filled.
    """
    if order_qty > 0 and fill_qty >= order_qty:
        return OrderStatus.FILLED
    return OrderStatus.PARTIALLY_FILLED


def _parse_time(time_str: str) -> datetime | None:
    """Parse a KIS time string (HHMMSS) into a datetime."""
    if not time_str or len(time_str) < 6:
        return None
    try:
        hour = int(time_str[0:2])
        minute = int(time_str[2:4])
        second = int(time_str[4:6])
        now = datetime.now(tz=timezone.utc)
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    except (ValueError, IndexError):
        return None


def _safe_decimal(value: str) -> Decimal:
    """Convert a string to Decimal safely, returning 0 on failure."""
    try:
        return Decimal(value)
    except (ValueError, TypeError):
        return Decimal("0")
