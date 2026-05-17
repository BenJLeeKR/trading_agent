"""KIS 163 장운영정보 (통합) WebSocket adapter — 실시간 장상태.

| 항목 | 내용 |
|------|------|
| Endpoint | ``ws://{base_ws_url}/websocket`` |
| TR ID | ``H0UNMKO0`` (국내주식 장운영정보 통합) |
| 인증 | ``POST /oauth2/Approval`` 로 발급받은 approval key |
| Heartbeat | 30초 간격 ping/pong |
| 재연결 | Exponential backoff: 1s→2s→4s→…→max 30s, 최대 5회 |

Paper (모의투자) 환경에서는 WebSocket 연결을 건너뛰고
``is_connected()`` 가 항상 ``False`` 를 반환한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import httpx

from agent_trading.brokers.koreainvestment.token_cache import (
    CachePurpose,
    KisTokenCache,
    KisTokenCacheConfig,
)
from agent_trading.config.settings import AppSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Market phase codes (P2: new enum values matching spec)
# ---------------------------------------------------------------------------

class MarketPhaseCode(str, Enum):
    """장운영 구분 코드 (P2: 사람이 읽을 수 있는 문자열 값).

    Mapping from KIS 163 ``MKOP_CLS_CODE`` response codes:
        "0" → PRE_MARKET (장개시 전)
        "1" → OPEN (정규장)
        "2" → CLOSING (동시호가)
        "3" → AFTER_HOURS (시간외)
        "4" → HALT (일시정지)
        "5" → HALT (폐장)
        otherwise → UNKNOWN
    """

    PRE_MARKET = "PRE_MARKET"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    AFTER_HOURS = "AFTER_HOURS"
    HALT = "HALT"
    UNKNOWN = "UNKNOWN"


# Mapping from raw MKOP_CLS_CODE → MarketPhaseCode
_MKOP_CLS_MAP: dict[str, MarketPhaseCode] = {
    "0": MarketPhaseCode.PRE_MARKET,
    "1": MarketPhaseCode.OPEN,
    "2": MarketPhaseCode.CLOSING,
    "3": MarketPhaseCode.AFTER_HOURS,
    "4": MarketPhaseCode.HALT,
    "5": MarketPhaseCode.HALT,
}


def _map_mkop_cls_code(raw: str) -> MarketPhaseCode:
    """Map a raw ``MKOP_CLS_CODE`` string to ``MarketPhaseCode``.

    Returns ``UNKNOWN`` for unrecognised values.
    """
    return _MKOP_CLS_MAP.get(raw, MarketPhaseCode.UNKNOWN)


# ---------------------------------------------------------------------------
# MarketState dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MarketState:
    """실시간 장운영 상태 정보 (163 WebSocket 응답 정규화).

    Attributes:
        timestamp: 상태 획득 시각 (UTC).
        mkop_cls_code: 원본 장운영 구분 코드 (예: ``"0"``).
        phase: ``MarketPhaseCode`` enum.
        vi_cls_code: VI적용구분코드 (0=미적용, 1=정적VI, 2=동적VI).
        trht_yn: 거래정지 여부 (Y/N).
        exch_cls_code: 거래소 구분코드.
        raw: 원본 응답 데이터 (디버깅용).
    """

    timestamp: datetime
    mkop_cls_code: str
    phase: MarketPhaseCode = MarketPhaseCode.UNKNOWN
    vi_cls_code: str = ""
    trht_yn: str = "N"
    exch_cls_code: str = ""
    raw: dict | None = None


# ---------------------------------------------------------------------------
# MarketStateListener (callback protocol)
# ---------------------------------------------------------------------------


class MarketStateListener(Protocol):
    """Callback interface for receiving market state updates.

    Implementations are invoked by ``KisMarketStateClient`` whenever a new
    ``H0UNMKO0`` message arrives over the WebSocket.
    """

    async def on_market_state_changed(self, state: MarketState) -> None:
        """Called when a new market state message is received.

        Args:
            state: The parsed ``MarketState`` from the 163 WebSocket.
        """
        ...


# ---------------------------------------------------------------------------
# MarketStateProvider (ABC)
# ---------------------------------------------------------------------------


class MarketStateProvider(ABC):
    """실시간 장운영 상태 제공자 추상 인터페이스."""

    @abstractmethod
    async def get_current_state(self) -> MarketState:
        """현재 (마지막으로 수신된) 장운영 상태 반환.

        WebSocket이 아직 연결되지 않았거나 데이터를 한 번도 수신하지
        않은 경우 ``UNKNOWN`` phase의 기본 상태를 반환한다.
        """
        ...

    @abstractmethod
    async def connect(self) -> None:
        """WebSocket 연결 수립."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """WebSocket 연결 종료."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """WebSocket 연결 상태."""
        ...


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# WebSocket 163 TR ID
_H0UNMKO0_TR_ID = "H0UNMKO0"

# Heartbeat interval (seconds)
_WS_HEARTBEAT_INTERVAL = 30

# Reconnect backoff parameters
_INITIAL_BACKOFF = 1.0  # seconds
_MAX_BACKOFF = 30.0  # seconds
_BACKOFF_MULTIPLIER = 2.0
_MAX_RECONNECT_ATTEMPTS = 5

# Approval key cache constants
_APPROVAL_KEY_EXPIRY = 86400  # 24h
_APPROVAL_KEY_REFRESH_MARGIN = 300  # refresh 5 min early


# ---------------------------------------------------------------------------
# Live-info token cache helpers (approval key)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# KisMarketStateClient (full implementation)
# ---------------------------------------------------------------------------


class KisMarketStateClient(MarketStateProvider):
    """163 국내주식 장운영정보 WebSocket adapter (full implementation).

    P2 구현 항목:
    - ``httpx`` 기반 approval key 발급 (``POST /oauth2/Approval``)
    - ``websockets`` 라이브러리 기반 async WebSocket client
    - Exponential backoff 재연결 (1s→2s→4s→…→max 30s, 최대 5회)
    - 30초 heartbeat (ping/pong)
    - ``H0UNMKO0`` 응답 파싱 → ``MarketState``
    - Listener pattern (``MarketStateListener`` protocol)
    - Paper 환경 skip + warning log
    - Live-info token cache (approval key 파일 캐시)
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        app_key: str,
        api_secret: str,
        base_ws_url: str | None = None,
        listeners: list[MarketStateListener] | None = None,
    ) -> None:
        """Initialize the 163 WebSocket adapter.

        Args:
            settings: ``AppSettings`` — used for live-info token cache config.
            app_key: KIS API app key.
            api_secret: KIS API secret.
            base_ws_url: WebSocket base URL. If ``None``, derived from env
                (``KIS_LIVE_INFO_WS_URL`` or ``KIS_BASE_WS_URL``).
            listeners: Optional initial set of ``MarketStateListener`` s.
        """
        self._settings = settings
        self._app_key = app_key
        self._api_secret = api_secret
        self._base_ws_url = base_ws_url or ""
        self._listeners: list[MarketStateListener] = list(listeners or [])

        # Internal state
        self._connected = False
        self._last_state: MarketState = MarketState(
            timestamp=datetime.now(timezone.utc),
            mkop_cls_code="",
            phase=MarketPhaseCode.UNKNOWN,
        )
        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._approval_key: str | None = None
        self._approval_key_expires_at: float = 0.0
        self._http_client: httpx.AsyncClient | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._reconnect_attempts = 0
        self._shutdown_event = asyncio.Event()

        # Approval key cache via KisTokenCache
        self._approval_cache = KisTokenCache(KisTokenCacheConfig(
            enabled=settings.kis_live_token_cache_enabled,
            cache_path=Path(settings.kis_live_token_cache_path),
            cache_purpose=CachePurpose.LIVE_APPROVAL_KEY,
            fingerprint_input=f"live_info_{app_key}_{api_secret}",
            extra_validators={
                "cache_type": "approval_key",
            },
            load_expiry_buffer=60.0,
            save_expiry_buffer=300.0,
        ))

        # 163 WebSocket is driven by live-info dedicated credentials,
        # not by the trading environment (paper/mock/live).
        # If credentials are provided, we attempt connection regardless of env.
        if not app_key or not api_secret:
            logger.warning(
                "KisMarketStateClient: 163 WebSocket not available (no live-info credentials)"
            )
            self._is_paper = True  # credential 없으면 skip
        else:
            self._is_paper = False  # live-info credential으로 직접 연결

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_current_state(self) -> MarketState:
        """Return the last received ``MarketState``.

        If no data has been received yet, returns ``UNKNOWN`` phase.
        """
        return self._last_state

    async def connect(self) -> None:
        """Establish WebSocket connection.

        Paper env: logs warning and returns immediately.
        """
        if self._is_paper:
            logger.warning(
                "KisMarketStateClient[paper]: connect() skipped — "
                "163 WebSocket not available in paper environment."
            )
            return

        if self._connected:
            logger.debug("KisMarketStateClient: already connected")
            return

        self._shutdown_event.clear()
        self._reconnect_attempts = 0

        # Ensure approval key
        await self._ensure_approval_key()

        # Start connection task
        task = asyncio.create_task(self._run_connection_loop())
        self._tasks.append(task)

    async def disconnect(self) -> None:
        """Gracefully disconnect the WebSocket."""
        self._shutdown_event.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

        # Close HTTP client
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        logger.info("KisMarketStateClient: disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Listener management
    # ------------------------------------------------------------------

    def add_listener(self, listener: MarketStateListener) -> None:
        """Register a market state change listener."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: MarketStateListener) -> None:
        """Unregister a market state change listener."""
        self._listeners = [l for l in self._listeners if l is not listener]

    # ------------------------------------------------------------------
    # Approval key (REST)
    # ------------------------------------------------------------------

    async def _ensure_approval_key(self) -> str:
        """Obtain (or return cached) WebSocket approval key.

        Uses KisTokenCache for persistence across restarts.
        """
        # 1. Try in-memory cache
        now_wall = time.time()
        if self._approval_key is not None and now_wall < self._approval_key_expires_at:
            return self._approval_key

        # 2. Try file cache via KisTokenCache
        cached = await self._approval_cache.load()
        if cached is not None:
            self._approval_key = cached
            # Set expiry from cache (24h from file creation — conservative)
            self._approval_key_expires_at = now_wall + _APPROVAL_KEY_EXPIRY - _APPROVAL_KEY_REFRESH_MARGIN
            return cached

        # 3. HTTP: POST /oauth2/Approval
        client = await self._get_http_client()
        body = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "secretkey": self._api_secret,
        }
        try:
            resp = await client.post(
                "/oauth2/Approval",
                json=body,
            )
        except RuntimeError:
            raise RuntimeError(
                "KisMarketStateClient: event loop closed during approval key HTTP request "
                "(Python 3.14 httpx teardown issue)."
            ) from None

        resp.raise_for_status()
        data = resp.json()

        approval_key: str = data["approval_key"]
        expires_in = int(data.get("expires_in", _APPROVAL_KEY_EXPIRY))
        expires_at = now_wall + expires_in - _APPROVAL_KEY_REFRESH_MARGIN

        self._approval_key = approval_key
        self._approval_key_expires_at = expires_at

        # 4. Persist to live-info token cache via KisTokenCache
        await self._approval_cache.save(approval_key, expires_in)

        logger.info(
            "KisMarketStateClient: approval key obtained (expires_at=%s)",
            expires_at,
        )
        return approval_key

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy-initialized HTTP client for approval key requests."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self._base_ws_url.replace("ws://", "http://").replace("wss://", "https://"),
                timeout=10.0,
            )
        return self._http_client

    # ------------------------------------------------------------------
    # WebSocket connection loop
    # ------------------------------------------------------------------

    async def _run_connection_loop(self) -> None:
        """Main connection loop with reconnection support."""
        import websockets

        ws_url = self._resolve_ws_url()

        while not self._shutdown_event.is_set():
            try:
                # Connect
                logger.info(
                    "KisMarketStateClient: connecting to %s (attempt %d)",
                    ws_url,
                    self._reconnect_attempts + 1,
                )

                extra_headers = {
                    "approval_key": self._approval_key or "",
                }
                self._ws = await websockets.connect(
                    ws_url,
                    extra_headers=extra_headers,
                    ping_interval=_WS_HEARTBEAT_INTERVAL,
                    ping_timeout=10,
                    close_timeout=5,
                )
                self._connected = True
                self._reconnect_attempts = 0
                logger.info("KisMarketStateClient: connected")

                # Subscribe to H0UNMKO0
                await self._send_subscribe()

                # Message receive loop
                await self._message_loop()

            except asyncio.CancelledError:
                logger.info("KisMarketStateClient: connection task cancelled")
                self._connected = False
                return

            except Exception as exc:
                logger.warning(
                    "KisMarketStateClient: connection error: %s",
                    exc,
                    exc_info=True,
                )
                self._connected = False
                self._ws = None

                if self._shutdown_event.is_set():
                    return

                # Exponential backoff reconnect
                self._reconnect_attempts += 1
                if self._reconnect_attempts > _MAX_RECONNECT_ATTEMPTS:
                    logger.error(
                        "KisMarketStateClient: max reconnect attempts (%d) reached. Giving up.",
                        _MAX_RECONNECT_ATTEMPTS,
                    )
                    return

                delay = min(
                    _INITIAL_BACKOFF * (_BACKOFF_MULTIPLIER ** (self._reconnect_attempts - 1)),
                    _MAX_BACKOFF,
                )
                logger.info(
                    "KisMarketStateClient: reconnecting in %.1fs (attempt %d/%d)",
                    delay,
                    self._reconnect_attempts,
                    _MAX_RECONNECT_ATTEMPTS,
                )
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=delay,
                    )
                    # If shutdown event is set during wait, exit
                    return
                except asyncio.TimeoutError:
                    continue  # Timeout means we should retry

    async def _send_subscribe(self) -> None:
        """Send H0UNMKO0 subscription message over WebSocket."""
        if self._ws is None:
            return
        sub_body = {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": "1",  # 1=register, 2=unregister
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": _H0UNMKO0_TR_ID,
                    "tr_key": "H0UNMKO0",  # dummy tr_key for subscription
                }
            },
        }
        await self._ws.send(json.dumps(sub_body))
        logger.debug("KisMarketStateClient: subscribed to H0UNMKO0")

    async def _message_loop(self) -> None:
        """Receive and process WebSocket messages."""
        if self._ws is None:
            return

        try:
            async for raw_message in self._ws:
                if self._shutdown_event.is_set():
                    break
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning(
                        "KisMarketStateClient: invalid JSON message: %s",
                        raw_message[:200],
                    )
                    continue

                # Check for H0UNMKO0 data
                await self._process_message(data)

        except websockets.exceptions.ConnectionClosed:
            logger.info("KisMarketStateClient: WebSocket connection closed")
        except Exception as exc:
            logger.warning(
                "KisMarketStateClient: message loop error: %s",
                exc,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Message processing
    # ------------------------------------------------------------------

    async def _process_message(self, data: dict[str, Any]) -> None:
        """Process a single WebSocket message.

        H0UNMKO0 real-time messages have the format:
        ``{"header": {...}, "body": {...}}``

        The ``body`` contains:
        - ``mkop_cls_code``: 장운영구분코드 ("0"~"5")
        - ``antc_mkop_cls_code``: 예상장구분코드
        - ``vi_cls_code``: VI적용구분코드
        - ``trht_yn``: 거래정지여부
        - ``exch_cls_code``: 거래소구분코드
        """
        # Check for system/error messages
        header = data.get("header", {})
        if isinstance(header, dict):
            tr_id = header.get("tr_id", "")
            if tr_id and tr_id != _H0UNMKO0_TR_ID:
                # Not a H0UNMKO0 message — could be a system message
                logger.debug(
                    "KisMarketStateClient: received non-H0UNMKO0 message: tr_id=%s",
                    tr_id,
                )
                return

        # Extract body
        body = data.get("body", {})
        if not isinstance(body, dict):
            return

        raw_mkop_cls_code = body.get("mkop_cls_code", "") or ""
        if not raw_mkop_cls_code:
            # Not a market state message
            return

        # Parse fields
        phase = _map_mkop_cls_code(raw_mkop_cls_code)
        now = datetime.now(timezone.utc)

        state = MarketState(
            timestamp=now,
            mkop_cls_code=raw_mkop_cls_code,
            phase=phase,
            vi_cls_code=body.get("vi_cls_code", ""),
            trht_yn=body.get("trht_yn", "N"),
            exch_cls_code=body.get("exch_cls_code", ""),
            raw=data,  # keep the entire message for debugging
        )

        prev_phase = self._last_state.phase
        self._last_state = state

        # Log phase change
        if prev_phase != phase:
            logger.info(
                "KisMarketStateClient: phase change %s → %s (raw=%s)",
                prev_phase.value,
                phase.value,
                raw_mkop_cls_code,
            )

        # Notify listeners
        for listener in self._listeners:
            try:
                await listener.on_market_state_changed(state)
            except Exception:
                logger.exception(
                    "KisMarketStateClient: listener %s failed",
                    listener,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_ws_url(self) -> str:
        """Resolve the WebSocket URL.

        Priority:
        1. ``self._base_ws_url`` (explicitly provided)
        2. ``KIS_LIVE_INFO_WS_URL`` env var → ``ws://{value}/websocket``
        3. ``KIS_BASE_WS_URL`` env var → ``ws://{value}/websocket``
        4. ``KIS_BASE_URL`` + ``ws://`` prefix → ``ws://{base}/websocket``
        """
        if self._base_ws_url:
            base = self._base_ws_url
        else:
            # Try settings-derived URLs
            base = getattr(self._settings, "kis_live_info_ws_url", None) or ""
            if not base:
                base = getattr(self._settings, "kis_base_ws_url", "") or ""
            if not base:
                # Fallback: use HTTP base URL, convert to ws://
                base_url = getattr(self._settings, "kis_real_rest_base_url", "")
                base = base_url.replace("https://", "").replace("http://", "")

        if not base.startswith("ws://") and not base.startswith("wss://"):
            base = f"ws://{base}"

        if not base.endswith("/websocket"):
            base = f"{base.rstrip('/')}/websocket"

        return base


# ---------------------------------------------------------------------------
# SimpleMarketStateListener (logging helper)
# ---------------------------------------------------------------------------


class SimpleMarketStateListener:
    """Minimal listener that logs phase changes.

    Useful for debugging and monitoring.
    """

    async def on_market_state_changed(self, state: MarketState) -> None:
        """Log the market state change."""
        logger.info(
            "Market state: phase=%s raw_mkop=%s vi=%s trht=%s exch=%s",
            state.phase.value,
            state.mkop_cls_code,
            state.vi_cls_code,
            state.trht_yn,
            state.exch_cls_code,
        )
