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
    overlay_capture_rate: float | None = None


# ── Default fallback ────────────────────────────────────────────────────────

FALLBACK_ACCOUNT_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")
"""Fallback account UUID used when no account is resolvable."""
