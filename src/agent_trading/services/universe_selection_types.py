"""Universe Selection Service — type definitions.

This module defines the data contracts for the Universe Selection Service
(P1 / P2), separating ``Instrument Master`` from ``Trading Universe``.

Reference
---------
- ``plans/[POLICY] trading_universe_policy_v1.md`` — 5-layer universe selection policy
- ``plans/[DESIGN] universe_selection_service.md`` — P1 design document
- ``plans/[DESIGN] universe_selection_service.md`` — P2 design document
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


class SourceType(str, Enum):
    """Origin of a symbol's inclusion in the trading universe.

    Values are ordered by priority (declared order = ascending priority).
    """

    CORE = "core"                      # Core Universe (KOSPI200, etc.)
    MARKET_OVERLAY = "market_overlay"  # Market-Driven (KIS ranking)
    EVENT_OVERLAY = "event_overlay"    # Event-Driven (OpenDART, news)
    RECONCILIATION_OVERLAY = "reconciliation_overlay"  # Open/reconcile-required orders
    HELD_POSITION = "held_position"    # Held position (mandatory)
    MANUAL = "manual"                  # Manual watchlist (future)

    @property
    def priority(self) -> int:
        """Lower value = higher priority (0 = highest)."""
        mapping: tuple[SourceType, ...] = (
            SourceType.HELD_POSITION,    # 0 — mandatory
            SourceType.RECONCILIATION_OVERLAY,  # 1 — unknown/open order state
            SourceType.EVENT_OVERLAY,    # 2 — important event
            SourceType.MARKET_OVERLAY,   # 3 — market signal
            SourceType.MANUAL,           # 4 — operator override
            SourceType.CORE,             # 5 — baseline
        )
        try:
            return mapping.index(self)
        except ValueError:
            return 99


# ── Inclusion reason constants ──────────────────────────────────────────────

INCLUSION_REASON_CORE = "approved_core_universe"
INCLUSION_REASON_HELD = "held_position_mandatory"
INCLUSION_REASON_EVENT = "high_importance_event"
INCLUSION_REASON_RECONCILIATION = "reconciliation_required"
INCLUSION_REASON_MANUAL = "manual_watchlist"

# Market-driven overlay reasons (P2)
INCLUSION_REASON_VOLUME_SURGE = "volume_surge_top10"
INCLUSION_REASON_TRADE_STRENGTH = "trade_strength_top10"
INCLUSION_REASON_NEAR_HIGH = "near_high_breakout"
INCLUSION_REASON_PRICE_VOLUME_BREAKOUT = "price_volume_breakout"


@dataclass(slots=True, frozen=True)
class SelectedSymbol:
    """A single symbol selected for the trading universe.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. ``"005930"``).
    market : str
        Market code (e.g. ``"KRX"``).
    source_type : SourceType
        Origin of this symbol's inclusion.
    inclusion_reason : str
        Human-readable / machine-readable reason string.
        Examples: ``"approved_core_universe"``, ``"held_position_mandatory"``,
        ``"high_importance_event:disclosure"``, ``"volume_surge_top10"``.
    """

    symbol: str
    market: str
    source_type: SourceType = SourceType.CORE
    inclusion_reason: str = INCLUSION_REASON_CORE
    market_segment: str | None = None
    index_memberships: tuple[str, ...] = ()
    primary_index_membership: str | None = None

    @property
    def priority(self) -> int:
        """Lower value = higher priority in the decision loop."""
        return self.source_type.priority


@dataclass(slots=True, frozen=True)
class CompositionContext:
    """Context for a single universe composition request.

    Parameters
    ----------
    account_id : UUID
        The account for which the universe is being composed.
    since : datetime
        Look-back window for event-driven overlay (events ingested after
        this timestamp are considered).
    max_cap : int
        Maximum number of non-held symbols in the final universe.
        Default: 30.
    core_cap : int | None
        Maximum number of ``core`` source symbols allowed inside the
        non-held universe. ``None`` means no separate core-only limit.
    event_overlay_cap : int | None
        Maximum number of ``event_overlay`` source symbols allowed inside
        the non-held universe. ``None`` means no separate event-only limit.
    exclude_held_from_cap : bool
        If True, held-position symbols do not count toward ``max_cap``.
        Default: True.
    market_overlay_cap : int
        Maximum number of market-driven overlay symbols to include per cycle.
        Default: 5 (P2 minimum).
    reconciliation_overlay_reserve : int | None
        Number of ``reconciliation_overlay`` symbols that are excluded from
        the normal ``max_cap`` accounting. ``None`` preserves the current
        behaviour where all reconciliation symbols are excluded from cap.
    pre_pool_size : int
        Maximum number of core-universe candidates to evaluate via
        ``inquire-price`` batch.  Default: 50 (P2 minimum).
    manual_symbols : tuple[tuple[str, str], ...]
        Operator-supplied manual watchlist entries.  Each item is
        ``(symbol, market)``.  Default: empty tuple (disabled).
    """

    account_id: UUID
    since: datetime
    max_cap: int = 30
    core_cap: int | None = None
    event_overlay_cap: int | None = None
    exclude_held_from_cap: bool = True
    market_overlay_cap: int = 5
    reconciliation_overlay_reserve: int | None = None
    pre_pool_size: int = 50
    manual_symbols: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True, frozen=True)
class MarketDataSnapshot:
    """Parsed KIS ``inquire-price`` response for a single symbol.

    P2 minimum uses three axes:
    1. **Absolute intraday turnover** — ``acc_trade_amount``
    2. **Change rate** — ``change_rate``
    3. **Near-high proximity** — ``current_price`` / ``high_price``

    All fields are optional; ``None`` means the data was unavailable
    (failed quote, missing field, parse error).  Consumers must handle
    ``None`` gracefully (score=0, filter PASS).
    """

    symbol: str
    market: str
    current_price: Decimal | None = None
    """``stck_prpr`` — 현재가 (KIS verified)."""

    change_rate: Decimal | None = None
    """``prdy_ctrt`` — 등락률 (KIS verified)."""

    acc_trade_amount: Decimal | None = None
    """``acml_tr_pbmn`` — 당일 누적 거래대금 (KIS assumed)."""

    high_price: Decimal | None = None
    """``stck_hgpr`` — 당일 고가 (KIS verified)."""

    low_price: Decimal | None = None
    """``stck_lwpr`` — 당일 저가 (KIS verified, not used in P2)."""

    open_price: Decimal | None = None
    """``stck_oprc`` — 시가 (KIS verified, not used in P2)."""

    iscd_stat_cls_code: str | None = None
    """``iscd_stat_cls_code`` — 종목 상태 코드 (verification required).

    KIS Excel 확인 전까지 guarded/soft path로 처리.
    None/empty/unknown → PASS (보수적 허용).
    """

    raw: dict[str, Any] = field(default_factory=dict)
    """Raw KIS response dict for debugging / future fields."""


@dataclass(slots=True, frozen=True)
class LiquidityFilterResult:
    """Result of a single liquidity filter check.

    Parameters
    ----------
    passed : bool
        True if the symbol passes all liquidity checks.
    fail_reason : str | None
        Machine-readable failure reason when ``passed=False``.
        Examples: ``"unknown_instrument"``, ``"inactive_instrument"``,
        ``"tick_size_too_large"``, ``"micro_cap"``, ``"suspended"``.
    """

    passed: bool
    fail_reason: str | None = None


@dataclass(slots=True, frozen=True)
class MomentumShadowSignal:
    """UNIV-3: 멀티데이 모멘텀 shadow 신호 (관측 전용, 선정에 미반영).

    ``_calc_market_score()``는 당일 스파이크(등락률/거래대금/신고가 근접)만
    보므로, 실제로 "새로 추세가 시작되는 종목"을 잡는지 검증하기 위해
    market_overlay가 이미 선정한 종목에 한해 일봉(``get_daily_price``) 기반
    신호를 부가로 계산해 관측한다.
    """

    symbol: str
    relative_volume_surge: float | None = None
    """당일(최근 1건) 거래량 / 최근 20거래일 평균 거래량."""

    return_5d: float | None = None
    """최근 5거래일 수익률 (종가 기준)."""

    return_20d: float | None = None
    """최근 20거래일 수익률 (종가 기준)."""

    short_term_recovering: bool | None = None
    """5일 수익률 > 0 이고 20일 수익률 >= -5% — "하락을 멈추고 돌아서는 중" 근사."""


@dataclass(slots=True, frozen=True)
class MarketOverlayDiagnostics:
    """Operational diagnostics for market-driven overlay composition."""

    enabled: bool
    skipped_reason: str | None = None
    seed_pool_source: str | None = None
    seed_pool_count: int = 0
    effective_pre_pool_size: int = 0
    pre_pool_candidate_count: int = 0
    quotes_requested_count: int = 0
    quotes_received_count: int = 0
    filtered_out_count: int = 0
    scored_candidate_count: int = 0
    added_count: int = 0
    quote_success_rate: float | None = None
    filter_pass_rate: float | None = None
    scored_capture_rate: float | None = None
    overlay_capture_rate: float | None = None

    # ── UNIV-3 shadow: F5 pre-market fallback (2026-07-12) ──────────────────
    # 당일 누적거래대금(acml_tr_pbmn)이 미형성(장 시작 전 freeze materialize)
    # 상태라 F5에서 전량 탈락했을 때, 전일 일봉(종가×거래량) 기반 추정
    # 거래대금으로 "F5를 통과했을 후보"를 관측만 한다 — 아직 실제 선정에는
    # 반영하지 않는다(shadow-first 원칙, UNIV-1-fix 조사 결과 통합).
    shadow_fallback_evaluated: bool = False
    shadow_fallback_evaluated_count: int = 0
    shadow_fallback_pass_count: int = 0
    shadow_fallback_top_symbols: tuple[str, ...] = ()

    # ── UNIV-3 shadow: 멀티데이 모멘텀 신호 (2026-07-12) ────────────────────
    # market_overlay가 실제로 선정한 종목(top_n)에 한해서만 부가로 계산한다
    # (rate budget 보호 — pre-pool 전체가 아니라 편입된 소수만). 선정 결과에는
    # 영향을 주지 않는 순수 관측용 필드다.
    momentum_shadow_evaluated: bool = False
    momentum_shadow_signals: tuple[MomentumShadowSignal, ...] = ()


# ── Default fallback ────────────────────────────────────────────────────────

FALLBACK_ACCOUNT_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")
"""Fallback account UUID used when no account is resolvable."""
