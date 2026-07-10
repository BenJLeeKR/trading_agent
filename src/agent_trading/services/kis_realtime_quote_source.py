"""KIS WebSocket-backed ``RealtimeQuoteSource`` (Step 3) — 실시간 현재가 조회 전용.

This is the **only** module that opens a live KIS WebSocket connection for
the "실시간 현재가 조회" Admin UI screen
(``plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md``).

Account isolation (critical invariant — see plan Step 3 §8 안전장치)
---------------------------------------------------------------------
This module is wired via ``runtime.bootstrap.build_realtime_quote_source()``,
which as of 2026-07-10 uses the ``KIS_LIVE_INFO_APP_KEY``/``_APP_SECRET``
credential (authoritative — the same disclosure/live-info account already
used for the 076 holiday lookup and ``_build_kis_live_quote_client()``; legacy
``KIS_REALTIME_QUOTE_APP_KEY``/``_APP_SECRET`` is a short-lived fallback).
This is safe because ``ops-scheduler`` no longer opens any KIS WebSocket
(163 removed 2026-07-10) — this module is now the *only* process holding a
live WebSocket session for that appkey (§4.2 WebSocket Session 1개 원칙). It
still never touches:

- the trading account's ``KISRestClient``/``KoreaInvestmentAdapter``
  (``KIS_APP_KEY`` / ``KIS_API_KEY``)
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
    _KST,
    _validate_symbol,
    default_instrument_info,
)

logger = logging.getLogger(__name__)

_TRADE_CHANNEL = "H0STCNT0"  # 실시간체결가 (KRX)
_ORDERBOOK_CHANNEL = "H0STASP0"  # 실시간호가 (KRX)

# Step 4 — REST fallback (11_kis_realtime_quote_operations_screen.md §4.7).
# WS 연결이 끊긴/재연결 중인 상태가 이만큼 지속되면 구독 중인 종목들의 snapshot을
# REST 현재가 조회로 보정한다. 종목당 최소 이 간격(초)만큼은 띄워서만 재시도한다
# ("과도한 호출 방지" — KISRestClient.get_quote() 자체에도 3분 TTL 캐시가 있지만,
# 이 소스 레벨에서도 명시적으로 최소 간격을 강제한다).
_FALLBACK_TRIGGER_AFTER_SECONDS = 10.0
_FALLBACK_COOLDOWN_SECONDS = 10.0
_HEALTH_CHECK_INTERVAL_SECONDS = 3.0

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
    # KST 캘린더 날짜("YYYYMMDD") — 정적 참조값(기준가/전일종가 등)을 마지막으로
    # REST에서 가져온 날짜. 구독이 자정을 넘겨 계속 유지되면(자동 unsubscribe가
    # 없어 실제로 발생함) 이 값이 오늘 날짜와 달라지고, 그걸 신호로 재조회한다.
    reference_date: str = ""

    # 2026-07-10 (Step 4 — REST fallback): WS tick으로 갱신되면 "websocket",
    # KIS WS 연결이 끊겨 REST 현재가 조회로 보정되면 "rest_fallback". 실제 WS
    # tick이 다시 도착하면(apply_trade/apply_orderbook) 자동으로 "websocket"으로
    # 되돌아간다 — 별도의 "복귀 처리"가 필요 없다.
    data_source: str = "websocket"

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
        self.data_source = "websocket"
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
        self.data_source = "websocket"

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
        self.reference_date = datetime.now(_KST).strftime("%Y%m%d")

    def apply_rest_fallback(self, raw_quote: dict[str, Any]) -> None:
        """Step 4 — KIS WS 연결이 끊기거나 재연결 중일 때 REST 현재가 조회
        (``029_주식현재가_시세.md``, ``FHKST01010100`` — ``KisRealtimeQuoteSource``가
        정적 참조값 보강에도 쓰는 바로 그 endpoint)로 snapshot을 1회성 보정한다.

        REST 응답에서 확보 가능한 "실시간성" 필드만 갱신하고, REST에 없는 필드는
        건드리지 않고 마지막으로 알려진 값을 그대로 유지한다:

        - 갱신: last_price/change/change_rate/change_sign, open/high/low_price,
          accumulated_volume/accumulated_value, trading_halted(``temp_stop_yn``).
        - 유지(REST 응답에 없음): ask_levels/bid_levels/총잔량(호가는 별도 API),
          recent_trades(체결 이력), trade_time(체결 시각), hour_class(시간구분),
          vi_stnd_price. 화면은 이 필드들을 "마지막으로 알려진 값"으로 계속 보여준다.
        - prev_close/upper_limit/lower_limit/PER/PBR/EPS/BPS는 건드리지 않는다 —
          그 필드들의 갱신 책임은 ``apply_static_reference()``/자정 롤오버 로직이
          이미 갖고 있으므로 여기서 중복 처리하지 않는다.

        Best-effort — ``raw_quote``에 값이 없으면 기존 값을 그대로 둔다.
        """
        self.has_price_data = True
        self.last_price = _to_float(raw_quote.get("stck_prpr", "")) or self.last_price
        self.change = _to_float(raw_quote.get("prdy_vrss", ""))
        self.change_rate = _to_float(raw_quote.get("prdy_ctrt", ""))
        self.change_sign = "up" if self.change > 0 else "down" if self.change < 0 else "flat"
        self.open_price = _to_float(raw_quote.get("stck_oprc", "")) or self.open_price
        self.high_price = _to_float(raw_quote.get("stck_hgpr", "")) or self.high_price
        self.low_price = _to_float(raw_quote.get("stck_lwpr", "")) or self.low_price
        self.accumulated_volume = _to_int(raw_quote.get("acml_vol", "")) or self.accumulated_volume
        self.accumulated_value = (
            _to_int(raw_quote.get("acml_tr_pbmn", "")) or self.accumulated_value
        )
        temp_stop_yn = raw_quote.get("temp_stop_yn")
        if temp_stop_yn is not None:
            self.trading_halted = temp_stop_yn == "Y"
        self.data_source = "rest_fallback"
        self.updated_at = datetime.now(timezone.utc)

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
            data_source=self.data_source,
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
        fallback_trigger_after_seconds: float = _FALLBACK_TRIGGER_AFTER_SECONDS,
        fallback_cooldown_seconds: float = _FALLBACK_COOLDOWN_SECONDS,
        health_check_interval_seconds: float = _HEALTH_CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._rest_client = rest_client
        self._ws_url = ws_url
        self._max_registrations = max_registrations
        self._registrations_per_symbol = registrations_per_symbol
        self._fallback_trigger_after_seconds = fallback_trigger_after_seconds
        self._fallback_cooldown_seconds = fallback_cooldown_seconds
        self._health_check_interval_seconds = health_check_interval_seconds

        self._budget = SubscriptionBudget(max_subscriptions=max_registrations)
        self._ws_client: KISWebSocketClient | None = None
        self._state: dict[str, _SymbolState] = {}
        self._consumer_task: asyncio.Task[None] | None = None
        # Step 4 — REST fallback (11_...md §4.7). ``_disconnected_since``는 WS
        # 연결이 CONNECTED가 아니게 된 시각(전체 세션 단위) — 이게 threshold
        # 이상 지속돼야 fallback을 시작한다. ``_last_fallback_at``은 종목별
        # cooldown(과호출 방지)이다.
        self._health_monitor_task: asyncio.Task[None] | None = None
        self._disconnected_since: datetime | None = None
        self._last_fallback_at: dict[str, datetime] = {}
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
        # 2026-07-10: 구독이 자정을 넘겨 계속 유지되는 경우(자동 unsubscribe가
        # 없어 실제로 발생함), subscribe() 시점에 REST로 1회만 가져온 prev_close/
        # 기준가가 날짜가 바뀐 뒤에도 그대로 남아 "호가"의 클라이언트 계산 대비율과
        # "실시간 체결가"의 KIS 서버 계산 change_rate가 서로 다른 기준으로 어긋나는
        # 문제가 실측됐다. 종목별로 정적 참조값 재조회가 이미 진행 중인지 표시해
        # 프레임마다 중복으로 재조회를 스케줄링하지 않도록 한다.
        self._reference_refresh_in_progress: set[str] = set()

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
        timestamps itself) and ``symbol``/``market``/``name`` (constant for a
        given subscription). Includes ``recent_trades`` so a genuinely new
        trade tick still counts as a change even when the price happens to
        repeat (e.g. two consecutive trades at the same price).

        2026-07-10 (Step 4 후속 보정): ``data_source``도 포함한다 — 값 자체는
        그대로인데 ``websocket`` → ``rest_fallback``(또는 그 반대)으로 출처만
        바뀌는 경우, 이 필드가 빠져 있으면 signature가 동일하게 판정돼 listener
        notify(SSE 구독자에게 "지금 REST 보정값을 보고 있다"는 사실 전달 포함)가
        생략됐다. 출처 전환은 숫자 값이 같아도 반드시 구독자에게 전달돼야 한다.
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
            snapshot.data_source,
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
            self._health_monitor_task = asyncio.create_task(self._health_monitor_loop())
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
        if self._health_monitor_task is not None:
            self._health_monitor_task.cancel()
            self._health_monitor_task = None
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

        today = datetime.now(_KST).strftime("%Y%m%d")
        if (
            state.reference_date
            and state.reference_date != today
            and symbol not in self._reference_refresh_in_progress
        ):
            self._reference_refresh_in_progress.add(symbol)
            asyncio.create_task(self._refresh_static_reference(symbol))

        if self._listeners:
            snapshot = state.to_snapshot(symbol, self.instrument_info(symbol))
            signature = self._content_signature(snapshot)
            if signature != self._last_notified_signature.get(symbol):
                self._last_notified_signature[symbol] = signature
                self._notify_listeners(symbol, snapshot)

    async def _refresh_static_reference(self, symbol: str) -> None:
        """자정을 넘겨 유지된 구독의 기준가/전일종가(등)를 재조회한다.

        구독이 그새 해제됐거나(``state`` 소실) REST 호출이 실패해도 이 갱신은
        best-effort다 — 실패해도 다음 프레임에서 ``reference_date``가 여전히
        stale하므로 다시 시도된다(``_reference_refresh_in_progress``에서만
        지금 이 시도를 제거하면 됨).
        """
        try:
            state = self._state.get(symbol)
            if state is None:
                return  # unsubscribed while the refresh was pending
            raw_quote = await self._rest_client.get_quote(symbol)
            state = self._state.get(symbol)  # re-check — may have unsubscribed mid-await
            if state is not None and raw_quote:
                state.apply_static_reference(raw_quote)
        except Exception:
            logger.warning(
                "Realtime-quote static reference refresh failed for %s "
                "(will retry on the next frame)",
                symbol,
                exc_info=True,
            )
        finally:
            self._reference_refresh_in_progress.discard(symbol)

    # ------------------------------------------------------------------
    # Step 4 — REST fallback (11_kis_realtime_quote_operations_screen.md §4.7)
    #
    # "브라우저↔API 간 transport fallback"(SSE 전송 실패 시 REST polling,
    # Phase 4/QuoteBroadcaster의 관심사)과는 다른 계층이다 — 여기서 다루는 건
    # "API↔KIS 간 quote source fallback": KIS WS 연결 자체가 끊기거나 재연결
    # 중일 때, 구독 중인 종목의 snapshot을 REST 현재가 조회로 보정한다.
    # ------------------------------------------------------------------

    async def _health_monitor_loop(self) -> None:
        """WS 연결 상태를 주기적으로 확인해 REST fallback을 트리거한다.

        연결이 끊긴/재연결 중인 상태가 ``_fallback_trigger_after_seconds`` 이상
        지속되면, 그 시점부터는 매 체크마다 구독 중인 모든 종목에 대해
        REST fallback을 시도한다(단, 종목별 cooldown은 ``_maybe_apply_rest_fallback``
        내부에서 강제). 연결이 회복되면(``CONNECTED``) 즉시 감시 상태를 리셋한다 —
        실제 WS tick이 다시 오면 ``apply_trade``/``apply_orderbook``이 자동으로
        ``data_source``를 "websocket"으로 되돌리므로 별도 복귀 처리는 필요 없다.
        """
        try:
            while True:
                await asyncio.sleep(self._health_check_interval_seconds)
                if self.connection_state() == ConnectionState.CONNECTED:
                    self._disconnected_since = None
                    continue
                now = datetime.now(timezone.utc)
                if self._disconnected_since is None:
                    self._disconnected_since = now
                    continue
                elapsed = (now - self._disconnected_since).total_seconds()
                if elapsed < self._fallback_trigger_after_seconds:
                    continue
                for symbol in list(self._state.keys()):
                    await self._maybe_apply_rest_fallback(symbol)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Realtime-quote health monitor loop failed")

    async def _maybe_apply_rest_fallback(self, symbol: str) -> None:
        """종목별 cooldown을 지킨 채 REST fallback을 1회 시도한다.

        REST 호출은 ``bypass_cache=True``로 호출한다 — ``subscribe()``의 정적
        참조값 보강(§4.1)과 자정 롤오버 재조회(``_refresh_static_reference``)가
        같은 ``get_quote()``의 3분 TTL 캐시를 공유하므로, 캐시를 그대로 쓰면 WS가
        구독 직후(또는 자정 롤오버 재조회 직후) 3분 이내에 끊겼을 때 "장애 시점의
        실제 최신 현재가"가 아니라 "그 이전 호출의 캐시값"을 재사용하게 된다. Step 4
        fallback은 항상 최신값을 조회해야 하므로 이 경로만 캐시를 우회한다.

        REST 호출 실패는 best-effort로 로깅만 하고 넘어간다 — cooldown 시각은
        **성공했을 때만** 갱신한다. 실패 시에도 cooldown을 걸어버리면 그 다음
        health check 주기에서도 재시도가 막혀 "다음 체크에서 재시도"라는 의도가
        깨진다.
        """
        now = datetime.now(timezone.utc)
        last = self._last_fallback_at.get(symbol)
        if last is not None and (now - last).total_seconds() < self._fallback_cooldown_seconds:
            return

        try:
            raw_quote = await self._rest_client.get_quote(symbol, bypass_cache=True)
        except Exception:
            logger.warning(
                "Realtime-quote REST fallback fetch failed for %s "
                "(cooldown not applied — will retry on the next health check)",
                symbol,
                exc_info=True,
            )
            return

        # 성공한 시점에만 cooldown을 시작한다 — 실패한 시도가 다음 재시도를
        # 막지 않도록, cooldown 시각 기록을 fetch 성공 이후로 미뤘다.
        self._last_fallback_at[symbol] = datetime.now(timezone.utc)

        state = self._state.get(symbol)  # re-check — may have unsubscribed mid-await
        if state is None or not raw_quote:
            return
        state.apply_rest_fallback(raw_quote)

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
        self._reference_refresh_in_progress.discard(normalized)
        self._last_fallback_at.pop(normalized, None)

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
