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
- ``plans/universe_selection_service_p1_design.md`` — P1 design document
- ``plans/universe_selection_service_p2_market_overlay_design.md`` — P2 design
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Sequence

from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.universe_selection_types import (
    INCLUSION_REASON_CORE,
    INCLUSION_REASON_EVENT,
    INCLUSION_REASON_HELD,
    INCLUSION_REASON_NEAR_HIGH,
    INCLUSION_REASON_PRICE_VOLUME_BREAKOUT,
    INCLUSION_REASON_TRADE_STRENGTH,
    INCLUSION_REASON_VOLUME_SURGE,
    CompositionContext,
    LiquidityFilterResult,
    MarketDataSnapshot,
    SelectedSymbol,
    SourceType,
)

if TYPE_CHECKING:
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient

logger = logging.getLogger(__name__)

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

    async def check(self, symbol: str, market: str) -> LiquidityFilterResult:
        """Run all deterministic liquidity checks for a single symbol.

        Returns ``LiquidityFilterResult(passed=True)`` if all checks pass,
        or ``LiquidityFilterResult(passed=False, fail_reason=...)`` with
        the first failing reason.
        """
        instrument = await self._repos.instruments.get_by_symbol(symbol, market)
        if instrument is None:
            return LiquidityFilterResult(False, "unknown_instrument")

        if not instrument.is_active:
            return LiquidityFilterResult(False, "inactive_instrument")

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

    async def compose(self, ctx: CompositionContext) -> list[SelectedSymbol]:
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

        # Step 3: Event-Driven Overlay
        await self._add_event_overlay(seen, ctx)

        # Step 4: Market-Driven Overlay (P2 minimum)
        await self._add_market_overlay(seen, ctx)

        # Step 5: Exclusion Rules (Liquidity Filter)
        candidates = await self._apply_exclusions(seen)

        # Step 6: Priority Sort (ascending priority value = highest first)
        candidates.sort(key=lambda s: s.priority)

        # Step 7: Daily Cap
        return self._apply_cap(candidates, ctx)

    # ── Step implementations ─────────────────────────────────────────────

    async def _add_core_universe(
        self,
        seen: dict[str, SelectedSymbol],
    ) -> None:
        """Load all active KRX instruments as the Core Universe."""
        instruments = await self._repos.instruments.list_active_by_market("KRX")
        for inst in instruments:
            sym = inst.symbol
            if sym not in seen:
                seen[sym] = SelectedSymbol(
                    symbol=sym,
                    market=inst.market_code,
                    source_type=SourceType.CORE,
                    inclusion_reason=INCLUSION_REASON_CORE,
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
                    SelectedSymbol(
                        symbol=sym,
                        market=instrument.market_code,
                        source_type=SourceType.HELD_POSITION,
                        inclusion_reason=INCLUSION_REASON_HELD,
                    ),
                )

    async def _add_event_overlay(
        self,
        seen: dict[str, SelectedSymbol],
        ctx: CompositionContext,
    ) -> None:
        """Promote symbols with high-severity events to event_overlay."""
        events = await self._repos.external_events.list_by_type(
            "disclosure", ctx.since
        )
        for event in events:
            sym = event.symbol
            if sym is None:
                continue
            if event.severity == "high":
                self._upsert_with_priority(
                    seen,
                    SelectedSymbol(
                        symbol=sym,
                        market=event.market or "KRX",
                        source_type=SourceType.EVENT_OVERLAY,
                        inclusion_reason=f"{INCLUSION_REASON_EVENT}:{event.event_type}",
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
    ) -> None:
        """Add market-driven overlay candidates (P2 minimum).

        Flow
        ----
        1. Build pre-pool from core universe (exclude already-seen symbols).
        2. Fetch quotes via KIS ``inquire-price`` batch (budget-safe).
        3. Parse responses into ``MarketDataSnapshot``.
        4. Apply F4 (iscd_stat_cls_code) and F5 (low volume) filters.
        5. Calculate composite score for remaining candidates.
        6. Select top N (``market_overlay_cap``) for inclusion.

        If ``kis_client`` is ``None`` (no KIS configured), this is a no-op
        (P1-compatible stub behaviour).

        Paper env: KIS paper mock quote API is structurally unstable (>90%
        failure rate).  Skip market_overlay entirely to avoid log noise and
        unnecessary KIS 500 errors.
        """
        if self._kis_client is None:
            logger.debug("_add_market_overlay: no KIS client — skipping (P1 stub).")
            return

        # Paper env: KIS paper API 구조적 불안정(>90% failure)으로 market_overlay skip
        if hasattr(self._kis_client, "env") and self._kis_client.env == "paper":
            logger.info(
                "market_overlay: skipped in paper env "
                "(KIS paper mock quote API unstable, >90%% failure)"
            )
            return

        # ── Step 1: Build pre-pool ───────────────────────────────────────
        effective_pool_size = self._effective_pre_pool_size(ctx)
        core_symbols = await self._repos.instruments.list_active_by_market("KRX")
        pre_pool_candidates: list[str] = []
        for inst in core_symbols:
            sym = inst.symbol
            # Core symbol은 seen에 이미 있더라도 pre-pool에 포함.
            # Held/Event/Manual symbol만 제외 (이미 더 높은 우선순위로 포함됨).
            if sym not in seen or seen[sym].source_type == SourceType.CORE:
                pre_pool_candidates.append(sym)
            if len(pre_pool_candidates) >= effective_pool_size:
                break

        if not pre_pool_candidates:
            logger.debug("_add_market_overlay: pre-pool is empty — skipping.")
            return

        logger.info(
            "market_overlay pre-pool: %d symbols (cap=%d, env=%s).",
            len(pre_pool_candidates),
            effective_pool_size,
            getattr(self._kis_client, "env", "unknown"),
        )

        # ── Step 2: Fetch quotes batch ───────────────────────────────────
        raw_batch = await self._kis_client.get_quotes_batch(pre_pool_candidates)

        if not raw_batch:
            logger.debug("_add_market_overlay: no quotes returned — skipping.")
            return

        # ── Step 2.5: Count successful quote fetches ─────────────────────
        total = len(pre_pool_candidates)
        success = sum(1 for sym in pre_pool_candidates if raw_batch.get(sym) is not None)
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

        for sym in pre_pool_candidates:
            raw = raw_batch.get(sym)
            if raw is None:
                # Failed quote → skip (not crash)
                continue

            snapshot = _parse_quote_to_snapshot(sym, "KRX", raw)

            # Step 4: F4 + F5 filter
            filter_result = await self._liquidity_filter.check_market_snapshot(snapshot)
            if not filter_result.passed:
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
            return

        # ── Step 6: Select top N ─────────────────────────────────────────
        scored.sort(key=lambda x: x[0], reverse=True)
        top_n = scored[: ctx.market_overlay_cap]

        for score, snapshot in top_n:
            reason = _categorize_market_reason(snapshot, score)
            self._upsert_with_priority(
                seen,
                SelectedSymbol(
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

    async def _apply_exclusions(
        self,
        seen: dict[str, SelectedSymbol],
    ) -> list[SelectedSymbol]:
        """Apply Liquidity Filter to all candidates."""
        result: list[SelectedSymbol] = []
        for sym in seen.values():
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
            HELD_POSITION(0) > EVENT_OVERLAY(1) > MARKET_OVERLAY(2) > MANUAL(3) > CORE(4)
            - HELD_POSITION(0): highest — never overwritten (mandatory override).
            - EVENT_OVERLAY(1) > MARKET_OVERLAY(2): event wins over market on same symbol.
            - MARKET_OVERLAY(2) > MANUAL(3): market signal beats manual inclusion.
            - MANUAL(3): reserved for future operator override; current precedence
              follows ``SourceType.priority()``.
            - CORE(4): lowest — always eligible for promotion.

        Rule: ``incoming.priority < existing.priority`` → overwrite.
        Equal or lower priority → keep existing (first-writer wins).
        """
        existing = seen.get(incoming.symbol)
        if existing is None or incoming.priority < existing.priority:
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
        for sym in candidates:
            if sym.source_type == SourceType.HELD_POSITION:
                capped.append(sym)
            elif non_held_count < ctx.max_cap:
                capped.append(sym)
                non_held_count += 1
            else:
                break
        return capped
