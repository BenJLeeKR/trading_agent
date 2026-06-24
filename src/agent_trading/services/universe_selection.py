"""Universe Selection Service — P1 + P2 minimum implementation.

Separates ``Instrument Master`` → ``Trading Universe`` into a dedicated
service layer.  Composes 4 input sources, applies a deterministic
Liquidity Filter, and records ``source_type`` / ``inclusion_reason``
for every selected symbol.

P2 minimum adds:
- Market-Driven Overlay via KIS ``inquire-price`` batch
- Pre-pool candidate selection (budget-safe, max 50 calls/cycle)
- 3-axis composite score (turnover, change rate, near-high proximity)
- F4 (iscd_stat_cls_code — guarded/soft) and F5 (low volume) filters

Reference
---------
- ``plans/[POLICY] trading_universe_policy_v1.md`` — 5-layer universe selection policy
- ``plans/[DESIGN] universe_selection_service.md`` — P1 design document
- ``plans/[DESIGN] universe_selection_service.md`` — P2 design
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Sequence

from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.core_universe_seed import (
    APPROVED_CORE_UNIVERSE_SYMBOLS,
    APPROVED_DISCOVERY_UNIVERSE_SYMBOLS,
)
from agent_trading.services.instrument_profile import (
    derive_primary_index_membership,
    normalize_index_memberships,
)
from agent_trading.services.universe_selection_types import (
    INCLUSION_REASON_CORE,
    INCLUSION_REASON_EVENT,
    INCLUSION_REASON_HELD,
    INCLUSION_REASON_MANUAL,
    INCLUSION_REASON_RECONCILIATION,
    INCLUSION_REASON_NEAR_HIGH,
    INCLUSION_REASON_PRICE_VOLUME_BREAKOUT,
    INCLUSION_REASON_TRADE_STRENGTH,
    INCLUSION_REASON_VOLUME_SURGE,
    CompositionContext,
    LiquidityFilterResult,
    MarketDataSnapshot,
    MarketOverlayDiagnostics,
    SelectedSymbol,
    SourceType,
)

if TYPE_CHECKING:
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient

logger = logging.getLogger(__name__)

_STANDARD_KRX_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_SUPPORTED_KR_EQUITY_MARKETS: frozenset[str] = frozenset({
    "KRX",
    "KOSPI",
    "KOSDAQ",
})
_ACTIVE_ORDER_STATUSES: tuple[OrderStatus, ...] = (
    OrderStatus.DRAFT,
    OrderStatus.VALIDATED,
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.CANCEL_PENDING,
    OrderStatus.RECONCILE_REQUIRED,
)

# ── Liquidity Filter thresholds ─────────────────────────────────────────────

_TICK_SIZE_MICRO_CAP_THRESHOLD = Decimal("1000")
"""Tick sizes >= this value are considered micro-cap / illiquid."""

# F5: 누적 거래대금 threshold (P2 minimum)
_ACC_VOLUME_THRESHOLD: Decimal = Decimal("1_000_000_000")
"""당일 누적 거래대금 < 10억원 → 제외 (P2 assumed, tuning needed)."""

# F4: iscd_stat_cls_code — verification required (KIS Excel 확인 전 assumed)
# ⚠️ These code values are assumed.  Actual mapping must be verified against
#    the KIS Excel Layout sheet before production use.
_SUSPENDED_STATUS_CODES: frozenset[str] = frozenset({
    "01",  # assumed: 관리종목
    "02",  # assumed: 투자위험
    "03",  # assumed: 투자경고
    "04",  # assumed: 투자주의
    "05",  # assumed: 거래정지
})

_EVENT_SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

_EVENT_TYPE_ALIASES: dict[str, str] = {
    "disclosure": "disclosure_material",
    "y|disclosure": "disclosure_material",
    "k|disclosure": "disclosure_material",
    "n|disclosure": "disclosure_material",
    "seeded_news": "news_breaking",
    "y|seeded_news": "news_breaking",
    "n|seeded_news": "news_breaking",
}

_EVENT_OVERLAY_POLICY: dict[str, str] = {
    "earnings": "high",
    "disclosure_material": "high",
    "disclosure_correction": "high",
    "trading_halt": "medium",
    "investment_warning": "medium",
    "management_issue": "medium",
    "capital_change": "high",
    "governance": "high",
    "macro_release": "high",
    "sector_policy": "high",
    "broker_report_change": "high",
    "news_breaking": "high",
}

_EVENT_FETCH_TYPES: tuple[str, ...] = (
    "disclosure",
    "Y|disclosure",
    "K|disclosure",
    "N|disclosure",
    "seeded_news",
    "Y|seeded_news",
    "N|seeded_news",
    "earnings",
    "disclosure_material",
    "disclosure_correction",
    "trading_halt",
    "investment_warning",
    "management_issue",
    "capital_change",
    "governance",
    "macro_release",
    "sector_policy",
    "broker_report_change",
    "news_breaking",
)

_DISCOVERY_SEGMENT_CODES: frozenset[str] = frozenset({
    "KOSPI100",
    "KOSPI_100",
    "KOSPI200",
    "KOSPI_200",
    "KOSDAQ50",
    "KOSDAQ_50",
    "KOSDAQ150",
    "KOSDAQ_150",
    "KOSPI_LARGE",
    "KOSDAQ_GROWTH",
})

_CORE_INDEX_MEMBERSHIP_CODES: frozenset[str] = frozenset({
    "KOSPI100",
    "KOSPI_100",
    "KOSPI200",
    "KOSPI_200",
    "KOSPI_LARGE",
})

_DISCOVERY_INDEX_MEMBERSHIP_CODES: frozenset[str] = frozenset({
    "KOSDAQ50",
    "KOSDAQ_50",
    "KOSDAQ150",
    "KOSDAQ_150",
    "KOSDAQ_GROWTH",
})


# ── Pure functions: score calculation ────────────────────────────────────────


def _calc_market_score(snapshot: MarketDataSnapshot) -> float:
    """P2 Minimum composite score (0.0 ~ 1.0).

    P2는 absolute 기준만 사용. historical baseline 비교 없음.
    """
    scores: list[float] = []

    # Score 1: Turnover ranking proxy (0.0 ~ 1.0)
    # acml_tr_pbmn 절대값이 클수록 high score
    # P2: cross-sectional ranking이므로 normalize by max in batch
    if snapshot.acc_trade_amount is not None:
        # Normalize: 0 ~ 1e12 (1조) 구간을 0.0 ~ 1.0으로
        # 1조 이상이면 1.0으로 cap
        raw = float(snapshot.acc_trade_amount)
        normalized = min(raw / 1_000_000_000_000, 1.0)
        scores.append(normalized)

    # Score 2: 등락률 ranking proxy (0.0 ~ 1.0)
    # prdy_ctrt가 클수록 high score (상승 중)
    if snapshot.change_rate is not None:
        # 등락률 -5% ~ +10% 구간을 0.0 ~ 1.0으로 normalize
        cr = float(snapshot.change_rate)
        normalized = (cr + 5.0) / 15.0
        scores.append(max(0.0, min(normalized, 1.0)))

    # Score 3: 당일 고가 근접 (0.0 ~ 1.0)
    # P2: stck_hgpr 기준 (52주 최고가 아님)
    if snapshot.current_price is not None and snapshot.high_price is not None and snapshot.high_price > 0:
        near_high = float(snapshot.current_price) / float(snapshot.high_price)
        # 80% 미만은 0점, 80%~100% 구간 0.0~1.0
        near_high_score = max(0.0, (near_high - 0.8) / 0.2)
        scores.append(min(near_high_score, 1.0))

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _categorize_market_reason(snapshot: MarketDataSnapshot, score: float) -> str:
    """P2: score 구성 요소 기반 inclusion_reason 결정.

    우선순위: volume_top > strength_top > high_near
    """
    _ = score  # score is reserved for future composite-threshold logic

    # 하나의 symbol에 여러 reason이 중복될 수 있지만,
    # inclusion_reason은 단일 값만 기록 (대표 reason)
    if snapshot.acc_trade_amount is not None:
        raw = float(snapshot.acc_trade_amount)
        if raw > 500_000_000_000:  # 5000억 이상 → volume surge
            return INCLUSION_REASON_VOLUME_SURGE

    if snapshot.change_rate is not None and float(snapshot.change_rate) > 3.0:
        return INCLUSION_REASON_TRADE_STRENGTH

    if (
        snapshot.current_price is not None
        and snapshot.high_price is not None
        and snapshot.high_price > 0
    ):
        high_ratio = float(snapshot.current_price) / float(snapshot.high_price)
        if high_ratio > 0.95:
            return INCLUSION_REASON_NEAR_HIGH

    return INCLUSION_REASON_PRICE_VOLUME_BREAKOUT


# ── Pure functions: KIS response parsing ────────────────────────────────────


def _parse_quote_to_snapshot(
    symbol: str,
    market: str,
    raw: dict[str, object],
) -> MarketDataSnapshot:
    """Parse a raw KIS ``inquire-price`` response dict into a ``MarketDataSnapshot``.

    All field accesses are guarded with ``None`` fallback.
    """
    def _decimal(key: str) -> Decimal | None:
        val = raw.get(key)
        if val is None:
            return None
        try:
            return Decimal(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    def _str_val(key: str) -> str | None:
        val = raw.get(key)
        if val is None:
            return None
        s = str(val).strip()
        # Return None only if the key was truly absent (val is None).
        # Empty string "" is a valid value (e.g. iscd_stat_cls_code="" means normal).
        return s if s != "" else ""

    return MarketDataSnapshot(
        symbol=symbol,
        market=market,
        current_price=_decimal("stck_prpr"),
        change_rate=_decimal("prdy_ctrt"),
        acc_trade_amount=_decimal("acml_tr_pbmn"),
        high_price=_decimal("stck_hgpr"),
        low_price=_decimal("stck_lwpr"),
        open_price=_decimal("stck_oprc"),
        iscd_stat_cls_code=_str_val("iscd_stat_cls_code"),
        raw=dict(raw),
    )


# ── Pure functions: Liquidity Filter helpers (F4, F5) ───────────────────────


def _check_iscd_stat_cls_code(status_code: str | None) -> LiquidityFilterResult:
    """F4: iscd_stat_cls_code 기반 종목 상태 필터.

    P2 필수. 단, 코드 매핑은 KIS Excel 확인 필요 (assumed).
    Fallback: status_code가 None이거나 empty면 PASS (보수적 허용).
    알 수 없는 코드 → PASS (보수적).
    """
    if not status_code:  # None or empty → assume normal
        return LiquidityFilterResult(True)
    if status_code in _SUSPENDED_STATUS_CODES:
        return LiquidityFilterResult(False, f"suspended_status:{status_code}")
    # 알 수 없는 코드 → PASS (보수적)
    logger.debug(
        "F4: unknown iscd_stat_cls_code=%r — PASS (guarded). "
        "TODO: verify code mapping against KIS Excel.",
        status_code,
    )
    return LiquidityFilterResult(True)


def _check_acc_trade_amount(
    acc_trade_amount: Decimal | None,
    *,
    threshold: Decimal = _ACC_VOLUME_THRESHOLD,
) -> LiquidityFilterResult:
    """F5: 당일 누적 거래대금 필터.

    P2 필수. acml_tr_pbmn이 threshold 미만 → 제외.
    Fallback: acc_trade_amount가 None이면 PASS (데이터 없으면 보수적 허용).
    """
    if acc_trade_amount is None:
        return LiquidityFilterResult(True)
    if acc_trade_amount < threshold:
        return LiquidityFilterResult(False, f"low_volume:{acc_trade_amount}")
    return LiquidityFilterResult(True)


def _metadata_flag(metadata: dict[str, object], key: str) -> bool | None:
    raw = metadata.get(key)
    if isinstance(raw, bool):
        return raw
    return None


def _normalize_asset_class(asset_class: str | None) -> str:
    return str(asset_class or "").strip().lower()


def _is_standard_krx_symbol(symbol: str) -> bool:
    return _STANDARD_KRX_SYMBOL_PATTERN.match(str(symbol or "").strip()) is not None


def _normalize_market_code(market: str | None) -> str:
    return str(market or "").strip().upper()


def _is_supported_kr_equity_market(market: str | None) -> bool:
    return _normalize_market_code(market) in _SUPPORTED_KR_EQUITY_MARKETS


def _looks_like_preferred_or_special_share(symbol: str, name: str) -> bool:
    normalized_name = str(name or "").strip()
    _ = symbol
    if normalized_name.endswith("(전환)"):
        return True
    return re.search(r"(우|우B|[123]우|[123]우B)$", normalized_name) is not None


def _is_core_seed_instrument_symbol(symbol: str) -> bool:
    return str(symbol or "").strip() in APPROVED_CORE_UNIVERSE_SYMBOLS


def _is_discovery_seed_instrument_symbol(symbol: str) -> bool:
    return str(symbol or "").strip() in APPROVED_DISCOVERY_UNIVERSE_SYMBOLS


def _segment_value(metadata: dict[str, object]) -> str | None:
    for key in ("market_segment", "segment", "universe_segment"):
        raw = metadata.get(key)
        if raw is None:
            continue
        value = str(raw).strip().upper()
        if value:
            return value
    return None


def _instrument_market_segment(instrument: object) -> str | None:
    raw = getattr(instrument, "market_segment", None)
    if raw is not None:
        value = str(raw).strip().upper()
        if value:
            return value
    metadata = getattr(instrument, "metadata", {}) or {}
    raw = metadata.get("market_segment")
    if raw is None:
        return None
    value = str(raw).strip().upper()
    return value or None


def _metadata_index_membership_values(instrument: object) -> frozenset[str]:
    metadata = getattr(instrument, "metadata", {}) or {}
    raw = metadata.get("index_memberships")
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, Sequence):
        values = list(raw)
    else:
        return frozenset()
    normalized: set[str] = set()
    for value in values:
        item = str(value).strip().upper()
        if item:
            normalized.add(item)
    return frozenset(normalized)


def _calc_overlay_capture_rate(added_count: int, candidate_count: int) -> float | None:
    if candidate_count <= 0:
        return None
    return added_count / candidate_count


def _calc_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _normalize_event_type(event_type: str | None) -> str:
    normalized = str(event_type or "").strip()
    lowered = normalized.lower()
    return _EVENT_TYPE_ALIASES.get(lowered, lowered or "unknown")


def _event_importance_level(metadata: dict[str, object] | None) -> str | None:
    raw = (metadata or {}).get("importance")
    if raw is None:
        return None
    return str(raw).strip().lower() or None


def _meets_event_overlay_threshold(
    event_type: str,
    severity: str | None,
    importance: str | None,
) -> bool:
    required = _EVENT_OVERLAY_POLICY.get(event_type)
    if required is None:
        return False
    actual_level = max(
        _EVENT_SEVERITY_ORDER.get(str(severity or "").strip().lower(), -1),
        _EVENT_SEVERITY_ORDER.get(str(importance or "").strip().lower(), -1),
    )
    required_level = _EVENT_SEVERITY_ORDER[required]
    return actual_level >= required_level


# ── LiquidityFilter class ────────────────────────────────────────────────────


class LiquidityFilter:
    """Deterministic pre-gate for universe candidates.

    P1 implements:
    - ``is_active`` check (inactive instruments excluded)
    - Tick-size heuristic (tick_size >= 1000 → micro-cap exclusion)
    - Unknown instrument exclusion

    P2 minimum adds:
    - F4: ``iscd_stat_cls_code`` — suspended/managed status (guarded/soft)
    - F5: ``acml_tr_pbmn < threshold`` — low volume exclusion
    """

    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos

    async def _resolve_instrument(
        self,
        symbol: str,
        market: str,
    ) -> object | None:
        normalized_market = _normalize_market_code(market)
        instrument = await self._repos.instruments.get_by_symbol(symbol, normalized_market)
        if instrument is not None:
            return instrument
        if not _is_supported_kr_equity_market(normalized_market):
            return None
        fallback = await self._repos.instruments.get_by_symbol_any_market(symbol)
        if fallback is None:
            return None
        if not _is_supported_kr_equity_market(getattr(fallback, "market_code", None)):
            return None
        return fallback

    async def check(self, symbol: str, market: str) -> LiquidityFilterResult:
        """Run all deterministic liquidity checks for a single symbol.

        Returns ``LiquidityFilterResult(passed=True)`` if all checks pass,
        or ``LiquidityFilterResult(passed=False, fail_reason=...)`` with
        the first failing reason.
        """
        normalized_market = _normalize_market_code(market)
        if not _is_supported_kr_equity_market(normalized_market):
            return LiquidityFilterResult(False, "unsupported_market")

        instrument = await self._resolve_instrument(symbol, normalized_market)
        if instrument is None:
            return LiquidityFilterResult(False, "unknown_instrument")

        if not instrument.is_active:
            return LiquidityFilterResult(False, "inactive_instrument")

        if _normalize_asset_class(instrument.asset_class) != "kr_stock":
            return LiquidityFilterResult(False, "unsupported_asset_class")

        metadata = instrument.metadata or {}
        if _metadata_flag(metadata, "exclude_from_trading_universe") is True:
            return LiquidityFilterResult(False, "metadata_excluded")

        if _metadata_flag(metadata, "broker_supported") is False:
            return LiquidityFilterResult(False, "broker_unsupported")

        if _metadata_flag(metadata, "instrument_complete") is False:
            return LiquidityFilterResult(False, "incomplete_instrument")

        if not _is_standard_krx_symbol(instrument.symbol):
            return LiquidityFilterResult(False, "non_standard_symbol")

        if _looks_like_preferred_or_special_share(instrument.symbol, instrument.name):
            return LiquidityFilterResult(False, "preferred_share_class")

        # Tick-size heuristic: large tick size often indicates low liquidity
        # or micro-cap stocks on KRX.
        if (
            instrument.tick_size is not None
            and instrument.tick_size >= _TICK_SIZE_MICRO_CAP_THRESHOLD
        ):
            return LiquidityFilterResult(False, "tick_size_too_large")

        # P2 F4 and F5 are applied in _add_market_overlay() only,
        # not in the base LiquidityFilter.check(), because they require
        # KIS inquire-price response data.
        return LiquidityFilterResult(True)

    async def check_market_snapshot(
        self,
        snapshot: MarketDataSnapshot,
    ) -> LiquidityFilterResult:
        """Run P2 liquidity checks (F4, F5) on a market data snapshot.

        These checks require KIS ``inquire-price`` response data and are
        applied only to market-driven overlay candidates.
        """
        # F4: iscd_stat_cls_code (guarded/soft path)
        f4 = _check_iscd_stat_cls_code(snapshot.iscd_stat_cls_code)
        if not f4.passed:
            return f4

        # F5: 누적 거래대금 threshold
        f5 = _check_acc_trade_amount(snapshot.acc_trade_amount)
        if not f5.passed:
            return f5

        return LiquidityFilterResult(True)


# ── UniverseSelectionService ─────────────────────────────────────────────────


class UniverseSelectionService:
    """Compose the trading universe from 4 input sources.

    Flow
    ----
    1. **Core Universe** — DB active KRX instruments (``InstrumentRepository``).
    2. **Held Positions** — Account positions with ``quantity > 0``
       (mandatory override).
    3. **Event-Driven Overlay** — ``ExternalEventRepository`` events with
       ``severity='high'`` since the given timestamp.
    4. **Market-Driven Overlay** — KIS ``inquire-price`` batch → score → top N
       (P2 minimum).
    5. **Exclusion Rules** — ``LiquidityFilter`` deterministic pre-gate.
    6. **Priority Sort** — Held > Event > Market > Core.
    7. **Daily Cap** — Limit non-held symbols to ``max_cap``.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        liquidity_filter: LiquidityFilter | None = None,
        kis_client: KISRestClient | None = None,
    ) -> None:
        self._repos = repos
        self._liquidity_filter = liquidity_filter or LiquidityFilter(repos)
        self._kis_client = kis_client

    async def _index_membership_values(self, instrument: object) -> frozenset[str]:
        instrument_id = getattr(instrument, "instrument_id", None)
        if instrument_id is not None:
            memberships = await self._repos.instrument_index_memberships.list_active_by_instrument(
                instrument_id
            )
            if memberships:
                return frozenset(
                    str(item.membership_code).strip().upper()
                    for item in memberships
                    if str(item.membership_code).strip()
                )
        return _metadata_index_membership_values(instrument)

    async def _is_core_seed_instrument(self, instrument: object) -> bool:
        metadata = getattr(instrument, "metadata", {}) or {}
        flagged = _metadata_flag(metadata, "core_universe")
        if flagged is not None:
            return flagged
        memberships = await self._index_membership_values(instrument)
        if memberships:
            segment = _instrument_market_segment(instrument)
            if segment == "KOSPI" and memberships & _CORE_INDEX_MEMBERSHIP_CODES:
                return True
        return _is_core_seed_instrument_symbol(getattr(instrument, "symbol", ""))

    async def _is_market_discovery_seed_instrument(self, instrument: object) -> bool:
        metadata = getattr(instrument, "metadata", {}) or {}
        if await self._is_core_seed_instrument(instrument):
            return True
        if _is_discovery_seed_instrument_symbol(getattr(instrument, "symbol", "")):
            return True
        if _metadata_flag(metadata, "market_discovery_pool") is True:
            return True
        segment = _segment_value(metadata)
        if segment is not None and segment in _DISCOVERY_SEGMENT_CODES:
            return True
        memberships = await self._index_membership_values(instrument)
        if memberships & _DISCOVERY_INDEX_MEMBERSHIP_CODES:
            segment = _instrument_market_segment(instrument)
            if segment == "KOSDAQ":
                return True
        return False

    async def _build_selected_symbol(
        self,
        *,
        symbol: str,
        market: str,
        source_type: SourceType,
        inclusion_reason: str,
        instrument: object | None = None,
    ) -> SelectedSymbol:
        resolved_instrument = instrument
        if resolved_instrument is None:
            resolved_instrument = await self._repos.instruments.get_by_symbol_any_market(symbol)
        market_segment = (
            _instrument_market_segment(resolved_instrument)
            if resolved_instrument is not None
            else None
        )
        memberships = (
            await self._index_membership_values(resolved_instrument)
            if resolved_instrument is not None
            else frozenset()
        )
        return SelectedSymbol(
            symbol=symbol,
            market=market,
            source_type=source_type,
            inclusion_reason=inclusion_reason,
            market_segment=market_segment,
            index_memberships=normalize_index_memberships(memberships),
            primary_index_membership=derive_primary_index_membership(memberships),
        )

    async def _list_active_kr_equity_instruments(self) -> list[object]:
        items_by_symbol: dict[str, object] = {}
        for market_code in ("KRX", "KOSPI", "KOSDAQ"):
            instruments = await self._repos.instruments.list_active_by_market(market_code)
            for instrument in instruments:
                symbol = getattr(instrument, "symbol", "")
                if not symbol or symbol in items_by_symbol:
                    continue
                segment = _instrument_market_segment(instrument)
                if market_code == "KRX" and segment not in {"KOSPI", "KOSDAQ"}:
                    continue
                items_by_symbol[symbol] = instrument
        return list(items_by_symbol.values())

    async def compose(self, ctx: CompositionContext) -> list[SelectedSymbol]:
        selected, _ = await self.compose_with_diagnostics(ctx)
        return selected

    async def compose_with_diagnostics(
        self,
        ctx: CompositionContext,
    ) -> tuple[list[SelectedSymbol], MarketOverlayDiagnostics]:
        """Compose the final trading universe for a single decision cycle.

        Parameters
        ----------
        ctx : CompositionContext
            Account ID, look-back window, cap settings, P2 overlay config.

        Returns
        -------
        list[SelectedSymbol]
            Ordered list (highest priority first) ready for the decision loop.
        """
        seen: dict[str, SelectedSymbol] = {}

        # Step 1: Core Universe
        await self._add_core_universe(seen)

        # Step 2: Held Positions (mandatory override)
        await self._add_held_positions(seen, ctx)

        # Step 3: Reconciliation / open-order overlay (mandatory for order safety)
        await self._add_reconciliation_overlay(seen, ctx)

        # Step 4: Event-Driven Overlay
        await self._add_event_overlay(seen, ctx)

        # Step 5: Manual Watchlist Overlay
        await self._add_manual_overlay(seen, ctx)

        # Step 6: Market-Driven Overlay (P2 minimum)
        market_overlay_diagnostics = await self._add_market_overlay(seen, ctx)

        # Step 7: Exclusion Rules (Liquidity Filter)
        candidates = await self._apply_exclusions(seen)

        # Step 8: Priority Sort (ascending priority value = highest first)
        candidates.sort(key=lambda s: s.priority)

        # Step 9: Daily Cap
        return self._apply_cap(candidates, ctx), market_overlay_diagnostics

    # ── Step implementations ─────────────────────────────────────────────

    async def _add_core_universe(
        self,
        seen: dict[str, SelectedSymbol],
    ) -> None:
        """Load only approved core-seed instruments as the Core Universe."""
        instruments = await self._list_active_kr_equity_instruments()
        for inst in instruments:
            if not await self._is_core_seed_instrument(inst):
                continue
            sym = inst.symbol
            if sym not in seen:
                seen[sym] = await self._build_selected_symbol(
                    symbol=sym,
                    market=inst.market_code,
                    source_type=SourceType.CORE,
                    inclusion_reason=INCLUSION_REASON_CORE,
                    instrument=inst,
                )

    async def _add_held_positions(
        self,
        seen: dict[str, SelectedSymbol],
        ctx: CompositionContext,
    ) -> None:
        """Override universe with held positions (mandatory).

        Resolves ``instrument_id`` → ``symbol`` / ``market_code`` via
        ``InstrumentRepository.get()`` since ``PositionSnapshotEntity``
        only stores the FK.
        """
        positions = await self._repos.position_snapshots.list_latest_by_account(ctx.account_id)
        for pos in positions:
            if pos.quantity > 0:
                instrument = await self._repos.instruments.get(pos.instrument_id)
                if instrument is None:
                    logger.debug(
                        "Held position %s has no matching instrument — skipping.",
                        pos.instrument_id,
                    )
                    continue
                sym = instrument.symbol
                self._upsert_with_priority(
                    seen,
                    await self._build_selected_symbol(
                        symbol=sym,
                        market=instrument.market_code,
                        source_type=SourceType.HELD_POSITION,
                        inclusion_reason=INCLUSION_REASON_HELD,
                        instrument=instrument,
                    ),
                )

    async def _add_reconciliation_overlay(
        self,
        seen: dict[str, SelectedSymbol],
        ctx: CompositionContext,
    ) -> None:
        """Force-include open-order / reconciliation-required symbols.

        Policy rationale:
        - unknown order state must be checked before new order creation
        - open / reconcile-required lineage cannot fall out of the universe
        """
        instrument_cache: dict[object, object | None] = {}

        async def _resolve_instrument(order_instrument_id: object) -> object | None:
            if order_instrument_id not in instrument_cache:
                instrument_cache[order_instrument_id] = await self._repos.instruments.get(
                    order_instrument_id
                )
            return instrument_cache[order_instrument_id]

        open_orders = await self._repos.orders.list(
            OrderQuery(
                account_id=ctx.account_id,
                statuses=_ACTIVE_ORDER_STATUSES,
                limit=500,
            )
        )
        for order in open_orders:
            instrument = await _resolve_instrument(order.instrument_id)
            if instrument is None:
                continue
            self._upsert_with_priority(
                seen,
                await self._build_selected_symbol(
                    symbol=instrument.symbol,
                    market=instrument.market_code,
                    source_type=SourceType.RECONCILIATION_OVERLAY,
                    inclusion_reason=f"{INCLUSION_REASON_RECONCILIATION}:{order.status.value}",
                    instrument=instrument,
                ),
            )

        pending_runs = await self._repos.reconciliations.list_pending_runs(
            limit=50,
            account_id=ctx.account_id,
        )
        for run in pending_runs:
            links = await self._repos.reconciliations.get_run_order_links(
                run.reconciliation_run_id
            )
            for link in links:
                order = await self._repos.orders.get(link.order_request_id)
                if order is None:
                    continue
                instrument = await _resolve_instrument(order.instrument_id)
                if instrument is None:
                    continue
                self._upsert_with_priority(
                    seen,
                    await self._build_selected_symbol(
                        symbol=instrument.symbol,
                        market=instrument.market_code,
                        source_type=SourceType.RECONCILIATION_OVERLAY,
                        inclusion_reason=(
                            f"{INCLUSION_REASON_RECONCILIATION}:"
                            f"{link.mismatch_type or 'pending_run'}"
                        ),
                        instrument=instrument,
                    ),
                )

        locks = await self._repos.reconciliations.list_locks(ctx.account_id)
        for lock in locks:
            normalized_symbol = str(lock.symbol or "").strip()
            if not normalized_symbol:
                continue
            self._upsert_with_priority(
                seen,
                await self._build_selected_symbol(
                    symbol=normalized_symbol,
                    market="KRX",
                    source_type=SourceType.RECONCILIATION_OVERLAY,
                    inclusion_reason=f"{INCLUSION_REASON_RECONCILIATION}:blocking_lock",
                ),
            )

    async def _add_event_overlay(
        self,
        seen: dict[str, SelectedSymbol],
        ctx: CompositionContext,
    ) -> None:
        """정책상 의미 있는 최근 이벤트를 event_overlay로 승격한다."""
        fetched: list[object] = []
        for event_type in _EVENT_FETCH_TYPES:
            events = await self._repos.external_events.list_by_type(
                event_type,
                ctx.since,
                include_seeded_news=True,
            )
            fetched.extend(events)

        fetched.sort(
            key=lambda item: getattr(item, "published_at", None),
            reverse=True,
        )

        for event in fetched:
            sym = getattr(event, "symbol", None)
            if sym is None:
                continue

            normalized_event_type = _normalize_event_type(getattr(event, "event_type", None))
            importance = _event_importance_level(getattr(event, "metadata", None))
            if not _meets_event_overlay_threshold(
                normalized_event_type,
                getattr(event, "severity", None),
                importance,
            ):
                continue

            self._upsert_with_priority(
                seen,
                await self._build_selected_symbol(
                    symbol=sym,
                    market=getattr(event, "market", None) or "KRX",
                    source_type=SourceType.EVENT_OVERLAY,
                    inclusion_reason=(
                        f"{INCLUSION_REASON_EVENT}:{normalized_event_type}"
                    ),
                ),
            )

    async def _add_manual_overlay(
        self,
        seen: dict[str, SelectedSymbol],
        ctx: CompositionContext,
    ) -> None:
        """Add operator-supplied manual watchlist symbols.

        Manual symbols are deterministic operator hints.  They are:
        - opt-in only (empty by default)
        - lower priority than event/market overlays
        - still subject to the standard liquidity filter and daily cap
        """
        for symbol, market in ctx.manual_symbols:
            normalized_symbol = str(symbol or "").strip()
            normalized_market = str(market or "KRX").strip().upper() or "KRX"
            if not normalized_symbol:
                continue
            self._upsert_with_priority(
                seen,
                await self._build_selected_symbol(
                    symbol=normalized_symbol,
                    market=normalized_market,
                    source_type=SourceType.MANUAL,
                    inclusion_reason=INCLUSION_REASON_MANUAL,
                ),
            )

    def _effective_pre_pool_size(self, ctx: CompositionContext) -> int:
        """Paper 환경에서는 pre-pool size를 20으로 제한.

        Live 환경(capacity=24, refill=6.0)에서는 문제가 없으므로
        ctx.pre_pool_size (50)을 그대로 사용.
        Paper 환경(capacity=1, refill=0.5)에서는 budget exhaustion을
        완화하기 위해 최대 20으로 축소.
        """
        if self._kis_client is not None and hasattr(self._kis_client, "env") and self._kis_client.env == "paper":
            return min(ctx.pre_pool_size, 20)
        return ctx.pre_pool_size

    async def _add_market_overlay(
        self,
        seen: dict[str, SelectedSymbol],
        ctx: CompositionContext,
    ) -> MarketOverlayDiagnostics:
        """Add market-driven overlay candidates (P2 minimum).

        처리 순서
        --------
        1. 가능하면 KIS 랭킹 API에서 seed pool을 구성한다.
        2. 랭킹 seed가 비면 core seed pre-pool로 fallback한다.
        3. ``inquire-price`` batch로 quote를 조회한다.
        4. ``MarketDataSnapshot``으로 파싱한다.
        5. F4/F5 필터를 적용한다.
        6. composite score를 계산한 뒤 상위 N개를 편입한다.

        If ``kis_client`` is ``None`` (no KIS configured), this is a no-op
        (P1-compatible stub behaviour).

        Paper env: KIS paper mock quote API is structurally unstable (>90%
        failure rate).  Skip market_overlay entirely to avoid log noise and
        unnecessary KIS 500 errors.
        """
        if self._kis_client is None:
            logger.debug("_add_market_overlay: no KIS client — skipping (P1 stub).")
            return MarketOverlayDiagnostics(
                enabled=False,
                skipped_reason="no_kis_client",
            )

        # Paper env: KIS paper API 구조적 불안정(>90% failure)으로 market_overlay skip
        if hasattr(self._kis_client, "env") and self._kis_client.env == "paper":
            logger.info(
                "market_overlay: skipped in paper env "
                "(KIS paper mock quote API unstable, >90%% failure)"
            )
            return MarketOverlayDiagnostics(
                enabled=False,
                skipped_reason="paper_env_skipped",
            )

        # ── Step 1: seed pool / pre-pool 구성 ────────────────────────────
        effective_pool_size = self._effective_pre_pool_size(ctx)
        ranking_seed_symbols: list[str] = []
        seed_pool_source = "core_fallback"

        get_seed_symbols = getattr(self._kis_client, "get_market_overlay_seed_symbols", None)
        if callable(get_seed_symbols):
            ranking_seed_symbols = list(
                await get_seed_symbols(limit=max(effective_pool_size, 30))
            )
            if ranking_seed_symbols:
                seed_pool_source = "kis_ranking"

        if ranking_seed_symbols:
            seed_pool_symbols = ranking_seed_symbols
        else:
            core_symbols = await self._list_active_kr_equity_instruments()
            seed_pool_symbols: list[str] = []
            for inst in core_symbols:
                if await self._is_market_discovery_seed_instrument(inst):
                    seed_pool_symbols.append(inst.symbol)

        symbol_market_map: dict[str, str] = {}
        for symbol in seed_pool_symbols:
            instrument = await self._repos.instruments.get_by_symbol_any_market(symbol)
            if instrument is None:
                continue
            market_code = getattr(instrument, "market_code", None)
            if not _is_supported_kr_equity_market(market_code):
                continue
            symbol_market_map[symbol] = _normalize_market_code(market_code)

        pre_pool_candidates: list[tuple[str, str]] = []
        for sym in seed_pool_symbols:
            market_code = symbol_market_map.get(sym, "KRX")
            if sym in seen and seen[sym].source_type != SourceType.CORE:
                continue
            base_filter = await self._liquidity_filter.check(sym, market_code)
            if not base_filter.passed:
                continue
            pre_pool_candidates.append((sym, market_code))
            if len(pre_pool_candidates) >= effective_pool_size:
                break

        if not pre_pool_candidates:
            logger.debug("_add_market_overlay: pre-pool is empty — skipping.")
            return MarketOverlayDiagnostics(
                enabled=True,
                skipped_reason="empty_pre_pool",
                seed_pool_source=seed_pool_source,
                seed_pool_count=len(seed_pool_symbols),
                effective_pre_pool_size=effective_pool_size,
                pre_pool_candidate_count=0,
            )

        logger.info(
            "market_overlay pre-pool: %d symbols (cap=%d, env=%s).",
            len(pre_pool_candidates),
            effective_pool_size,
            getattr(self._kis_client, "env", "unknown"),
        )

        # ── Step 2: Fetch quotes batch ───────────────────────────────────
        raw_batch = await self._kis_client.get_quotes_batch(
            [symbol for symbol, _market in pre_pool_candidates]
        )

        if not raw_batch:
            logger.debug("_add_market_overlay: no quotes returned — skipping.")
            return MarketOverlayDiagnostics(
                enabled=True,
                skipped_reason="no_quotes_returned",
                seed_pool_source=seed_pool_source,
                seed_pool_count=len(seed_pool_symbols),
                effective_pre_pool_size=effective_pool_size,
                pre_pool_candidate_count=len(pre_pool_candidates),
                quotes_requested_count=len(pre_pool_candidates),
                quotes_received_count=0,
                quote_success_rate=0.0,
            )

        # ── Step 2.5: Count successful quote fetches ─────────────────────
        total = len(pre_pool_candidates)
        success = sum(
            1 for sym, _market in pre_pool_candidates if raw_batch.get(sym) is not None
        )
        if success < total:
            logger.warning(
                "market_overlay quotes fetched: %d/%d "
                "(budget exhaustion expected in paper env).",
                success,
                total,
            )
        else:
            logger.info(
                "market_overlay quotes fetched: %d/%d.",
                success,
                total,
            )

        # ── Step 3: Parse → Filter → Score ───────────────────────────────
        scored: list[tuple[float, MarketDataSnapshot]] = []
        filtered_out_count = 0

        for sym, market_code in pre_pool_candidates:
            raw = raw_batch.get(sym)
            if raw is None:
                # Failed quote → skip (not crash)
                continue

            snapshot = _parse_quote_to_snapshot(sym, market_code, raw)

            # Step 4: F4 + F5 filter
            filter_result = await self._liquidity_filter.check_market_snapshot(snapshot)
            if not filter_result.passed:
                filtered_out_count += 1
                logger.debug(
                    "Market overlay candidate %s excluded: %s",
                    sym,
                    filter_result.fail_reason,
                )
                continue

            # Step 5: Score
            score = _calc_market_score(snapshot)
            scored.append((score, snapshot))

        if not scored:
            logger.debug("_add_market_overlay: no candidates passed filters — skipping.")
            return MarketOverlayDiagnostics(
                enabled=True,
                skipped_reason="all_candidates_filtered",
                seed_pool_source=seed_pool_source,
                seed_pool_count=len(seed_pool_symbols),
                effective_pre_pool_size=effective_pool_size,
                pre_pool_candidate_count=len(pre_pool_candidates),
                quotes_requested_count=total,
                quotes_received_count=success,
                filtered_out_count=filtered_out_count,
                scored_candidate_count=0,
                added_count=0,
                quote_success_rate=_calc_ratio(success, total),
                filter_pass_rate=0.0,
                scored_capture_rate=0.0,
                overlay_capture_rate=0.0,
            )

        # ── Step 6: Select top N ─────────────────────────────────────────
        scored.sort(key=lambda x: x[0], reverse=True)
        top_n = scored[: ctx.market_overlay_cap]

        for score, snapshot in top_n:
            reason = _categorize_market_reason(snapshot, score)
            self._upsert_with_priority(
                seen,
                await self._build_selected_symbol(
                    symbol=snapshot.symbol,
                    market=snapshot.market,
                    source_type=SourceType.MARKET_OVERLAY,
                    inclusion_reason=reason,
                ),
            )

        logger.info(
            "market_overlay symbols added to universe: %d (cap=%d, candidates=%d).",
            len(top_n),
            ctx.market_overlay_cap,
            len(scored),
        )
        return MarketOverlayDiagnostics(
            enabled=True,
            skipped_reason=None,
            seed_pool_source=seed_pool_source,
            seed_pool_count=len(seed_pool_symbols),
            effective_pre_pool_size=effective_pool_size,
            pre_pool_candidate_count=len(pre_pool_candidates),
            quotes_requested_count=total,
            quotes_received_count=success,
            filtered_out_count=filtered_out_count,
            scored_candidate_count=len(scored),
            added_count=len(top_n),
            quote_success_rate=_calc_ratio(success, total),
            filter_pass_rate=_calc_ratio(len(scored), success),
            scored_capture_rate=_calc_ratio(len(top_n), len(scored)),
            overlay_capture_rate=_calc_overlay_capture_rate(
                len(top_n),
                len(pre_pool_candidates),
            ),
        )

    async def _apply_exclusions(
        self,
        seen: dict[str, SelectedSymbol],
    ) -> list[SelectedSymbol]:
        """Apply Liquidity Filter to all candidates."""
        result: list[SelectedSymbol] = []
        for sym in seen.values():
            if sym.source_type in {
                SourceType.HELD_POSITION,
                SourceType.RECONCILIATION_OVERLAY,
            }:
                result.append(sym)
                continue
            lf = await self._liquidity_filter.check(sym.symbol, sym.market)
            if lf.passed:
                result.append(sym)
            else:
                logger.debug(
                    "Excluded %s/%s: %s",
                    sym.symbol,
                    sym.market,
                    lf.fail_reason,
                )
        return result

    @staticmethod
    def _upsert_with_priority(
        seen: dict[str, SelectedSymbol],
        incoming: SelectedSymbol,
    ) -> None:
        """Add or update ``seen`` respecting source-type priority hierarchy.

        Priority hierarchy (lower number = higher priority):
            HELD_POSITION(0) > RECONCILIATION_OVERLAY(1) > EVENT_OVERLAY(2)
            > MARKET_OVERLAY(3) > MANUAL(4) > CORE(5)
            - HELD_POSITION(0): highest — never overwritten (mandatory override).
            - RECONCILIATION_OVERLAY(1): unknown/open order state management.
            - EVENT_OVERLAY(2) > MARKET_OVERLAY(3): event wins over market on same symbol.
            - MARKET_OVERLAY(3) > MANUAL(4): market signal beats manual inclusion.
            - MANUAL(4): reserved for future operator override; current precedence
              follows ``SourceType.priority()``.
            - CORE(5): lowest — always eligible for promotion.

        Rule: ``incoming.priority < existing.priority`` → overwrite.
        Equal or lower priority → keep existing (first-writer wins).
        """
        existing = seen.get(incoming.symbol)
        if existing is None or incoming.priority < existing.priority:
            seen[incoming.symbol] = incoming
            return
        if (
            existing.source_type == SourceType.RECONCILIATION_OVERLAY
            and incoming.source_type == SourceType.RECONCILIATION_OVERLAY
            and existing.inclusion_reason.endswith(
                f":{OrderStatus.RECONCILE_REQUIRED.value}"
            )
            and incoming.inclusion_reason
            != f"{INCLUSION_REASON_RECONCILIATION}:{OrderStatus.RECONCILE_REQUIRED.value}"
        ):
            seen[incoming.symbol] = incoming

    @staticmethod
    def _apply_cap(
        candidates: list[SelectedSymbol],
        ctx: CompositionContext,
    ) -> list[SelectedSymbol]:
        """Apply daily cap, optionally excluding held positions."""
        if not ctx.exclude_held_from_cap:
            return candidates[: ctx.max_cap]

        capped: list[SelectedSymbol] = []
        non_held_count = 0
        core_count = 0
        event_count = 0
        reconciliation_exempt_count = 0
        for sym in candidates:
            if sym.source_type == SourceType.HELD_POSITION:
                capped.append(sym)
                continue

            if sym.source_type == SourceType.RECONCILIATION_OVERLAY:
                if (
                    ctx.reconciliation_overlay_reserve is None
                    or reconciliation_exempt_count < ctx.reconciliation_overlay_reserve
                ):
                    capped.append(sym)
                    reconciliation_exempt_count += 1
                    continue

            if non_held_count >= ctx.max_cap:
                break
            if (
                sym.source_type == SourceType.CORE
                and ctx.core_cap is not None
                and core_count >= ctx.core_cap
            ):
                continue
            if (
                sym.source_type == SourceType.EVENT_OVERLAY
                and ctx.event_overlay_cap is not None
                and event_count >= ctx.event_overlay_cap
            ):
                continue

            capped.append(sym)
            non_held_count += 1
            if sym.source_type == SourceType.CORE:
                core_count += 1
            if sym.source_type == SourceType.EVENT_OVERLAY:
                event_count += 1
        return capped
