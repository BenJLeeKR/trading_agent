"""KIS WebSocket-backed ``RealtimeQuoteSource`` (Step 3) — 실시간 현재가 조회 전용.

This is the **only** module that opens a live KIS WebSocket connection for
the "실시간 현재가 조회" Admin UI screen
(``plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md``).

Account isolation (critical invariant — see plan Step 3 §8 안전장치)
---------------------------------------------------------------------
This module is wired **exclusively** with the dedicated
``KIS_REALTIME_QUOTE_APP_KEY``/``_APP_SECRET`` credentials
(``runtime.bootstrap.build_realtime_quote_source()``). It never touches:

- the trading account's ``KISRestClient``/``KoreaInvestmentAdapter``
  (``KIS_APP_KEY`` / ``KIS_API_KEY``)
- the disclosure account's client (``KIS_LIVE_INFO_*``)
- ``OrderManager`` / ``ReconciliationService`` / the decision pipeline
- ``ops-scheduler`` — this connection lives and dies with the ``api``
  process only (see ``api/app.py`` lifespan wiring)

Reuse (what this module does NOT reimplement)
----------------------------------------------
- ``KISRestClient.get_approval_key()`` — approval key issuance, file cache,
  1-RPS lock, all unchanged. Only the *credentials* passed to the
  ``KISRestClient`` instance differ from the trading/disclosure clients.
- ``KISWebSocketClient`` — connection lifecycle, exponential-backoff
  reconnect, subscribe/unsubscribe framing, ``SubscriptionBudget``
  enforcement. Used completely unmodified (aside from two new read-only
  ``is_connected``/``is_reconnecting`` properties added for observability).
- ``ws_parser.is_json_message`` — used upstream by ``websocket_client.py`` to
  detect JSON ack/error frames before they reach this module.

What this module writes fresh
------------------------------
- Full-field extraction from the 172(체결가)/178(호가) delimited payload.
  The shared ``ws_parser.parse_trade_price()``/``parse_orderbook()``/
  ``parse_delimited_message()`` functions assume the 3-part
  ``tr_id|continuum_key|body`` envelope verified for ``H0STCNI0`` (체결통보);
  the actual live wire format for ``H0STCNT0``/``H0STASP0`` is the 4-part
  ``encrypt_flag|tr_id|data_cnt|body`` (실측 2026-07-09, see
  ``_split_realtime_frame``). Reusing the shared parser for these two
  channels silently misclassified every tick as ``tr_id="0"``/``type=
  "unknown"`` and dropped it. This module re-splits ``msg["raw"]`` locally
  instead (see ``_split_realtime_frame`` / ``_parse_trade_fields`` /
  ``_parse_orderbook_fields``), and never touches the shared parser, so the
  existing ``H0STCNI0`` order-fill path is unaffected.
- The subscription/session model: **single app process, single implicit
  viewer** — matches Step 3 scope. A per-viewer reference count or
  multi-consumer session registry (for when multiple browser tabs need
  independently-managed views) is deliberately deferred; see
  ``realtime_quote_source.py`` module docstring "Subscription model" note,
  which applies identically here.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from agent_trading.brokers.base import SubscriptionBudget
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.koreainvestment.websocket_client import KISWebSocketClient
from agent_trading.services.realtime_quote_source import (
    DEFAULT_MAX_REGISTRATIONS,
    MAX_DAILY_PRICE_HISTORY,
    MAX_TRADE_HISTORY,
    REGISTRATIONS_PER_SYMBOL,
    ConnectionState,
    DailyPriceBar,
    InstrumentInfo,
    QuoteLevel,
    QuoteSnapshot,
    SubscriptionLimitExceededError,
    TradeTick,
    _validate_symbol,
    default_instrument_info,
)

logger = logging.getLogger(__name__)

_TRADE_CHANNEL = "H0STCNT0"  # 실시간체결가 (KRX)
_ORDERBOOK_CHANNEL = "H0STASP0"  # 실시간호가 (KRX)

# 실측(2026-07-09) 기준 KIS가 실제로 보내는 H0STCNT0/H0STASP0 raw frame 포맷은
#   {encrypt_flag}|{tr_id}|{data_cnt}|{body}
# 4-part 포맷이다. 공유 ``ws_parser.parse_delimited_message()``는
# ``tr_id|continuum_key|body`` 3-part 포맷을 가정하므로(H0STCNI0 체결통보 전용으로
# 검증된 형식 — 그 경로는 이번에 건드리지 않는다), 이 두 채널에는 맞지 않아
# parts[0]("0", encrypt_flag)을 tr_id로 오인해 모든 tick이 무조건 "unknown"으로
# 분류/드롭되는 버그가 있었다. 아래 ``_split_realtime_frame``이 이 두 채널
# 전용으로 raw 문자열을 직접 재분리한다(공유 파서는 그대로 둔다).
def _split_realtime_frame(raw: str) -> tuple[str, list[str]] | None:
    """Split a raw KIS realtime frame as ``encrypt_flag|tr_id|data_cnt|body``.

    Returns ``(tr_id, fields)`` where ``fields`` has a leading empty string
    prepended so the existing 1-indexed field-layout constants in
    ``_parse_trade_fields``/``_parse_orderbook_fields`` (verified against real
    ``H0STCNT0``/``H0STASP0`` samples once the envelope is stripped) continue
    to apply unchanged. Returns ``None`` if the frame doesn't have the
    expected 4 pipe-separated parts.
    """
    parts = raw.split("|")
    if len(parts) < 4:
        return None
    tr_id = parts[1]
    body = "|".join(parts[3:])
    return tr_id, [""] + body.split("^")

_HOUR_CLASS_LABELS: dict[str, str] = {
    "0": "장중",
    "A": "장후예상",
    "B": "장전예상",
    "C": "VI발동",
    "D": "시간외단일가",
}


# ---------------------------------------------------------------------------
# Field extraction — see module docstring "What this module writes fresh"
# ---------------------------------------------------------------------------


def _f(fields: list[str], idx: int) -> str:
    return fields[idx] if 0 <= idx < len(fields) else ""


def _to_float(raw: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _to_int(raw: str) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _parse_trade_fields(fields: list[str]) -> dict[str, Any]:
    """Extract the full 172(체결가 KRX) field set.

    Field layout (1-indexed — ``fields[0]`` is the empty string from the
    leading ``^`` in the raw KIS payload, matching
    ``ws_parser.parse_orderbook``'s documented convention)::

        1  MKSC_SHRN_ISCD (stock_code)     8  STCK_OPRC       36 TRHT_YN
        2  STCK_CNTG_HOUR (trade_time)     9  STCK_HGPR       44 HOUR_CLS_CODE
        3  STCK_PRPR (last_price)          10 STCK_LWPR       46 VI_STND_PRC
        5  PRDY_VRSS (change)              13 CNTG_VOL (tick_volume)
        6  PRDY_CTRT (change_rate)         14 ACML_VOL
                                            15 ACML_TR_PBMN
    """
    change = _to_float(_f(fields, 5))
    change_sign = "up" if change > 0 else "down" if change < 0 else "flat"
    return {
        "last_price": _to_float(_f(fields, 3)),
        "change": change,
        "change_rate": _to_float(_f(fields, 6)),
        "change_sign": change_sign,
        "open_price": _to_float(_f(fields, 8)),
        "high_price": _to_float(_f(fields, 9)),
        "low_price": _to_float(_f(fields, 10)),
        "tick_volume": _to_int(_f(fields, 13)),
        "accumulated_volume": _to_int(_f(fields, 14)),
        "accumulated_value": _to_int(_f(fields, 15)),
        "trade_time": _f(fields, 2),
        "trading_halted": _f(fields, 36) == "Y",
        "hour_class": _HOUR_CLASS_LABELS.get(_f(fields, 44), "장중"),
        "vi_stnd_price": _to_float(_f(fields, 46)),
    }


def _parse_orderbook_fields(fields: list[str]) -> dict[str, Any]:
    """Extract the 178(호가 KRX) field set (10-level price ladder + totals).

    Field layout (1-indexed, same leading-empty convention as above)::

        1     MKSC_SHRN_ISCD (stock_code)
        4-13  ASKP1..10
        14-23 BIDP1..10
        24-33 ASKP_RSQN1..10
        34-43 BIDP_RSQN1..10
        44    TOTAL_ASKP_RSQN
        45    TOTAL_BIDP_RSQN

    실측(2026-07-09) 검증: 위 전체 필드 레이아웃(가격 10+10, 잔량 10+10, 총잔량 2)이
    실제 live 프레임에서 그대로 채워지는 것을 ``get_snapshots()`` 응답으로 확인했다
    (일부 초기 샘플에서 잔량 필드가 적게 보였던 것은 그 tick이 우연히 짧은 프레임이었을
    뿐, 구조적 누락이 아니었다). 다만 개별 프레임이 트레일링 필드를 덜 보낼 가능성은
    여전히 있으므로 ``_f()``의 out-of-range → ``""``/``0`` 기본값 처리는 그대로 유지한다.
    """
    ask_prices = [_to_float(_f(fields, i)) for i in range(4, 14)]
    bid_prices = [_to_float(_f(fields, i)) for i in range(14, 24)]
    ask_qty = [_to_int(_f(fields, i)) for i in range(24, 34)]
    bid_qty = [_to_int(_f(fields, i)) for i in range(34, 44)]
    return {
        "ask_levels": [QuoteLevel(price=p, quantity=q) for p, q in zip(ask_prices, ask_qty)],
        "bid_levels": [QuoteLevel(price=p, quantity=q) for p, q in zip(bid_prices, bid_qty)],
        "total_ask_quantity": _to_int(_f(fields, 44)),
        "total_bid_quantity": _to_int(_f(fields, 45)),
    }


# ---------------------------------------------------------------------------
# Per-symbol live state
# ---------------------------------------------------------------------------


@dataclass
class _SymbolState:
    """Mutable per-symbol state, updated in place as WS messages arrive."""

    has_price_data: bool = False
    has_orderbook_data: bool = False

    # -- from H0STCNT0 --
    last_price: float = 0.0
    change: float = 0.0
    change_rate: float = 0.0
    change_sign: str = "flat"
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    accumulated_volume: int = 0
    accumulated_value: int = 0
    trade_time: str = ""
    hour_class: str = "장중"
    trading_halted: bool = False
    vi_stnd_price: float = 0.0
    recent_trades: deque[TradeTick] = field(default_factory=lambda: deque(maxlen=MAX_TRADE_HISTORY))

    # -- from H0STASP0 --
    ask_levels: list[QuoteLevel] = field(default_factory=list)
    bid_levels: list[QuoteLevel] = field(default_factory=list)
    total_ask_quantity: int = 0
    total_bid_quantity: int = 0

    # -- static reference, one-shot REST fetch at subscribe time --
    prev_close: float = 0.0
    upper_limit: float = 0.0
    lower_limit: float = 0.0
    per: float | None = None
    pbr: float | None = None
    eps: float | None = None
    bps: float | None = None

    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def apply_trade(self, parsed: dict[str, Any]) -> None:
        self.has_price_data = True
        self.last_price = parsed["last_price"]
        self.change = parsed["change"]
        self.change_rate = parsed["change_rate"]
        self.change_sign = parsed["change_sign"]
        self.open_price = parsed["open_price"]
        self.high_price = parsed["high_price"]
        self.low_price = parsed["low_price"]
        self.accumulated_volume = parsed["accumulated_volume"]
        self.accumulated_value = parsed["accumulated_value"]
        self.trade_time = parsed["trade_time"]
        self.trading_halted = parsed["trading_halted"]
        self.hour_class = parsed["hour_class"]
        self.vi_stnd_price = parsed["vi_stnd_price"]
        self.updated_at = datetime.now(timezone.utc)
        # 마감 후 KIS가 동일한 마지막 체결 프레임을 반복 전송할 때, 그걸 매번
        # "새 체결"로 착각해 recent_trades에 또 appendleft하면 안 된다 — 실제로는
        # 새 거래가 아니라 같은 프레임의 재전송이다. trade_time+price+volume이
        # 직전 tick과 완전히 같으면 재전송으로 간주하고 history에는 추가하지 않는다.
        latest = self.recent_trades[0] if self.recent_trades else None
        if (
            latest is None
            or latest.trade_time != parsed["trade_time"]
            or latest.price != parsed["last_price"]
            or latest.volume != parsed["tick_volume"]
        ):
            # appendleft + maxlen → recent_trades stays newest-first without
            # needing a reverse() on every read.
            self.recent_trades.appendleft(
                TradeTick(
                    trade_time=parsed["trade_time"],
                    price=parsed["last_price"],
                    change=parsed["change"],
                    change_rate=parsed["change_rate"],
                    volume=parsed["tick_volume"],
                )
            )

    def apply_orderbook(self, parsed: dict[str, Any]) -> None:
        self.has_orderbook_data = True
        self.ask_levels = parsed["ask_levels"]
        self.bid_levels = parsed["bid_levels"]
        self.total_ask_quantity = parsed["total_ask_quantity"]
        self.total_bid_quantity = parsed["total_bid_quantity"]
        self.updated_at = datetime.now(timezone.utc)

    def apply_static_reference(self, raw_quote: dict[str, Any]) -> None:
        """Apply one-shot REST 정적 참조값 (029_주식현재가_시세.md, FHKST01010100).

        Best-effort — missing/unparseable fields are left at their defaults
        (0.0 / None) rather than raising, since this enrichment must never
        block a subscribe() call.
        """
        self.prev_close = _to_float(raw_quote.get("stck_sdpr", ""))
        self.upper_limit = _to_float(raw_quote.get("stck_mxpr", ""))
        self.lower_limit = _to_float(raw_quote.get("stck_llam", ""))
        self.per = _to_float(raw_quote.get("per", "")) or None
        self.pbr = _to_float(raw_quote.get("pbr", "")) or None
        self.eps = _to_float(raw_quote.get("eps", "")) or None
        self.bps = _to_float(raw_quote.get("bps", "")) or None

    def to_snapshot(self, symbol: str, info: InstrumentInfo) -> QuoteSnapshot:
        return QuoteSnapshot(
            symbol=symbol,
            market=info.market,
            name=info.name,
            last_price=self.last_price,
            prev_close=self.prev_close,
            change=self.change,
            change_rate=self.change_rate,
            change_sign=self.change_sign,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            upper_limit=self.upper_limit,
            lower_limit=self.lower_limit,
            accumulated_volume=self.accumulated_volume,
            accumulated_value=self.accumulated_value,
            per=self.per,
            pbr=self.pbr,
            eps=self.eps,
            bps=self.bps,
            ask_levels=list(self.ask_levels),
            bid_levels=list(self.bid_levels),
            total_ask_quantity=self.total_ask_quantity,
            total_bid_quantity=self.total_bid_quantity,
            trade_time=self.trade_time,
            hour_class=self.hour_class,
            trading_halted=self.trading_halted,
            data_source="websocket",
            updated_at=self.updated_at,
            recent_trades=list(self.recent_trades),
        )


# ---------------------------------------------------------------------------
# KisRealtimeQuoteSource
# ---------------------------------------------------------------------------


class KisRealtimeQuoteSource:
    """KIS-backed ``RealtimeQuoteSource`` — single app-process, single viewer.

    Construction is synchronous (no I/O). Call ``await connect()`` once
    inside an async context (FastAPI ``lifespan``) before use, and
    ``await aclose()`` on shutdown.
    """

    def __init__(
        self,
        *,
        rest_client: KISRestClient,
        ws_url: str,
        max_registrations: int = DEFAULT_MAX_REGISTRATIONS,
        registrations_per_symbol: int = REGISTRATIONS_PER_SYMBOL,
    ) -> None:
        self._rest_client = rest_client
        self._ws_url = ws_url
        self._max_registrations = max_registrations
        self._registrations_per_symbol = registrations_per_symbol

        self._budget = SubscriptionBudget(max_subscriptions=max_registrations)
        self._ws_client: KISWebSocketClient | None = None
        self._state: dict[str, _SymbolState] = {}
        self._consumer_task: asyncio.Task[None] | None = None
        # Phase 4 push relay hook — see realtime_quote_broadcaster.py. Listeners
        # are invoked synchronously, right after in-memory state is updated,
        # with the freshly-built snapshot for that symbol. Best-effort: a
        # listener exception is logged and never breaks WS message processing.
        self._listeners: list[Callable[[str, QuoteSnapshot], None]] = []
        # 2026-07-09: 마감 후에도 KIS가 동일한 마지막 체결가/호가를 반복 전송하는
        # 것이 실측됐다 — 내용이 실제로 안 바뀐 프레임까지 매번 notify하면 SSE
        # 직렬화/전송, 구독 중인 브라우저 리렌더가 불필요하게 반복된다. 종목별
        # "마지막으로 notify한 내용의 signature"를 들고 있다가, 다음 프레임의
        # signature가 같으면 조용히 상태만 갱신하고 notify는 건너뛴다. 구독
        # 직후 첫 프레임은 비교 대상이 없어(신규 종목) 항상 signature가 달라지므로
        # 무조건 최소 1회는 통과한다 — "장중엔 미구독 → 장 종료 후 구독" 시나리오도
        # 항상 최소 1회 값을 받는다는 보장이 이걸로 성립한다.
        self._last_notified_signature: dict[str, tuple[Any, ...]] = {}

    def add_listener(self, callback: Callable[[str, QuoteSnapshot], None]) -> None:
        """Register a callback invoked on every trade/orderbook update.

        Used by ``QuoteBroadcaster`` to fan out pushes to SSE subscribers
        without polling. Not part of the ``RealtimeQuoteSource`` protocol —
        callers must duck-type check (``hasattr(source, "add_listener")``)
        since ``InMemoryMockQuoteSource`` has no native push events and does
        not implement this.
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, QuoteSnapshot], None]) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify_listeners(self, symbol: str, snapshot: QuoteSnapshot) -> None:
        for callback in self._listeners:
            try:
                callback(symbol, snapshot)
            except Exception:
                logger.exception("Realtime-quote broadcaster listener failed for %s", symbol)

    @staticmethod
    def _content_signature(snapshot: QuoteSnapshot) -> tuple[Any, ...]:
        """Comparable "did anything meaningful change" key for ``snapshot``.

        Deliberately excludes ``updated_at`` (always differs — every frame
        timestamps itself) and ``data_source``/``symbol``/``market``/``name``
        (constant for a given subscription). Includes ``recent_trades`` so a
        genuinely new trade tick still counts as a change even when the price
        happens to repeat (e.g. two consecutive trades at the same price).
        """
        return (
            snapshot.last_price,
            snapshot.change,
            snapshot.change_rate,
            snapshot.change_sign,
            snapshot.open_price,
            snapshot.high_price,
            snapshot.low_price,
            snapshot.accumulated_volume,
            snapshot.accumulated_value,
            snapshot.trade_time,
            snapshot.hour_class,
            snapshot.trading_halted,
            tuple(snapshot.ask_levels),
            tuple(snapshot.bid_levels),
            snapshot.total_ask_quantity,
            snapshot.total_bid_quantity,
            tuple(snapshot.recent_trades),
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Fetch an approval key and open the dedicated KIS WebSocket connection.

        Idempotent — calling this twice while already connected is a no-op.
        On any failure partway through, self-cleans up (via ``aclose()``)
        before re-raising, so the instance is left in a clean state that a
        caller can safely retry ``connect()`` on later.
        """
        if self._ws_client is not None and self._ws_client.is_connected:
            return

        try:
            approval_key = await self._rest_client.get_approval_key()
            self._ws_client = KISWebSocketClient(
                rest_client=self._rest_client,
                approval_key=approval_key,
                env="live",
                subscription_budget=self._budget,
                ws_url=self._ws_url,
            )
            await self._ws_client.connect()
            self._consumer_task = asyncio.create_task(self._consume_loop())
            logger.info("KisRealtimeQuoteSource connected (realtime-quote screen only)")
        except Exception:
            logger.exception("KisRealtimeQuoteSource.connect() failed — cleaning up")
            await self.aclose()
            raise

    async def aclose(self) -> None:
        """Stop the consumer task, disconnect the WS client, close the REST client.

        Safe to call multiple times and safe to call after a partially
        completed (or entirely failed) ``connect()`` — each step is
        independently guarded so no single failure skips the rest.
        """
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            self._consumer_task = None
        if self._ws_client is not None:
            try:
                await self._ws_client.disconnect()
            except Exception:
                logger.exception("KisRealtimeQuoteSource: error disconnecting WS client")
            self._ws_client = None
        try:
            await self._rest_client.close()
        except Exception:
            logger.exception("KisRealtimeQuoteSource: error closing REST client")
        logger.info("KisRealtimeQuoteSource closed")

    async def _consume_loop(self) -> None:
        assert self._ws_client is not None
        async for msg in self._ws_client.messages():
            try:
                self._handle_message(msg)
            except Exception:
                logger.exception(
                    "Failed to process realtime-quote WS message (type=%s)",
                    msg.get("type"),
                )

    def _handle_message(self, msg: dict[str, Any]) -> None:
        # Try our own channels first — the shared parser's type/tr_id
        # classification is unreliable for H0STCNT0/H0STASP0 raw frames (see
        # ``_split_realtime_frame`` docstring), so we re-parse ``raw``
        # directly rather than trusting ``msg.get("type")``/``msg.get("tr_id")``.
        raw = msg.get("raw")
        split = _split_realtime_frame(raw) if isinstance(raw, str) else None
        if split is not None and split[0] in (_TRADE_CHANNEL, _ORDERBOOK_CHANNEL):
            self._apply_realtime_frame(*split)
            return

        msg_type = msg.get("type")
        if msg_type == "error":
            logger.warning(
                "KIS realtime-quote WS rejected/errored: tr_id=%s message=%s",
                msg.get("tr_id"),
                msg.get("message"),
            )
        elif msg_type == "subscription_ack":
            logger.info(
                "KIS realtime-quote WS subscription_ack: tr_id=%s tr_key=%s",
                msg.get("tr_id"),
                msg.get("tr_key"),
            )
        elif msg_type not in (None, "real_time_data"):
            logger.warning(
                "KIS realtime-quote WS unhandled message type=%s tr_id=%s",
                msg_type,
                msg.get("tr_id"),
            )

    def _apply_realtime_frame(self, tr_id: str, fields: list[str]) -> None:
        symbol = _f(fields, 1)
        state = self._state.get(symbol)
        if state is None:
            return  # unsubscribed since this message was sent — ignore

        if tr_id == _TRADE_CHANNEL:
            state.apply_trade(_parse_trade_fields(fields))
        else:
            state.apply_orderbook(_parse_orderbook_fields(fields))

        if self._listeners:
            snapshot = state.to_snapshot(symbol, self.instrument_info(symbol))
            signature = self._content_signature(snapshot)
            if signature != self._last_notified_signature.get(symbol):
                self._last_notified_signature[symbol] = signature
                self._notify_listeners(symbol, snapshot)

    # ------------------------------------------------------------------
    # RealtimeQuoteSource protocol
    # ------------------------------------------------------------------

    @property
    def environment(self) -> str:
        return "live"

    @property
    def max_registrations(self) -> int:
        return self._max_registrations

    @property
    def registrations_per_symbol(self) -> int:
        return self._registrations_per_symbol

    def connection_state(self) -> ConnectionState:
        if self._ws_client is None:
            return ConnectionState.DISCONNECTED
        if self._ws_client.is_connected:
            return ConnectionState.CONNECTED
        if self._ws_client.is_reconnecting:
            return ConnectionState.RECONNECTING
        return ConnectionState.DISCONNECTED

    def registered_count(self) -> int:
        return len(self._state) * self._registrations_per_symbol

    def list_subscriptions(self) -> list[str]:
        return sorted(self._state.keys())

    def instrument_info(self, symbol: str) -> InstrumentInfo:
        return default_instrument_info(symbol)

    async def subscribe(self, symbol: str) -> None:
        normalized = _validate_symbol(symbol)
        if normalized in self._state:
            return  # idempotent — matches InMemoryMockQuoteSource semantics

        prospective = (len(self._state) + 1) * self._registrations_per_symbol
        if prospective > self._max_registrations:
            symbol_capacity = self._max_registrations // self._registrations_per_symbol
            raise SubscriptionLimitExceededError(
                f"Subscribing to {normalized} would exceed the registration budget "
                f"({self._max_registrations} registrations = {symbol_capacity} symbols "
                f"at {self._registrations_per_symbol} registrations/symbol)."
            )
        if self._ws_client is None:
            raise RuntimeError("KisRealtimeQuoteSource.subscribe() called before connect()")

        # Reserve state before awaiting so a concurrent duplicate subscribe()
        # for the same symbol sees it immediately and short-circuits above.
        self._state[normalized] = _SymbolState()

        ok_price = await self._ws_client.subscribe(_TRADE_CHANNEL, normalized, critical=False)
        ok_book = await self._ws_client.subscribe(_ORDERBOOK_CHANNEL, normalized, critical=False)
        if not (ok_price and ok_book):
            # Should not normally happen — our own capacity check above mirrors
            # SubscriptionBudget's sizing exactly since this client is the sole
            # consumer of its budget. Roll back defensively if it ever does.
            if ok_price:
                await self._ws_client.unsubscribe(_TRADE_CHANNEL, normalized, critical=False)
            if ok_book:
                await self._ws_client.unsubscribe(_ORDERBOOK_CHANNEL, normalized, critical=False)
            del self._state[normalized]
            raise SubscriptionLimitExceededError(
                f"KIS WebSocket rejected subscription for {normalized} "
                "(transport-level budget exhausted)."
            )

        # Best-effort one-shot static reference enrichment (상한가/하한가/기준가/
        # PER/PBR/EPS/BPS) — never blocks or fails the subscription itself.
        try:
            raw_quote = await self._rest_client.get_quote(normalized)
            if raw_quote:
                self._state[normalized].apply_static_reference(raw_quote)
        except Exception:
            logger.warning(
                "Realtime-quote static reference fetch failed for %s "
                "(상한가/하한가/기준가/PER/PBR/EPS/BPS will show as defaults)",
                normalized,
                exc_info=True,
            )

    async def unsubscribe(self, symbol: str) -> None:
        normalized = symbol.strip()
        if normalized not in self._state:
            return
        if self._ws_client is not None:
            await self._ws_client.unsubscribe(_TRADE_CHANNEL, normalized, critical=False)
            await self._ws_client.unsubscribe(_ORDERBOOK_CHANNEL, normalized, critical=False)
        del self._state[normalized]
        self._last_notified_signature.pop(normalized, None)

    def get_snapshots(self, symbols: Sequence[str]) -> dict[str, QuoteSnapshot]:
        out: dict[str, QuoteSnapshot] = {}
        for raw_symbol in symbols:
            normalized = raw_symbol.strip()
            state = self._state.get(normalized)
            if state is None or not (state.has_price_data or state.has_orderbook_data):
                continue
            out[normalized] = state.to_snapshot(normalized, self.instrument_info(normalized))
        return out

    async def get_daily_price(
        self, symbol: str, count: int = MAX_DAILY_PRICE_HISTORY
    ) -> list[DailyPriceBar]:
        """일자별 시세(``FHKST01010400``) — WS 구독 상태와 무관한 REST 1회 조회.

        구독 목록에 없는 종목도 조회 가능하다(순수 REST 조회이므로 이 화면의
        WS 구독/등록 budget을 소비하지 않는다).
        """
        normalized = _validate_symbol(symbol)
        raw_rows = await self._rest_client.get_daily_price(normalized)
        bars: list[DailyPriceBar] = []
        for row in raw_rows[: min(count, MAX_DAILY_PRICE_HISTORY)]:
            # KIS 응답의 prdy_vrss/prdy_ctrt는 이미 부호가 포함된 문자열이다
            # (028_주식현재가_일자별.md 응답 예시: "-2500"/"-1.97") — 별도 부호
            # 보정이 필요 없다.
            bars.append(
                DailyPriceBar(
                    date=str(row.get("stck_bsop_date", "")),
                    close=_to_float(row.get("stck_clpr", "")),
                    change=_to_float(row.get("prdy_vrss", "")),
                    change_rate=_to_float(row.get("prdy_ctrt", "")),
                    volume=_to_int(row.get("acml_vol", "")),
                )
            )
        return bars
