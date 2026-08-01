"""Realtime quote source interface + Phase 1 in-memory mock implementation.

This module defines the ``RealtimeQuoteSource`` protocol that the
"실시간 현재가 조회" Admin UI screen depends on
(see ``plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md``
and ``plans/[DESIGN]_kis_realtime_quote_operations_screen_plan.md``).

Phase 1 (this module) ships only ``InMemoryMockQuoteSource`` — no KIS
WebSocket connection is made. Phase 2 will add a KIS-backed implementation
of the same protocol (e.g. ``KisRealtimeQuoteSource``) and swap it in via
``app.state.realtime_quote_source`` without changing the API routes or
Admin UI contract.

Important constraint carried over from the design docs: KIS's official
WebSocket registration limit is 41 per account, counted per *registration*,
not per symbol. Subscribing to both 체결가(price) and 호가(orderbook) for one
symbol consumes 2 registrations. This screen self-limits below that official
ceiling — ``DEFAULT_MAX_REGISTRATIONS = 30`` (2026-07-09, operational safety
margin) — so the realistic symbol capacity is
``max_registrations // registrations_per_symbol`` (30 // 2 = 15), not 41/20.

Subscription model (Phase 1, single-screen semantics)
------------------------------------------------------
``subscribe()``/``unsubscribe()`` are a plain **idempotent set membership**
toggle, not a reference count: subscribing to an already-subscribed symbol is
a no-op, and a single ``unsubscribe()`` call fully removes it. This matches
what the Admin UI actually shows (each symbol appears as exactly one chip,
never a counter), so "구독 해제" always means "gone" from a single operator's
point of view.

This is *not* the same model this screen will eventually need once multiple
browser sessions can each independently view overlapping symbol sets (Step 3+,
after real KIS WebSocket fan-out is introduced) — at that point a per-viewer
reference count (or an explicit multi-consumer session registry) will be
required so one viewer closing a symbol doesn't drop it out from under another
viewer still watching it. That redesign is deliberately deferred; Phase 1 has
exactly one implicit "viewer" (the mock source itself), so idempotent
set semantics are simpler and correct for now.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Awaitable, Callable, Protocol, Sequence

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

# "체결가" 프레임(시별/일별 탭)의 표시/보관 상한 — 화면에 20행을 보여주는 게 목표이므로
# 그보다 조금 넉넉한 30개까지만 메모리에 들고 있는다(2026-07-09 결정).
MAX_TRADE_HISTORY = 30
MAX_DAILY_PRICE_HISTORY = 30

# KIS 공식 상한은 41(2026-04-20 공지 기준, plan_docs/detailed_design/
# 10_broker_rate_limit_and_capacity_policy.md §12)이지만, 이 화면은 운영 안정성
# 마진 확보를 위해 자체적으로 30으로 낮춰 운영한다(2026-07-09 결정,
# plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md §4.3).
DEFAULT_MAX_REGISTRATIONS = 30
REGISTRATIONS_PER_SYMBOL = 2  # 체결가 + 호가

_SYMBOL_RE_LEN = 6


class ConnectionState(str, Enum):
    """Connection status of the underlying quote source."""

    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"


class InvalidSymbolError(ValueError):
    """Raised when a symbol code fails basic format validation."""


class SubscriptionLimitExceededError(RuntimeError):
    """Raised when adding a symbol would exceed the registration budget."""


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    """Minimal instrument identity — name + market label."""

    symbol: str
    name: str
    market: str  # "KOSPI" | "KOSDAQ" | "UNKNOWN"


@dataclass(frozen=True, slots=True)
class QuoteLevel:
    """One price/quantity rung of the orderbook ladder."""

    price: float
    quantity: int


@dataclass(frozen=True, slots=True)
class TradeTick:
    """One 체결(trade) tick — 실시간 체결가 프레임의 '시별' 탭 한 행.

    ``H0STCNT0``의 ``CNTG_VOL``(체결 거래량, 1-indexed field 13)이 per-tick
    거래량이다 — ``ACML_VOL``(누적 거래량)과는 다르다.
    """

    trade_time: str  # "HH:MM:SS" (KST)
    price: float
    change: float  # 전일대비
    change_rate: float  # 전일대비율(%)
    volume: int  # 해당 tick의 체결량(CNTG_VOL) — 누적거래량이 아님


@dataclass(frozen=True, slots=True)
class DailyPriceBar:
    """하루치 시세 — 실시간 체결가 프레임의 '일별' 탭 한 행 (KIS ``FHKST01010400``)."""

    date: str  # "YYYYMMDD"
    close: float
    change: float  # 전일대비
    change_rate: float  # 전일대비율(%)
    volume: int  # 당일 누적 거래량(ACML_VOL)


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    """A single point-in-time quote for one symbol.

    Field naming intentionally mirrors the KIS TR field semantics documented
    in ``[DESIGN]_kis_realtime_quote_screen_ui_layout.md`` §6 (체결가
    ``H0STCNT0`` / 호가 ``H0STASP0`` / 정적 참조값 ``FHKST01010100``) so that a
    Phase 2 KIS-backed source can populate this same shape from real data.
    """

    symbol: str
    market: str
    name: str
    last_price: float
    prev_close: float  # 기준가
    change: float
    change_rate: float
    change_sign: str  # "up" | "down" | "flat"
    open_price: float
    high_price: float
    low_price: float
    upper_limit: float
    lower_limit: float
    accumulated_volume: int
    accumulated_value: int
    per: float | None
    pbr: float | None
    eps: float | None
    bps: float | None
    ask_levels: list[QuoteLevel]
    bid_levels: list[QuoteLevel]
    total_ask_quantity: int
    total_bid_quantity: int
    trade_time: str  # "HH:MM:SS" (KST)
    hour_class: str  # 장중 / 장전예상 / 장후예상 / VI발동 / 시간외단일가
    trading_halted: bool
    data_source: str  # "mock" | "websocket" | "rest_fallback"
    updated_at: datetime
    recent_trades: list[TradeTick] = field(default_factory=list)
    """최근 체결 tick 히스토리, 최신 순 — '시별' 탭 표시용 (최대 ``MAX_TRADE_HISTORY``개)."""


class RealtimeQuoteSource(Protocol):
    """Interface a Phase 2 KIS-backed implementation must satisfy.

    Routes in ``api/routes/realtime_quotes.py`` depend only on this
    protocol — swapping ``InMemoryMockQuoteSource`` for a real
    ``KISWebSocketClient``-backed implementation requires no route/schema
    changes.
    """

    @property
    def environment(self) -> str:
        """Data source environment label (``"mock"`` in Phase 1, ``"live"`` later)."""
        ...

    @property
    def max_registrations(self) -> int:
        """This screen's registration budget (30 — below KIS's official 41 ceiling)."""
        ...

    @property
    def registrations_per_symbol(self) -> int:
        """Registrations consumed per symbol (2 — 체결가 + 호가)."""
        ...

    def connection_state(self) -> ConnectionState:
        """Current connection status."""
        ...

    def registered_count(self) -> int:
        """Total registrations currently consumed (symbols * registrations_per_symbol)."""
        ...

    def list_subscriptions(self) -> list[str]:
        """Currently subscribed symbols, sorted."""
        ...

    def instrument_info(self, symbol: str) -> InstrumentInfo:
        """Best-effort name/market lookup — never raises for a well-formed symbol."""
        ...

    async def subscribe(self, symbol: str) -> None:
        """Idempotently add ``symbol`` to the subscription set.

        Subscribing to an already-subscribed symbol is a no-op (Phase 1
        single-screen semantics — see module docstring). It does **not**
        increment a reference count.

        Raises
        ------
        InvalidSymbolError
            If ``symbol`` fails 국내주식 6-digit format validation.
        SubscriptionLimitExceededError
            If adding a *new* symbol would exceed ``max_registrations``.
        """
        ...

    async def unsubscribe(self, symbol: str) -> None:
        """Remove ``symbol`` from the subscription set entirely.

        A single call fully unsubscribes ``symbol`` — there is no reference
        count to decrement (Phase 1 single-screen semantics).
        """
        ...

    def get_snapshots(self, symbols: Sequence[str]) -> dict[str, QuoteSnapshot]:
        """Return the latest snapshot for each *subscribed* symbol in ``symbols``.

        Symbols that are not currently subscribed are silently omitted from
        the result (not an error) — mirrors the REST fallback / cache-miss
        behaviour expected of the real implementation.
        """
        ...

    async def get_daily_price(self, symbol: str, count: int = MAX_DAILY_PRICE_HISTORY) -> list[DailyPriceBar]:
        """일자별 시세(KIS ``FHKST01010400``) — '일별' 탭 표시용, 최신순.

        구독 여부와 무관하게 REST 1회 조회로 동작한다(WS 구독 상태에 의존하지
        않음). ``count``는 ``MAX_DAILY_PRICE_HISTORY``(30, KIS 자체 상한과 동일)
        를 넘지 않는다.
        """
        ...


# ---------------------------------------------------------------------------
# Phase 1 — In-memory mock implementation
# ---------------------------------------------------------------------------

_MOCK_INSTRUMENTS: dict[str, InstrumentInfo] = {
    "005930": InstrumentInfo("005930", "삼성전자", "KOSPI"),
    "000660": InstrumentInfo("000660", "SK하이닉스", "KOSPI"),
    "035420": InstrumentInfo("035420", "NAVER", "KOSPI"),
    "138040": InstrumentInfo("138040", "메리츠금융지주", "KOSPI"),
    "091990": InstrumentInfo("091990", "셀트리온헬스케어", "KOSDAQ"),
}


def default_instrument_info(symbol: str) -> InstrumentInfo:
    """Demo/placeholder name+market lookup — last-resort fallback only.

    Only a handful of demo symbols are seeded; any other symbol falls back to
    a generic placeholder name and ``market="UNKNOWN"``. Real screens should
    go through ``InstrumentInfoResolver`` (below), which prefers the actual
    ``instruments`` DB table and only reaches this function when the table has
    no row for the symbol (or no lookup was configured at all, e.g. tests).
    """
    normalized = symbol.strip()
    known = _MOCK_INSTRUMENTS.get(normalized)
    if known is not None:
        return known
    return InstrumentInfo(normalized, f"종목{normalized}", "UNKNOWN")


# ``instruments`` 테이블 조회 콜백 — ``services/realtime_quote_source.py``는
# repository 계층을 직접 import하지 않는다(순환 의존/결합 방지). 실제 배선은
# ``api/app.py``/``runtime/bootstrap.py``에서 ``InstrumentRepository``를 감싸는
# 콜백을 만들어 주입한다 — symbol -> InstrumentInfo | None (DB에 없으면 None).
InstrumentInfoLookup = Callable[[str], Awaitable["InstrumentInfo | None"]]


class InstrumentInfoResolver:
    """symbol -> ``InstrumentInfo`` 조회 + 캐시 (mock/KIS 소스 공용).

    실시간 시세 화면은 같은 구독 종목에 대해 초 단위로 반복 조회되므로, 매
    ``instrument_info()`` 호출마다 DB를 두드리면 N+1이 된다. 대신 ``subscribe()``
    시점(종목당 정확히 1회, 이미 async인 경로)에만 ``instruments`` 테이블을 조회해
    결과를 캐싱하고, ``instrument_info()``는 캐시만 읽는 동기 조회로 유지한다
    (``RealtimeQuoteSource.instrument_info`` 프로토콜 자체가 동기 메서드라서, 매
    호출 시점에 직접 await 하는 선택지가 없다).

    조회 실패(DB에 없는 심볼, lookup 콜백 미설정, 조회 중 예외)는 모두
    ``default_instrument_info()``의 placeholder로 폴백하고, 그 폴백 결과도 그대로
    캐싱한다 — 같은 미등록 심볼을 구독할 때마다 매번 DB를 다시 두드리지 않기
    위함이다.
    """

    __slots__ = ("_lookup", "_cache")

    def __init__(self, lookup: InstrumentInfoLookup | None) -> None:
        self._lookup = lookup
        self._cache: dict[str, InstrumentInfo] = {}

    async def warm(self, symbol: str) -> None:
        """``symbol``의 name/market을 조회해 캐시에 채워 넣는다(이미 있으면 no-op).

        ``subscribe()``에서 호출한다 — 구독 시점에 딱 1번만 DB를 조회한다.
        """
        if symbol in self._cache:
            return
        info: InstrumentInfo | None = None
        if self._lookup is not None:
            try:
                info = await self._lookup(symbol)
            except Exception:
                logger.exception(
                    "instruments table lookup failed for symbol=%s — falling back "
                    "to placeholder name/market",
                    symbol,
                )
        self._cache[symbol] = info if info is not None else default_instrument_info(symbol)

    def get(self, symbol: str) -> InstrumentInfo:
        """캐시에서 조회 — 아직 ``warm()``되지 않은 심볼은 placeholder를 반환한다."""
        cached = self._cache.get(symbol)
        if cached is not None:
            return cached
        return default_instrument_info(symbol)

    def evict(self, symbol: str) -> None:
        """``unsubscribe()`` 시점에 캐시를 지운다.

        ``warm()``은 캐시에 값이 있으면 무조건 스킵하므로, 이걸 호출하지 않으면
        최초 구독 시점에 ``instruments`` 테이블에 없어 placeholder로 캐싱된
        심볼은(또는 반대로 DB 값이 나중에 바뀐 경우도) 프로세스가 살아있는 한
        재구독해도 영원히 갱신되지 않는다 — 다음 ``subscribe()``가 다시
        DB를 조회하도록 캐시 항목을 제거한다.
        """
        self._cache.pop(symbol, None)

    def set_lookup(self, lookup: InstrumentInfoLookup | None) -> None:
        """조회 콜백을 나중에 주입/교체한다.

        생성 시점에는 아직 repos/DB pool이 준비되지 않은 배선(예: ``api/app.py``
        lifespan에서 quote source를 먼저 만들고, repos는 그 뒤에 준비되는 순서)을
        지원하기 위함이다. 이미 캐싱된 항목은 그대로 유지된다 — 교체 시점 이전에
        조회된 게 없으므로 실질적으로는 항상 빈 캐시에서 시작한다.
        """
        self._lookup = lookup


def _validate_symbol(symbol: str) -> str:
    """Normalize + validate a 국내주식 symbol code.

    Only exactly 6 digits are accepted (e.g. ``"005930"``). This screen is
    KIS 국내주식 실시간 현재가 조회 only — no ETN (``Q`` prefix), no
    alphabetic/mixed codes, no other market's symbol formats.

    Raises ``InvalidSymbolError`` on failure.
    """
    normalized = symbol.strip()
    if len(normalized) != _SYMBOL_RE_LEN or not normalized.isdigit():
        raise InvalidSymbolError(
            f"Invalid symbol code: {symbol!r} (expected exactly 6 digits, "
            "국내주식 종목코드 only)"
        )
    return normalized


def _base_price(symbol: str) -> float:
    """Deterministic pseudo-base-price for a symbol (stable across calls)."""
    if symbol in _MOCK_INSTRUMENTS:
        # Recognizable base prices for the seeded demo instruments.
        seeded = {
            "005930": 71_900.0,
            "000660": 182_500.0,
            "035420": 215_000.0,
            "138040": 102_200.0,
            "091990": 68_500.0,
        }
        return seeded[symbol]
    # Unknown symbol: derive a stable-looking price from the symbol digits.
    digits = sum(ord(c) for c in symbol)
    return float(10_000 + (digits * 137) % 190_000)


class InMemoryMockQuoteSource:
    """Phase 1 mock ``RealtimeQuoteSource`` — no network calls, no KIS credentials.

    Generates deterministic, smoothly-oscillating quotes per symbol so the
    Admin UI has something meaningful to poll while Phase 2's real KIS
    WebSocket integration is built.

    Subscriptions are a plain idempotent set (see module docstring
    "Subscription model") — not a reference count. This matches the Admin
    UI's single-chip-per-symbol display and means one ``unsubscribe()`` call
    always fully removes a symbol. A per-viewer reference count / multi-consumer
    session registry is deferred to the Step 3+ KIS WebSocket fan-out redesign.
    """

    def __init__(
        self,
        *,
        max_registrations: int = DEFAULT_MAX_REGISTRATIONS,
        registrations_per_symbol: int = REGISTRATIONS_PER_SYMBOL,
        instrument_info_lookup: InstrumentInfoLookup | None = None,
    ) -> None:
        self._max_registrations = max_registrations
        self._registrations_per_symbol = registrations_per_symbol
        self._subscriptions: set[str] = set()
        self._tick = 0
        self._instrument_resolver = InstrumentInfoResolver(instrument_info_lookup)

    @property
    def environment(self) -> str:
        return "mock"

    @property
    def max_registrations(self) -> int:
        return self._max_registrations

    @property
    def registrations_per_symbol(self) -> int:
        return self._registrations_per_symbol

    def connection_state(self) -> ConnectionState:
        # Phase 1 mock source has no real connection to lose — always "up".
        return ConnectionState.CONNECTED

    def registered_count(self) -> int:
        return len(self._subscriptions) * self._registrations_per_symbol

    def list_subscriptions(self) -> list[str]:
        return sorted(self._subscriptions)

    def instrument_info(self, symbol: str) -> InstrumentInfo:
        return self._instrument_resolver.get(symbol)

    def set_instrument_info_lookup(self, lookup: InstrumentInfoLookup | None) -> None:
        """``instruments`` 테이블 조회 콜백을 배선한다(``api/app.py`` lifespan 전용)."""
        self._instrument_resolver.set_lookup(lookup)

    async def subscribe(self, symbol: str) -> None:
        normalized = _validate_symbol(symbol)
        if normalized in self._subscriptions:
            return  # idempotent — already subscribed, no-op

        prospective_count = (len(self._subscriptions) + 1) * self._registrations_per_symbol
        if prospective_count > self._max_registrations:
            symbol_capacity = self._max_registrations // self._registrations_per_symbol
            raise SubscriptionLimitExceededError(
                f"Subscribing to {normalized} would exceed the registration budget "
                f"({self._max_registrations} registrations = {symbol_capacity} symbols "
                f"at {self._registrations_per_symbol} registrations/symbol)."
            )
        await self._instrument_resolver.warm(normalized)
        self._subscriptions.add(normalized)

    async def unsubscribe(self, symbol: str) -> None:
        normalized = symbol.strip()
        self._subscriptions.discard(normalized)
        self._instrument_resolver.evict(normalized)

    def get_snapshots(self, symbols: Sequence[str]) -> dict[str, QuoteSnapshot]:
        self._tick += 1
        out: dict[str, QuoteSnapshot] = {}
        for raw_symbol in symbols:
            normalized = raw_symbol.strip()
            if normalized not in self._subscriptions:
                continue
            out[normalized] = self._generate_snapshot(normalized, self._tick)
        return out

    # ------------------------------------------------------------------
    # Internal — mock quote generation
    # ------------------------------------------------------------------

    def _generate_snapshot(self, symbol: str, tick: int) -> QuoteSnapshot:
        info = self.instrument_info(symbol)
        base = _base_price(symbol)
        seed_offset = (sum(ord(c) for c in symbol) % 100) / 10.0

        # Smooth deterministic oscillation — no randomness, no external state.
        wave = math.sin(tick * 0.3 + seed_offset)
        last_price = round(base * (1 + 0.01 * wave), -1) or base

        change = round(last_price - base, 1)
        change_rate = round((change / base) * 100, 2) if base else 0.0
        change_sign = "up" if change > 0 else "down" if change < 0 else "flat"

        tick_unit = max(10.0, round(last_price * 0.001, -1))

        ask_levels = [
            QuoteLevel(price=last_price + tick_unit * (i + 1), quantity=100 * (i + 1))
            for i in range(10)
        ]
        bid_levels = [
            QuoteLevel(price=last_price - tick_unit * (i + 1), quantity=90 * (i + 1))
            for i in range(10)
        ]

        return QuoteSnapshot(
            symbol=symbol,
            market=info.market,
            name=info.name,
            last_price=last_price,
            prev_close=base,
            change=change,
            change_rate=change_rate,
            change_sign=change_sign,
            open_price=round(base * 1.002, -1) or base,
            high_price=round(base * 1.02, -1) or base,
            low_price=round(base * 0.98, -1) or base,
            upper_limit=round(base * 1.3, -2) or base,
            lower_limit=round(base * 0.7, -2) or base,
            accumulated_volume=100_000 + tick * 1_234,
            accumulated_value=int((100_000 + tick * 1_234) * last_price),
            per=round(8.0 + seed_offset, 2),
            pbr=round(0.8 + seed_offset / 20, 2),
            eps=round(base * 0.12, 1),
            bps=round(base * 1.1, 1),
            ask_levels=ask_levels,
            bid_levels=bid_levels,
            total_ask_quantity=sum(level.quantity for level in ask_levels),
            total_bid_quantity=sum(level.quantity for level in bid_levels),
            trade_time=datetime.now(_KST).strftime("%H:%M:%S"),
            hour_class="장중",
            trading_halted=False,
            data_source="mock",
            updated_at=datetime.now(timezone.utc),
            recent_trades=self._generate_recent_trades(base, last_price, tick),
        )

    def _generate_recent_trades(self, base: float, last_price: float, tick: int) -> list[TradeTick]:
        """최근 tick일수록 ``last_price``에 가깝게, 과거로 갈수록 이전 오실레이션
        값으로 되돌아가는 결정론적 mock 히스토리(최신순, 최대 ``MAX_TRADE_HISTORY``개).
        """
        now = datetime.now(_KST)
        trades: list[TradeTick] = []
        for i in range(MAX_TRADE_HISTORY):
            past_tick = tick - i
            if past_tick < 1:
                break
            wave = math.sin(past_tick * 0.3)
            price = round(base * (1 + 0.01 * wave), -1) or base
            change = round(price - base, 1)
            change_rate = round((change / base) * 100, 2) if base else 0.0
            trades.append(
                TradeTick(
                    trade_time=(now - timedelta(seconds=i)).strftime("%H:%M:%S"),
                    price=price,
                    change=change,
                    change_rate=change_rate,
                    volume=10 + (past_tick % 20),
                )
            )
        return trades

    async def get_daily_price(
        self, symbol: str, count: int = MAX_DAILY_PRICE_HISTORY
    ) -> list[DailyPriceBar]:
        symbol = _validate_symbol(symbol)
        base = _base_price(symbol)
        capped = min(count, MAX_DAILY_PRICE_HISTORY)
        today = datetime.now(_KST)
        bars: list[DailyPriceBar] = []
        prev_close = base
        for i in range(capped):
            wave = math.sin(i * 0.5)
            close = round(base * (1 + 0.015 * wave), -1) or base
            change = round(close - prev_close, 1)
            change_rate = round((change / prev_close) * 100, 2) if prev_close else 0.0
            bars.append(
                DailyPriceBar(
                    date=(today - timedelta(days=i)).strftime("%Y%m%d"),
                    close=close,
                    change=change,
                    change_rate=change_rate,
                    volume=100_000 + (i * 777) % 50_000,
                )
            )
            prev_close = close
        return bars
