"""KIS WebSocket client for real-time market data and order event streaming.

Architecture
------------
- Uses ``websockets`` library for async WebSocket transport.
- Connects to KIS real-time server: ``ws://ops.koreainvestment.com:21000``
  (or ``ws://ops.koreainvestment.com:31000`` for paper).
- Supports multiple channel subscriptions (H0STCNT0, H0STASP0, H0STCNI0).
- **Append-only ingest**: WebSocket events are NOT the source of truth.
  They are parsed and emitted as ``ExternalEventEntity`` for downstream
  processing by ``OrderManager`` / ``ReconciliationService``.
- Gap fill after disconnection uses REST inquiry (via ``KISRestClient``).

Subscription budget
-------------------
- Uses ``SubscriptionBudget`` from ``base.py`` to enforce critical/optional
  subscription limits.
- Critical subscriptions (e.g., H0STCNI0 fill notifications) are protected
  from eviction by optional subscriptions (e.g., H0STCNT0 market data).

Thread safety
-------------
- All public methods are async and designed for single-consumer use.
- The client maintains an internal asyncio queue for incoming messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.base import SubscriptionBudget
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.koreainvestment.ws_parser import parse_message
from agent_trading.domain.enums import EventSource, SourceReliabilityTier
from agent_trading.domain.models import MarketDataSubscription

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KIS_WS_URLS: dict[str, str] = {
    "live": "ws://ops.koreainvestment.com:21000",
    "paper": "ws://ops.koreainvestment.com:31000",
}

# Reconnect delays (seconds)
_INITIAL_RECONNECT_DELAY = 1.0
_MAX_RECONNECT_DELAY = 60.0
_RECONNECT_MULTIPLIER = 2.0

# Heartbeat interval (seconds)
_HEARTBEAT_INTERVAL = 30.0

# Channel types for subscription budget
_CRITICAL_CHANNELS = frozenset({"H0STCNI0"})  # Fill notifications
_OPTIONAL_CHANNELS = frozenset({"H0STCNT0", "H0STASP0", "H0STCNS0"})  # Market data


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------


class KISWebSocketClient:
    """KIS WebSocket client for real-time data streaming.

    Usage::

        client = KISWebSocketClient(rest_client, approval_key="...")
        await client.connect()

        # Subscribe to channels
        await client.subscribe("H0STCNT0", "005930")  # critical=False (market data)
        await client.subscribe("H0STCNI0", "12345678", critical=True)  # fill notifications

        # Consume messages
        async for msg in client.messages():
            print(msg)

        await client.disconnect()
    """

    def __init__(
        self,
        rest_client: KISRestClient,
        approval_key: str,
        env: str = "paper",
        subscription_budget: SubscriptionBudget | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        ws_url: str = "",
    ) -> None:
        self._rest = rest_client
        self._approval_key = approval_key
        self._env = env
        self._budget = subscription_budget or SubscriptionBudget()
        self._on_event = on_event
        self._ws_url = ws_url

        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._connected = False
        self._should_reconnect = True
        self._reconnect_delay = _INITIAL_RECONNECT_DELAY
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscriptions: dict[str, set[str]] = {}  # channel -> {tr_keys}
        self._critical_subscriptions: dict[str, set[str]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._continuum_tracker: dict[str, str] = {}  # tr_id -> last continuum_key

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, *, force_refresh_approval_key: bool = False) -> None:
        """Connect to the KIS WebSocket server.

        Parameters
        ----------
        force_refresh_approval_key:
            Re-issue a fresh approval key (bypassing its 24h cache) before
            opening the socket, as an extra safety measure on reconnect.
            Not the fix for the "JSON PARSING ERROR" reconnect loop (see
            ``ping_interval`` note below for the actual root cause) — kept
            because there's no downside to a fresh key on reconnect.
            ``_handle_disconnect()`` always passes ``True``; the very first
            ``connect()`` call leaves this ``False`` since the caller
            (``KisRealtimeQuoteSource.connect()``) just fetched a fresh key
            moments earlier.

        Raises ``ConnectionError`` if the connection fails.

        Heartbeat (2026-07-14 root-cause fix)
        --------------------------------------
        Previously this sent an app-level empty string (``await
        self._ws.send("")``) every 30s from a separate task as a
        "heartbeat". KIS's WS gateway treats every application-level text
        frame as JSON to parse — an empty string isn't valid JSON, so KIS
        rejected it with ``rt_cd=1``/``"JSON PARSING ERROR : invalid json
        format"`` and then dropped the connection outright, causing an
        infinite reconnect loop (observed failures landed almost exactly
        30s after each connect, matching this heartbeat's interval).
        ``KisMarketStateClient`` (``market_state_client.py``) already does
        this correctly — protocol-level WebSocket ping/pong frames via
        ``websockets.connect(..., ping_interval=...)``, invisible to KIS's
        JSON parser since they never reach the application layer. This
        client now does the same instead of a hand-rolled heartbeat task.
        """
        import websockets

        if force_refresh_approval_key:
            self._approval_key = await self._rest.get_approval_key(force=True)

        url = self._ws_url or KIS_WS_URLS[self._env]
        try:
            self._ws = await websockets.connect(
                url,
                ping_interval=_HEARTBEAT_INTERVAL,
                ping_timeout=10,
                max_size=2**20,  # 1 MB max message size
            )
        except Exception as e:
            raise ConnectionError(f"KIS WebSocket connection failed: {e}") from e

        self._connected = True
        self._reconnect_delay = _INITIAL_RECONNECT_DELAY
        logger.info("KIS WebSocket connected to %s", url)

        # Start background tasks
        self._reader_task = asyncio.create_task(self._reader_loop())

        # Resubscribe after reconnect
        await self._resubscribe_all()

    async def disconnect(self) -> None:
        """Disconnect from the KIS WebSocket server."""
        self._should_reconnect = False
        self._connected = False

        # Cancel background tasks
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

        if self._ws is not None:
            try:
                await self._ws.close()
            except RuntimeError:
                # Python 3.14+: websockets/httpcore may raise RuntimeError
                # ('Event loop is closed') during teardown when the event
                # loop has already been shut down.  Safe to ignore — the
                # connection is already being torn down.
                pass
            self._ws = None

        logger.info("KIS WebSocket disconnected")

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket transport is currently connected."""
        return self._connected

    @property
    def is_reconnecting(self) -> bool:
        """Whether a reconnect attempt is in progress after an unexpected drop."""
        return (not self._connected) and self._should_reconnect

    async def __aenter__(self) -> KISWebSocketClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        channel: str,
        tr_key: str,
        *,
        critical: bool = False,
    ) -> bool:
        """Subscribe to a real-time channel.

        Parameters
        ----------
        channel : str
            KIS channel ID (e.g., ``"H0STCNT0"``, ``"H0STCNI0"``).
        tr_key : str
            Stock code or account number for the subscription.
        critical : bool
            If ``True``, uses the critical subscription budget.
            Critical subscriptions are protected from eviction.

        Returns
        -------
        bool
            ``True`` if the subscription was successful.
        """
        # Budget check
        if critical:
            if not self._budget.subscribe_critical():
                logger.warning("Critical subscription budget exhausted for %s/%s", channel, tr_key)
                return False
        else:
            if not self._budget.subscribe_optional():
                logger.warning("Optional subscription budget exhausted for %s/%s", channel, tr_key)
                return False

        # Track subscription for resubscribe
        target = self._critical_subscriptions if critical else self._subscriptions
        if channel not in target:
            target[channel] = set()
        target[channel].add(tr_key)

        # Send subscribe frame
        if self._connected and self._ws is not None:
            await self._send_subscribe_frame(channel, tr_key)

        logger.info("Subscribed to %s/%s (critical=%s)", channel, tr_key, critical)
        return True

    async def unsubscribe(
        self,
        channel: str,
        tr_key: str,
        *,
        critical: bool = False,
    ) -> None:
        """Unsubscribe from a real-time channel."""
        target = self._critical_subscriptions if critical else self._subscriptions
        if channel in target:
            target[channel].discard(tr_key)
            if not target[channel]:
                del target[channel]

        self._budget.unsubscribe(critical=critical, optional=not critical)

        if self._connected and self._ws is not None:
            await self._send_unsubscribe_frame(channel, tr_key)

        logger.info("Unsubscribed from %s/%s", channel, tr_key)

    # ------------------------------------------------------------------
    # Message consumption
    # ------------------------------------------------------------------

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """Async generator yielding parsed WebSocket messages.

        Messages are normalised by ``ws_parser.parse_message()`` and
        have at least a ``"type"`` key:
        - ``"subscription_ack"``
        - ``"real_time_data"``
        - ``"error"``
        - ``"unknown"``
        """
        while self._should_reconnect or not self._message_queue.empty():
            try:
                msg = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0,
                )
                yield msg
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------
    # Internal: reader loop
    # ------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        """Background task that reads raw messages from the WebSocket."""
        while self._connected and self._ws is not None:
            try:
                raw = await self._ws.recv()
            except Exception as e:
                logger.warning("WebSocket read error: %s", e)
                await self._handle_disconnect()
                return

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            try:
                parsed = parse_message(raw)
            except Exception as e:
                logger.error("Failed to parse WebSocket message: %s", e)
                continue

            # Track continuum for gap detection
            if parsed.get("type") == "real_time_data":
                tr_id = parsed.get("tr_id", "")
                continuum_key = parsed.get("continuum_key", "")
                if tr_id and continuum_key:
                    self._continuum_tracker[tr_id] = continuum_key

            # Emit to callback if configured
            if self._on_event is not None:
                try:
                    self._on_event(parsed)
                except Exception as e:
                    logger.error("Event callback failed: %s", e)

            # Enqueue for consumer
            try:
                self._message_queue.put_nowait(parsed)
            except asyncio.QueueFull:
                logger.warning("Message queue full, dropping message: %s", parsed.get("type"))


    # ------------------------------------------------------------------
    # Internal: disconnect handling
    # ------------------------------------------------------------------

    async def _handle_disconnect(self) -> None:
        """Handle unexpected disconnection with exponential backoff reconnect."""
        self._connected = False
        logger.warning(
            "KIS WebSocket disconnected, reconnecting in %.1fs...",
            self._reconnect_delay,
        )

        if not self._should_reconnect:
            return

        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(
            self._reconnect_delay * _RECONNECT_MULTIPLIER,
            _MAX_RECONNECT_DELAY,
        )

        try:
            await self.connect(force_refresh_approval_key=True)
        except Exception as e:
            logger.error("Reconnect failed: %s", e)
            # Schedule another reconnect attempt
            asyncio.create_task(self._handle_disconnect())

    # ------------------------------------------------------------------
    # Internal: subscribe / unsubscribe frames
    # ------------------------------------------------------------------

    async def _send_subscribe_frame(self, channel: str, tr_key: str) -> None:
        """Send a JSON subscribe frame to the WebSocket."""
        frame = {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": "1",  # 1 = subscribe
                "content_type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": channel,
                    "tr_key": tr_key,
                }
            },
        }
        if self._ws is not None:
            await self._ws.send(json.dumps(frame, ensure_ascii=False))

    async def _send_unsubscribe_frame(self, channel: str, tr_key: str) -> None:
        """Send a JSON unsubscribe frame to the WebSocket."""
        frame = {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": "2",  # 2 = unsubscribe
                "content_type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": channel,
                    "tr_key": tr_key,
                }
            },
        }
        if self._ws is not None:
            await self._ws.send(json.dumps(frame, ensure_ascii=False))

    async def _resubscribe_all(self) -> None:
        """Resubscribe to all tracked subscriptions after reconnect."""
        # Critical first
        for channel, tr_keys in self._critical_subscriptions.items():
            for tr_key in tr_keys:
                await self._send_subscribe_frame(channel, tr_key)

        # Then optional
        for channel, tr_keys in self._subscriptions.items():
            for tr_key in tr_keys:
                await self._send_subscribe_frame(channel, tr_key)

    # ------------------------------------------------------------------
    # Gap detection
    # ------------------------------------------------------------------

    def get_last_continuum(self, tr_id: str) -> str | None:
        """Get the last continuum key for a channel (for gap detection)."""
        return self._continuum_tracker.get(tr_id)

    def detect_gap(self, tr_id: str, continuum_key: str) -> bool:
        """Check if there is a gap between the last known continuum and the current one.

        Returns ``True`` if a gap is detected (messages were missed).
        """
        last_key = self._continuum_tracker.get(tr_id)
        if last_key is None:
            return False
        # Continuum keys are sequential integers as strings
        try:
            return int(continuum_key) - int(last_key) > 1
        except (ValueError, TypeError):
            return False


# Type alias for async generator
from collections.abc import AsyncIterator
