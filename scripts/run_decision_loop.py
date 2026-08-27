#!/usr/bin/env python3
"""Decision loop — 반복 운영 전용.

``run_orchestrator_once.py``는 단발 실행을 유지하고,
이 스크립트가 **연속 실행(continuous loop)** 을 담당한다.

기존 ``verify_decision_loop.py``는 **검증(verification)** 전용이며,
이 스크립트는 **운영(operations)** 전용이다.

역할 분리
---------
* ``run_snapshot_sync_loop.py`` — position/cash 데이터 최신성 유지 (300s)
* ``run_post_submit_sync_loop.py`` — 미체결/부분체결 주문 상태 Broker 수렴 (30s)
* ``run_decision_loop.py`` — AI Decision → Submit 반복 실행 (300s)

Usage
-----
.. code-block:: bash

    # 기본 실행 (5분 간격, 무한 반복, submit 모드)
    python3 -m scripts.run_decision_loop

    # 1회 실행 후 종료
    python3 -m scripts.run_decision_loop --count 1

    # Dry-run (assemble + sizing only, submit 없음)
    python3 -m scripts.run_decision_loop --count 1 --dry-run

    # 60초 간격, 5회, JSON 출력
    python3 -m scripts.run_decision_loop --interval 60 --count 5 --output json

    # 명시적 submit 모드 (기본값)
    python3 -m scripts.run_decision_loop --submit --count 1

환경 변수
---------
* ``PAPER_DECISION_LOOP_INTERVAL_SECONDS`` — 기본 interval (기본 300)
* ``TRADING_UNIVERSE_SYMBOLS`` — comma-separated symbol list (예: 005930,030200:KRX)
* ``KIS_SNAPSHOT_STALE_THRESHOLD_SECONDS`` — snapshot staleness 임계값 (기본 900)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, NoReturn
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
# Lazy import for python-dotenv (optional, for local dev)
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.enums import OrderSide, OrderType
from agent_trading.domain.entities import (
    ExecutionAttemptEntity,
    ExternalEventEntity,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import (
    CoordinatorError,
    ExternalEventRepository,
    SnapshotSyncHealthSummary,
)
from agent_trading.repositories.filters import AccountLookup
from agent_trading.runtime.bootstrap import (
    _build_kis_live_quote_client,
    postgres_runtime,
)
from agent_trading.services.common_types import PhaseTraceEntry, SubmitResult
from agent_trading.services.decision_agent_runner import complete_fdc_actual_dispatch
from agent_trading.services.core_risk_off_topk_projection import (
    project_core_risk_off_topk_exceptions,
)
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.execution_service import ExecutionService
from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator
from agent_trading.services.guardrail_audit import (
    persist_validation_result,
)
from agent_trading.services.held_position_policy import (
    is_held_position_sell_path,
)
from agent_trading.services.pre_ai_gate import (
    DEFAULT_PRE_AI_BUY_MIN_ORDERABLE_AMOUNT,
    evaluate_pre_ai_skip_reason,
    evaluate_pre_ai_validation_result,
)
from agent_trading.services.submit_lane_gate import (
    evaluate_symbol_submit_lane,
)
from agent_trading.services.sizing_engine import calculate_sizing
from agent_trading.services.translation import (
    build_submit_order_request_from_decision,
)
from agent_trading.services.universe_freeze_dedupe import (
    dedupe_universe_symbols_by_symbol_market,
)
from agent_trading.services.universe_selection import UniverseSelectionService
from agent_trading.services.universe_selection_types import (
    CORE_RANKING_MODE_SIGNAL_SCORE,
    CompositionContext,
    FALLBACK_ACCOUNT_ID,
)
from agent_trading.services.validators import (
    ValidationResult,
    build_validation_context,
)

# Lazy import for KISRestClient (only when KIS credentials are configured)
try:
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
    _HAS_KIS = True
except ImportError:
    KISRestClient = None  # type: ignore[assignment,misc]
    _HAS_KIS = False

# ── Seed constants (reused from run_orchestrator_once.py) ───────────────────
try:
    from scripts.run_orchestrator_once import (
        ACCOUNT_ALIAS,
        CLIENT_ID,
        STRATEGY_ID,
        SYMBOL,
        MARKET,
        _resolve_smoke_price,
        _seed_if_empty,
    )
except ModuleNotFoundError:
    from run_orchestrator_once import (
        ACCOUNT_ALIAS,
        CLIENT_ID,
        STRATEGY_ID,
        SYMBOL,
        MARKET,
        _resolve_smoke_price,
        _seed_if_empty,
    )

# ── Price resolution ──────────────────────────────────────────────────────────

_DEFAULT_SAFE_PRICE = Decimal("50000")
"""Ultimate fallback price when both live quote and KIS_SMOKE_PRICE are unavailable."""

PRE_AI_BUY_MIN_ORDERABLE_AMOUNT = DEFAULT_PRE_AI_BUY_MIN_ORDERABLE_AMOUNT
"""Skip BUY-side AI evaluation when verified orderable cash is too small.

Aligned with the sizing engine's 신규 포지션 최소 진입 금액(500,000원) so
that obviously non-actionable BUY candidates are filtered before any LLM call.
"""
async def _evaluate_pre_ai_skip_reason(
    repos: RepositoryContainer,
    *,
    account_alias: str,
    symbol: str,
    market: str,
    source_type: str,
    remaining_general_buy_budget: int | None = None,
    db_conn: Any | None = None,
    now_utc: datetime | None = None,
) -> tuple[str | None, dict[str, str | None]]:
    """Compatibility wrapper around shared deterministic pre-AI gate logic."""
    return await evaluate_pre_ai_skip_reason(
        repos,
        account_alias=account_alias,
        symbol=symbol,
        market=market,
        source_type=source_type,
        remaining_general_buy_budget=remaining_general_buy_budget,
        db_conn=db_conn,
        now_utc=now_utc,
        min_orderable_amount=PRE_AI_BUY_MIN_ORDERABLE_AMOUNT,
    )


async def _evaluate_pre_ai_validation_result(
    repos: RepositoryContainer,
    *,
    account_alias: str,
    symbol: str,
    market: str,
    source_type: str,
    remaining_general_buy_budget: int | None = None,
    db_conn: Any | None = None,
    now_utc: datetime | None = None,
) -> tuple[ValidationResult | None, dict[str, str | None]]:
    """Shared deterministic pre-AI validator wrapper."""
    return await evaluate_pre_ai_validation_result(
        repos,
        account_alias=account_alias,
        symbol=symbol,
        market=market,
        source_type=source_type,
        remaining_general_buy_budget=remaining_general_buy_budget,
        db_conn=db_conn,
        now_utc=now_utc,
        min_orderable_amount=PRE_AI_BUY_MIN_ORDERABLE_AMOUNT,
    )


async def _resolve_symbol_price(
    symbol: str,
    market: str,
    broker: BrokerAdapter | None,
) -> Decimal:
    """Resolve a per-symbol order price from live broker quote.

    Priority
    --------
    1. ``broker.get_quote(symbol, market).last`` — live quote current price.
    2. ``KIS_SMOKE_PRICE`` env var — smoke-test fallback (legacy).
    3. ``Decimal("50000")`` — safe default when nothing else works.

    Always logs the resolved price and its source for observability.
    """
    # ── Priority 1: Live broker quote ────────────────────────────────────
    if broker is not None and hasattr(broker, "get_quote"):
        try:
            quote = await broker.get_quote(symbol, market)
            if quote is not None and quote.last is not None and quote.last > 0:
                logger.info(
                    "Resolved price symbol=%s price=%s source=live_quote",
                    symbol,
                    quote.last,
                )
                return quote.last
            logger.warning(
                "Quote for %s returned invalid last=%s, falling back.",
                symbol,
                quote.last,
            )
        except Exception as exc:
            logger.warning(
                "Quote fetch failed symbol=%s error=%s, falling back.",
                symbol,
                exc,
            )
    else:
        logger.debug(
            "No broker adapter available for symbol=%s, using fallback price.",
            symbol,
        )

    # ── Priority 2: KIS_SMOKE_PRICE env var (legacy fallback) ────────────
    raw = os.environ.get("KIS_SMOKE_PRICE")
    if raw is not None:
        try:
            price = Decimal(raw)
            logger.info(
                "Resolved price symbol=%s price=%s source=KIS_SMOKE_PRICE(fallback)",
                symbol,
                price,
            )
            return price
        except (InvalidOperation, ValueError):
            logger.warning(
                "Invalid KIS_SMOKE_PRICE=%r for symbol=%s, falling back to default.",
                raw,
                symbol,
            )

    # ── Priority 3: Safe default ─────────────────────────────────────────
    logger.warning(
        "No price source available for symbol=%s, using default price=%s",
        symbol,
        _DEFAULT_SAFE_PRICE,
    )
    return _DEFAULT_SAFE_PRICE


def _resolve_order_type_and_price(
    *,
    side: str,
    decision_type: str | None = None,
    default_price: Decimal | None = None,
) -> tuple[OrderType, Decimal | None]:
    """의사결정 유형과 매매방향에 따라 execution 정책 결정.

    초기 요청은 ``MARKET``으로 시작한다.
    다만 실제 submit 직전에는 ``ExecutionService``가
    저유동성 BUY에 대해 ``LIMIT`` 강제 또는 submit 차단을
    추가로 적용할 수 있다.
    ``side`` / ``decision_type`` / ``default_price`` 파라미터는
    향후 시장성 지정가 등 확장에 대비해 预留(reserved)해 둠.
    """
    _ = side, decision_type, default_price  # 향후 확장 대비 预留
    return OrderType.MARKET, None


logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_EVENT_LOOKBACK_HOURS: int = 24
"""Event lookback window (hours).  Calendar 24h proxy — not trading-session-aware.
장 시작 직후/휴장일 경계에서는 실제 '1거래일'과 다를 수 있음.
P2.1+에서 trading calendar 기반 lookback으로 개선 필요."""
DEFAULT_TRADING_UNIVERSE_CORE_CAP = 12
DEFAULT_TRADING_UNIVERSE_MAX_CAP = 30
ENV_INTERVAL = "PAPER_DECISION_LOOP_INTERVAL_SECONDS"
ENV_TRADING_UNIVERSE = "TRADING_UNIVERSE_SYMBOLS"
ENV_MANUAL_WATCHLIST = "TRADING_UNIVERSE_MANUAL_SYMBOLS"
ENV_TRADING_UNIVERSE_CORE_CAP = "TRADING_UNIVERSE_CORE_CAP"
ENV_TRADING_UNIVERSE_MAX_CAP = "TRADING_UNIVERSE_MAX_CAP"
DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE = "decision_loop_intraday"

# D안(core signal-score 정렬)에서 snapshot을 FRESH로 볼 최대 경과 일수(KST
# 달력일). 장후 signal feature 배치는 거래일 20:10 KST에 돌므로 08:50 KST
# 유니버스 확정 시점의 최신 snapshot은 정상적으로 전 거래일 산출물(경과 1일)
# 이다. 금요일 배치 -> 월요일 확정(경과 3일)과 배치 1회 실패를 함께 흡수할
# 여유로 5일을 둔다. 초과분은 STALE 계층으로 하향되고 snapshot이 없는 종목은
# MISSING 계층(최하위)이 된다(SPPV-2.151 §139.3).
DEFAULT_CORE_SIGNAL_FRESHNESS_MAX_AGE_DAYS = 5
KST = ZoneInfo("Asia/Seoul")
_APPLY_CORE_RISK_OFF_TOPK = (
    os.environ.get("DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK", "0") == "1"
)


@dataclass(slots=True, frozen=True)
class UniverseSymbol:
    """A symbol/market pair evaluated by the decision loop.

    Attributes
    ----------
    symbol : str
        Ticker symbol (e.g. ``"005930"``).
    market : str
        Market code (e.g. ``"KRX"``).
    source_type : str
        Origin of this symbol's inclusion (``"core"``, ``"held_position"``,
        ``"event_overlay"``, ``"market_overlay"``, ``"manual"``).
        Default: ``"core"``.
    inclusion_reason : str
        Machine-readable reason for inclusion.
        Default: ``"approved_core_universe"``.
    """

    symbol: str
    market: str = MARKET
    source_type: str = "core"
    inclusion_reason: str = "approved_core_universe"
    market_segment: str | None = None
    index_memberships: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class UniverseAnchorMetadata:
    """Decision loop universe anchor metadata for audit/replay."""

    source: str
    universe_freeze_run_id: str | None = None
    freeze_purpose: str | None = None
    freeze_reused: bool = False
    business_date: str | None = None


def _current_business_date_kst() -> datetime.date:
    """현재 영업일 기준 날짜를 KST 기준으로 계산한다."""
    return datetime.now(timezone.utc).astimezone(KST).date()


async def _read_intraday_frozen_universe(
    repos: RepositoryContainer,
    *,
    freeze_purpose: str = DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
) -> tuple[UniverseSymbol, ...]:
    """최신 intraday universe freeze를 읽는다."""
    universe, _ = await _load_intraday_frozen_universe_with_anchor(
        repos,
        freeze_purpose=freeze_purpose,
    )
    return universe


async def _load_intraday_frozen_universe_with_anchor(
    repos: RepositoryContainer,
    *,
    freeze_purpose: str = DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
) -> tuple[tuple[UniverseSymbol, ...], UniverseAnchorMetadata | None]:
    """최신 intraday universe freeze와 audit anchor를 함께 읽는다."""
    latest_run = await repos.universe_freeze_runs.get_latest(
        _current_business_date_kst(),
        freeze_purpose,
    )
    if latest_run is None:
        return (), None
    items = await repos.universe_freeze_run_items.list_by_run(
        latest_run.universe_freeze_run_id
    )
    if not items:
        return (), None
    universe = tuple(
        UniverseSymbol(
            symbol=item.symbol,
            market=item.market_code,
            source_type=item.source_type,
            inclusion_reason=item.inclusion_reason,
        )
        for item in items
    )
    deduped_universe, skipped_duplicates = dedupe_universe_symbols_by_symbol_market(
        universe
    )
    if skipped_duplicates > 0:
        logger.warning(
            "Trading universe freeze duplicate rows skipped: count=%d "
            "(freeze_run_id=%s, freeze_purpose=%s, business_date=%s)",
            skipped_duplicates,
            latest_run.universe_freeze_run_id,
            latest_run.freeze_purpose,
            latest_run.business_date.isoformat(),
        )
    logger.info(
        "Trading universe from intraday freeze: %d symbols loaded "
        "(freeze_run_id=%s, freeze_purpose=%s, business_date=%s).",
        len(deduped_universe),
        latest_run.universe_freeze_run_id,
        latest_run.freeze_purpose,
        latest_run.business_date.isoformat(),
    )
    return (
        deduped_universe,
        UniverseAnchorMetadata(
            source="intraday_freeze",
            universe_freeze_run_id=str(latest_run.universe_freeze_run_id),
            freeze_purpose=latest_run.freeze_purpose,
            freeze_reused=True,
            business_date=latest_run.business_date.isoformat(),
        ),
    )

# ── Signal handling ─────────────────────────────────────────────────────────

_shutdown_event = asyncio.Event()


def _handle_signal() -> None:
    """SIGTERM/SIGINT handler — cancel all tasks and exit."""
    logger.warning("Received shutdown signal — cancelling all pending tasks")
    _shutdown_event.set()
    # Cancel all asyncio tasks to unblock httpx I/O waits
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


def _install_signal_handlers() -> None:
    """Install signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            signal.signal(sig, lambda s, f: _handle_signal())


# ── Config helpers ──────────────────────────────────────────────────────────


def _read_interval() -> int:
    """Read the decision loop interval from the environment (seconds)."""
    raw = os.getenv(ENV_INTERVAL)
    if raw is None:
        return DEFAULT_INTERVAL_SECONDS
    try:
        val = int(raw)
        if val < 5:
            logger.warning(
                "Interval %d is too short (< 5s), using %d instead.",
                val,
                DEFAULT_INTERVAL_SECONDS,
            )
            return DEFAULT_INTERVAL_SECONDS
        return val
    except (ValueError, TypeError):
        logger.warning(
            "Invalid %s=%r, using default %d.",
            ENV_INTERVAL,
            raw,
            DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS


def _parse_universe_symbols(raw: str | None) -> tuple[UniverseSymbol, ...]:
    """Parse a comma-separated trading universe.

    Supported item formats:
    - ``005930`` → ``005930:KRX``
    - ``005930:KRX`` → explicit symbol/market
    - ``005930.KRX`` → explicit symbol/market
    """
    if raw is None or not raw.strip():
        return (UniverseSymbol(symbol=SYMBOL, market=MARKET),)

    parsed: list[UniverseSymbol] = []
    seen: set[tuple[str, str]] = set()
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue

        if ":" in token:
            symbol, market = token.split(":", 1)
        elif "." in token:
            symbol, market = token.split(".", 1)
        else:
            symbol, market = token, MARKET

        symbol = symbol.strip().upper()
        market = (market.strip().upper() or MARKET)
        if not symbol:
            continue

        key = (symbol, market)
        if key not in seen:
            parsed.append(UniverseSymbol(symbol=symbol, market=market))
            seen.add(key)

    if not parsed:
        logger.warning(
            "Invalid %s=%r, falling back to %s:%s",
            ENV_TRADING_UNIVERSE,
            raw,
            SYMBOL,
            MARKET,
        )
        return (UniverseSymbol(symbol=SYMBOL, market=MARKET),)
    return tuple(parsed)


def _parse_manual_watchlist_symbols(raw: str | None) -> tuple[tuple[str, str], ...]:
    """Parse operator-supplied manual watchlist symbols.

    Supported item formats:
    - ``005930`` → ``("005930", "KRX")``
    - ``005930:KRX`` → explicit symbol/market
    - ``005930.KRX`` → explicit symbol/market
    """
    if raw is None or not raw.strip():
        return ()

    parsed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue

        if ":" in token:
            symbol, market = token.split(":", 1)
        elif "." in token:
            symbol, market = token.split(".", 1)
        else:
            symbol, market = token, MARKET

        symbol = symbol.strip().upper()
        market = (market.strip().upper() or MARKET)
        if not symbol:
            continue

        key = (symbol, market)
        if key not in seen:
            parsed.append(key)
            seen.add(key)
    return tuple(parsed)


async def _read_trading_universe(
    *,
    max_cap: int | None = None,
    core_cap: int | None = None,
    market_overlay_cap: int | None = None,
    pre_pool_size: int | None = None,
    exclude_held_from_cap: bool | None = None,
    disable_market_overlay_live: bool = False,
) -> tuple[UniverseSymbol, ...]:
    """Read the trading universe with fallback chain.

    Priority
    --------
    1. ``TRADING_UNIVERSE_SYMBOLS`` env var (explicit override).
    2. latest intraday universe freeze (`decision_loop_intraday`).
    3. ``UniverseSelectionService.compose()`` — 4-source composition with
       Liquidity Filter, priority sort, and daily cap.
    4. Hardcoded fallback: ``UniverseSymbol(symbol=SYMBOL, market=MARKET)`` (005930/KRX).

    The env var takes precedence so that operators can override the universe
    without modifying the database.  When the env var is not set, the
    ``UniverseSelectionService`` is used.  If the service is unavailable or
    returns no symbols, the single-symbol 005930 fallback is used.
    """
    universe, _ = await _load_trading_universe_with_anchor(
        max_cap=max_cap,
        core_cap=core_cap,
        market_overlay_cap=market_overlay_cap,
        pre_pool_size=pre_pool_size,
        exclude_held_from_cap=exclude_held_from_cap,
        disable_market_overlay_live=disable_market_overlay_live,
    )
    return universe


async def _load_trading_universe_with_anchor(
    *,
    max_cap: int | None = None,
    core_cap: int | None = None,
    market_overlay_cap: int | None = None,
    pre_pool_size: int | None = None,
    exclude_held_from_cap: bool | None = None,
    disable_market_overlay_live: bool = False,
) -> tuple[tuple[UniverseSymbol, ...], UniverseAnchorMetadata]:
    """Read trading universe plus audit anchor metadata."""
    # Priority 1: explicit env var override
    raw = os.getenv(ENV_TRADING_UNIVERSE)
    if raw is not None and raw.strip():
        return (
            _parse_universe_symbols(raw),
            UniverseAnchorMetadata(source="env_override"),
        )

    # Priority 2: latest intraday freeze, then live compose
    try:
        resolved_core_cap = (
            core_cap
            if core_cap is not None
            else int(
                os.getenv(
                    ENV_TRADING_UNIVERSE_CORE_CAP,
                    str(DEFAULT_TRADING_UNIVERSE_CORE_CAP),
                )
            )
        )
        resolved_max_cap = (
            max_cap
            if max_cap is not None
            else int(
                os.getenv(
                    ENV_TRADING_UNIVERSE_MAX_CAP,
                    str(DEFAULT_TRADING_UNIVERSE_MAX_CAP),
                )
            )
        )
        async with postgres_runtime(run_migrations=False) as runtime:
            repos: RepositoryContainer = runtime["repositories"]

            frozen_universe, frozen_anchor = await _load_intraday_frozen_universe_with_anchor(
                repos
            )
            if frozen_universe:
                return frozen_universe, (
                    frozen_anchor
                    or UniverseAnchorMetadata(source="intraday_freeze")
                )

            # Create KIS quote client if available (P2 market overlay)
            kis_client: KISRestClient | None = None
            if _HAS_KIS and not disable_market_overlay_live:
                try:
                    from agent_trading.config.settings import AppSettings
                    from agent_trading.brokers.rate_limit import build_kis_budget_manager

                    settings = AppSettings()
                    kis_client = _build_kis_live_quote_client(settings)
                    if kis_client is None:
                        budget_manager = build_kis_budget_manager(
                            kis_env=settings.kis_env,
                            real_rest_rps=settings.kis_real_rest_rps,
                            paper_rest_rps=settings.kis_paper_rest_rps,
                            shared_budget_file=settings.kis_shared_budget_file,
                        )
                        kis_client = KISRestClient(
                            api_key=settings.kis_api_key,
                            api_secret=settings.kis_api_secret,
                            account_number=settings.kis_account_number,
                            account_product_code=settings.kis_account_product_code,
                            env=settings.kis_env,
                            base_url=settings.kis_base_url,
                            budget_manager=budget_manager,
                            dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
                            dev_token_cache_path=settings.kis_dev_token_cache_path,
                            approval_cache_enabled=settings.kis_approval_key_cache_enabled,
                            approval_cache_path=settings.kis_approval_key_cache_path,
                        )
                except Exception as exc:
                    logger.warning(
                        "KIS client init failed — market_overlay disabled "
                        "(source=_read_trading_universe, error=%s: %s).",
                        type(exc).__name__,
                        exc,
                    )
            elif disable_market_overlay_live:
                logger.info(
                    "Trading universe compose: live market_overlay disabled "
                    "(source=_read_trading_universe)."
                )

            selector = UniverseSelectionService(
                repos,
                kis_client=kis_client,
            )

            # Resolve account ID for held-position lookup
            account_id: UUID = FALLBACK_ACCOUNT_ID
            try:
                account = await repos.accounts.find_one(
                    AccountLookup(account_alias=ACCOUNT_ALIAS)
                )
                if account is not None:
                    account_id = account.account_id
            except TypeError as e:
                logger.error("AccountLookup field name mismatch: %s", e)
                # TypeError는 복구 불가능한 프로그래밍 오류 → 재발생
                raise
            except Exception:
                logger.warning("Account lookup failed — using fallback account ID.")

            ctx = CompositionContext(
                account_id=account_id,
                since=datetime.now(timezone.utc) - timedelta(hours=DEFAULT_EVENT_LOOKBACK_HOURS),
                # P2 minimum: market overlay cap and pre-pool size
                max_cap=resolved_max_cap,
                core_cap=resolved_core_cap,
                exclude_held_from_cap=(
                    exclude_held_from_cap
                    if exclude_held_from_cap is not None
                    else True
                ),
                market_overlay_cap=(
                    market_overlay_cap if market_overlay_cap is not None else 5
                ),
                pre_pool_size=pre_pool_size if pre_pool_size is not None else 50,
                manual_symbols=_parse_manual_watchlist_symbols(
                    os.getenv(ENV_MANUAL_WATCHLIST)
                ),
                # D안(SPPV-2.145): core 후보를 종목코드 사전순이 아니라 최신
                # snapshot overall_score 기준으로 자른다. decision loop 경로만
                # 명시적으로 opt-in하므로, 같은 compose()를 쓰는 signal feature
                # snapshot 입력 배치는 기본값(사전순)으로 남는다(§132.3).
                core_ranking_mode=CORE_RANKING_MODE_SIGNAL_SCORE,
                # S5 freshness guard(SPPV-2.151): 생성 모집단을 소비 모집단에
                # 맞춰 넓혔더라도, 배치 부분 실패·신규 상장·상장폐지 등으로
                # 특정 종목 snapshot이 누락되면 오래된 점수가 정렬 상위를
                # 차지할 수 있다. 그 경우를 STALE/MISSING 계층으로 하향시켜
                # 막는 안전망이다(정렬 실패로 전체를 막지 않는다).
                core_signal_freshness_max_age_days=(
                    DEFAULT_CORE_SIGNAL_FRESHNESS_MAX_AGE_DAYS
                ),
            )
            selected = await selector.compose(ctx)

            if selected:
                universe = tuple(
                    UniverseSymbol(
                        symbol=s.symbol,
                        market=s.market,
                        source_type=s.source_type.value,
                        inclusion_reason=s.inclusion_reason,
                        market_segment=s.market_segment,
                        index_memberships=s.index_memberships,
                    )
                    for s in selected
                )
                # source_type 분포 로깅 — held_position 포함 여부 추적
                source_counts: dict[str, int] = {}
                for sym in universe:
                    source_counts[sym.source_type] = source_counts.get(sym.source_type, 0) + 1
                logger.info(
                    "Trading universe from UniverseSelectionService: "
                    "%d symbols loaded (cap=%d, core_cap=%s).  "
                    "source_type distribution: %s",
                    len(universe),
                    ctx.max_cap,
                    ctx.core_cap,
                    source_counts,
                )
                return universe, UniverseAnchorMetadata(
                    source="live_compose",
                    freeze_purpose=DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
                    freeze_reused=False,
                    business_date=_current_business_date_kst().isoformat(),
                )

            logger.info(
                "UniverseSelectionService returned 0 symbols — "
                "falling back to %s:%s.",
                SYMBOL,
                MARKET,
            )
    except Exception as exc:
        logger.warning(
            "UniverseSelectionService failed (%s: %s) — "
            "falling back to %s:%s.",
            type(exc).__name__,
            exc,
            SYMBOL,
            MARKET,
        )

    # Priority 4: hardcoded fallback (single smoke symbol)
    return (
        (UniverseSymbol(symbol=SYMBOL, market=MARKET),),
        UniverseAnchorMetadata(source="hardcoded_fallback"),
    )


# ── Pre-check: snapshot sync health ────────────────────────────────────────
# NOTE: This is a lightweight informational pre-check only.
# The actual guard is in DecisionOrchestratorService.assemble_and_submit()
# Phase 4c — we do NOT duplicate the guard policy here.


def _serialize_precheck(health: SnapshotSyncHealthSummary) -> dict[str, object]:
    """Serialize a ``SnapshotSyncHealthSummary`` for cycle summary output."""
    return {
        "health_status": "stale" if health.is_stale else "ok",
        "last_successful_run_at": (
            health.last_successful_run_at.isoformat()
            if health.last_successful_run_at
            else None
        ),
        "last_run_status": health.last_status,
        "consecutive_failures": health.consecutive_failures,
        "stale_threshold_seconds": health.stale_threshold_seconds,
    }


async def _run_precheck(
    repos: RepositoryContainer,
    stale_threshold: int = 900,
) -> dict[str, object] | None:
    """Lightweight pre-check: snapshot sync health summary.

    Returns a dict for the cycle summary, or ``None`` if the check is
    unavailable (e.g. the repository does not support it).

    Does NOT block execution — the real stale-snapshot guard is in
    Phase 4c of ``assemble_and_submit()``.
    """
    try:
        health = await repos.snapshot_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=stale_threshold,
        )
        precheck = _serialize_precheck(health)
        if health.is_stale:
            logger.info(
                "Pre-check: snapshot sync is STALE "
                "(last_successful=%s, threshold=%ds). "
                "Phase 4c guard will block submit if stale.",
                health.last_successful_run_at,
                health.stale_threshold_seconds,
            )
        elif health.last_successful_run_at is None:
            logger.info(
                "Pre-check: snapshot sync has NO HISTORY. "
                "Phase 4c guard will block submit if no_history policy applies."
            )
        else:
            logger.info(
                "Pre-check: snapshot sync HEALTHY (last_successful=%s).",
                health.last_successful_run_at,
            )
        return precheck
    except Exception as exc:
        logger.warning("Pre-check failed: %s", exc)
        return None


# 국면 혼합도 모니터링 벤치마크 — KODEX 200(§40/SPPV-2.50~2.62와 동일 기준).
_MIXEDNESS_BENCHMARK_SYMBOL = "069500"
_MIXEDNESS_BENCHMARK_MARKET = "KRX"


async def _run_mixedness_check(
    repos: RepositoryContainer,
) -> dict[str, object] | None:
    """국면 혼합도(regime mixedness) 관측/로깅 전용 체크(SPPV-2.63).

    ``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §40/§51
    참고 — `services/regime_mixedness_monitor.py`(순수 함수, BUY/SELL
    판정과 완전히 분리)를 이용해 벤치마크(KODEX 200)의 최근 국면
    혼합도 버킷을 계산하고 로그에 남긴다.

    **이 체크는 BUY/SELL 판정에 어떤 영향도 주지 않는다** — 신규
    KIS 호출도 하지 않는다(이미 스냅샷 동기화 루프가 채워 넣은
    `signal_feature_snapshots`를 read-only로 읽을 뿐이다). 실패해도
    사이클 진행에 영향을 주지 않도록 예외를 전부 흡수한다(``_run_
    precheck``와 동일한 안전 패턴).
    """
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.regime_mixedness_monitor import (
        classify_mixedness_bucket,
        compute_mixed_score,
    )

    try:
        instrument = await repos.instruments.get_by_symbol(
            symbol=_MIXEDNESS_BENCHMARK_SYMBOL,
            market_code=_MIXEDNESS_BENCHMARK_MARKET,
        )
        if instrument is None:
            return None
        snapshots = await repos.signal_feature_snapshots.list_by_instrument(
            instrument.instrument_id,
            timeframe="1d",
            limit=60,
        )
        if len(snapshots) < 20:
            logger.info(
                "Mixedness check: 벤치마크 스냅샷 이력 부족(%d건, 20건 미만) — skip.",
                len(snapshots),
            )
            return None

        trailing_labels = [
            classify_market_regime(snapshot).regime_label for snapshot in snapshots
        ]
        mixed_score = compute_mixed_score(trailing_labels)
        if mixed_score is None:
            return None

        assessment = classify_mixedness_bucket(mixed_score)
        logger.info(
            "Mixedness check: bucket=%s mixed_score=%.4f reason_code=%s "
            "(관측 전용 — BUY/SELL 판정에 영향 없음).",
            assessment.bucket,
            assessment.mixed_score,
            assessment.reason_code,
        )
        return {
            "mixed_score": assessment.mixed_score,
            "bucket": assessment.bucket,
            "reason_code": assessment.reason_code,
        }
    except Exception as exc:
        logger.warning("Mixedness check failed (관측 전용, 사이클에는 영향 없음): %s", exc)
        return None


# ── Result serialization ────────────────────────────────────────────────────


def _serialize_cycle_result(
    cycle: int,
    result: SubmitResult | None,
    duration: float,
    *,
    symbol: str = SYMBOL,
    market: str = MARKET,
    precheck: dict[str, object] | None = None,
    dry_run: bool = False,
    error: str | None = None,
    ei_output: dict[str, object] | None = None,
    source_type: str = "core",
    dry_run_reason: str | None = None,
    universe_anchor: UniverseAnchorMetadata | None = None,
) -> dict[str, object]:
    """Serialize a single decision cycle result.

    Parameters
    ----------
    cycle:
        Cycle number (1-based).
    result:
        The ``SubmitResult`` from the orchestrator, or ``None`` on error.
    duration:
        Wall-clock duration of the cycle in seconds.
    precheck:
        Optional pre-check result (snapshot sync health summary).
    dry_run:
        Whether this cycle was a dry-run (assemble + sizing only).
    error:
        Top-level error message, if the cycle failed before producing a result.
    ei_output:
        Optional EI Agent output (event_bias, event_conflict, event_reason_codes).
    source_type:
        Source type of the universe item (core, held_position, etc.).
        scheduler-level budget 분기에서 사용된다.
    """
    now = datetime.now(timezone.utc)
    started_at = now.isoformat()
    completed_at = now.isoformat()

    # decision_type과 side는 모든 분기에서 항상 포함되어야 한다.
    # scheduler-level budget 분기(_is_held_position_sell_result)에서
    # 3중 조건(source_type + decision_type + side) 판별에 사용된다.
    decision_type: str | None = None
    side: str | None = None

    if result is not None and result.order_intent is not None:
        decision_type = result.order_intent.ai_backend_inputs.decision_type
        side = result.order_intent.ai_backend_inputs.side
        deterministic_trigger = result.order_intent.context.deterministic_trigger
        data_risk_off_exception_eligible = bool(
            getattr(deterministic_trigger, "risk_off_exception_eligible", False)
        )
    else:
        data_risk_off_exception_eligible = False

    data: dict[str, object] = {
        "cycle": cycle,
        "symbol": symbol,
        "market": market,
        "source_type": source_type,
        "risk_off_exception_eligible": data_risk_off_exception_eligible,
        "decision_type": decision_type,
        "side": side,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": max(round(duration, 3), 0.001) if duration > 0 else 0.0,
    }

    if precheck is not None:
        data["precheck"] = precheck
    if universe_anchor is not None:
        data["universe_anchor_source"] = universe_anchor.source
        data["universe_freeze_run_id"] = universe_anchor.universe_freeze_run_id
        data["freeze_purpose"] = universe_anchor.freeze_purpose
        data["freeze_reused"] = universe_anchor.freeze_reused
        data["universe_anchor"] = asdict(universe_anchor)

    if error:
        data["status"] = "ERROR"
        data["error"] = error
    elif dry_run:
        # Dry-run mode: assemble + sizing, no broker submit
        data["status"] = "DRY_RUN"
        data["dry_run_reason"] = dry_run_reason
        data["stop_reason"] = result.stop_reason if result is not None else dry_run_reason
        if result is not None and result.order_intent is not None:
            data["decision_context_id"] = (
                str(result.decision_context_id) if result.decision_context_id else None
            )
            data["trade_decision_id"] = (
                str(result.trade_decision_id) if result.trade_decision_id else None
            )
            data["order_intent_id"] = str(result.order_intent.order_intent_id)
            data["sized_quantity"] = str(result.order_intent.request.quantity)
            ai_inputs = result.order_intent.ai_backend_inputs
            data["ai_call_path"] = {
                "ei_skipped": ai_inputs.ei_skipped,
                "ar_skipped": ai_inputs.ar_skipped,
                "fdc_skipped": ai_inputs.fdc_skipped,
                "skip_reason_codes": list(ai_inputs.skip_reason_codes),
            }
            # EXE-001: phase trace
            data["phase_trace"] = [
                {"phase": pt.phase, "elapsed_ms": pt.elapsed_ms, "status": pt.status}
                for pt in result.phase_trace
            ] if result.phase_trace else []
    elif result is not None:
        data["status"] = result.status
        data["error_phase"] = result.error_phase
        data["error_message"] = result.error_message
        data["stop_reason"] = result.stop_reason
        data["decision_context_id"] = (
            str(result.decision_context_id) if result.decision_context_id else None
        )
        data["trade_decision_id"] = (
            str(result.trade_decision_id) if result.trade_decision_id else None
        )
        if result.order_intent is not None:
            data["order_intent_id"] = str(result.order_intent.order_intent_id)
            data["sized_quantity"] = str(result.order_intent.request.quantity)
            ai_inputs = result.order_intent.ai_backend_inputs
            data["ai_call_path"] = {
                "ei_skipped": ai_inputs.ei_skipped,
                "ar_skipped": ai_inputs.ar_skipped,
                "fdc_skipped": ai_inputs.fdc_skipped,
                "skip_reason_codes": list(ai_inputs.skip_reason_codes),
            }
        if result.submit_response is not None:
            data["order_request_id"] = str(result.submit_response.order_request_id)
            data["order_status"] = result.submit_response.status.value
            data["client_order_id"] = result.submit_response.client_order_id
            data["requested_quantity"] = str(result.submit_response.requested_quantity)
        # EXE-001: phase trace
        data["phase_trace"] = [
            {"phase": pt.phase, "elapsed_ms": pt.elapsed_ms, "status": pt.status}
            for pt in result.phase_trace
        ] if result.phase_trace else []
    else:
        data["status"] = "UNKNOWN"

    if ei_output is not None:
        data["ei_output"] = ei_output

    return data


def _build_trigger_assessment_from_payload(
    payload: dict[str, object] | None,
) -> DeterministicTriggerAssessment | None:
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    candidate_set = payload.get("candidate_set")
    if isinstance(candidate_set, (list, tuple)):
        normalized_candidate_set = tuple(str(item) for item in candidate_set)
    else:
        normalized_candidate_set = ()
    eligibility_reasons = payload.get("eligibility_reasons")
    if isinstance(eligibility_reasons, (list, tuple)):
        normalized_eligibility_reasons = tuple(str(item) for item in eligibility_reasons)
    else:
        normalized_eligibility_reasons = ()
    reason_codes = payload.get("reason_codes")
    if isinstance(reason_codes, (list, tuple)):
        normalized_reason_codes = tuple(str(item) for item in reason_codes)
    else:
        normalized_reason_codes = ()
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict):
        thresholds = {}
    try:
        return DeterministicTriggerAssessment(
            trigger_version=str(payload.get("trigger_version") or "deterministic_trigger_v1"),
            primary_candidate=str(payload.get("primary_candidate") or "NO_ACTION"),
            candidate_set=normalized_candidate_set,
            watch_candidate=bool(payload.get("watch_candidate")),
            buy_candidate=bool(payload.get("buy_candidate")),
            sell_candidate=bool(payload.get("sell_candidate")),
            reduce_candidate=bool(payload.get("reduce_candidate")),
            candidate_confidence=float(payload.get("candidate_confidence") or 0.0),
            entry_score=(
                float(payload["entry_score"])
                if payload.get("entry_score") is not None
                else None
            ),
            exit_score=(
                float(payload["exit_score"])
                if payload.get("exit_score") is not None
                else None
            ),
            watch_score=(
                float(payload["watch_score"])
                if payload.get("watch_score") is not None
                else None
            ),
            eligibility_passed=bool(payload.get("eligibility_passed")),
            eligibility_reasons=normalized_eligibility_reasons,
            coverage_score=(
                float(payload["coverage_score"])
                if payload.get("coverage_score") is not None
                else None
            ),
            ranking_score=(
                float(payload["ranking_score"])
                if payload.get("ranking_score") is not None
                else None
            ),
            ranking_percentile=(
                float(payload["ranking_percentile"])
                if payload.get("ranking_percentile") is not None
                else None
            ),
            ranking_bucket=(
                str(payload["ranking_bucket"])
                if payload.get("ranking_bucket") is not None
                else None
            ),
            candidate_mode=str(payload.get("candidate_mode") or "absolute_threshold_v1"),
            risk_off_exception_eligible=bool(payload.get("risk_off_exception_eligible")),
            reason_codes=normalized_reason_codes,
            thresholds=dict(thresholds),
            metadata=dict(metadata),
        )
    except (TypeError, ValueError):
        return None


async def _apply_core_risk_off_shadow_projection_for_cycle(
    cycle_results: list[dict[str, object]],
) -> None:
    trade_decision_ids: list[UUID] = []
    result_by_trade_decision_id: dict[str, dict[str, object]] = {}
    for result in cycle_results:
        raw_id = result.get("trade_decision_id")
        if raw_id is None:
            continue
        try:
            parsed = UUID(str(raw_id))
        except ValueError:
            continue
        trade_decision_ids.append(parsed)
        result_by_trade_decision_id[str(parsed)] = result

    if not trade_decision_ids:
        return

    from agent_trading.db.transaction import transaction as _db_transaction

    async with _db_transaction() as tx:
        rows = await tx.connection.fetch(
            """
            SELECT trade_decision_id, symbol, decision_json
            FROM trading.trade_decisions
            WHERE trade_decision_id = ANY($1::uuid[])
            """,
            trade_decision_ids,
        )
        assessments_by_symbol: dict[str, DeterministicTriggerAssessment] = {}
        trade_decision_id_by_symbol: dict[str, UUID] = {}
        for row in rows:
            decision_json = row["decision_json"]
            if not isinstance(decision_json, dict):
                continue
            trigger_payload = decision_json.get("deterministic_trigger")
            assessment = _build_trigger_assessment_from_payload(trigger_payload)
            if assessment is None:
                continue
            assessments_by_symbol[str(row["symbol"])] = assessment
            trade_decision_id_by_symbol[str(row["symbol"])] = row["trade_decision_id"]

        if not assessments_by_symbol:
            await tx.commit()
            return

        projected = project_core_risk_off_topk_exceptions(assessments_by_symbol)
        selected_count = 0
        candidate_count = 0
        for symbol, assessment in projected.items():
            experiment = dict((assessment.metadata or {}).get("core_risk_off_experiment") or {})
            if not experiment:
                continue
            if bool(experiment.get("shadow_topk_candidate")):
                candidate_count += 1
            if bool(experiment.get("shadow_topk_selected")):
                selected_count += 1
            trade_decision_id = trade_decision_id_by_symbol.get(symbol)
            if trade_decision_id is None:
                continue
            await tx.connection.execute(
                """
                UPDATE trading.trade_decisions
                SET decision_json = jsonb_set(
                    COALESCE(decision_json, '{}'::jsonb),
                    '{deterministic_trigger,metadata,core_risk_off_experiment}',
                    $2::jsonb,
                    true
                )
                WHERE trade_decision_id = $1
                """,
                trade_decision_id,
                json.dumps(experiment),
            )
            serialized = result_by_trade_decision_id.get(str(trade_decision_id))
            if serialized is not None:
                serialized["core_risk_off_shadow_topk_candidate"] = bool(
                    experiment.get("shadow_topk_candidate")
                )
                serialized["core_risk_off_shadow_topk_selected"] = bool(
                    experiment.get("shadow_topk_selected")
                )
                serialized["core_risk_off_shadow_rank"] = experiment.get("shadow_rank")
                serialized["core_risk_off_shadow_group_size"] = experiment.get(
                    "shadow_group_size"
                )
        await tx.commit()

    logger.info(
        "Cycle shadow projection applied: trade_decisions=%d candidates=%d selected=%d",
        len(trade_decision_ids),
        candidate_count,
        selected_count,
    )


async def _build_core_risk_off_apply_overrides_for_cycle(
    *,
    universe: tuple[UniverseSymbol, ...],
) -> dict[str, dict[str, object]]:
    """Same-cycle top-k 예외 승격 대상을 미리 계산한다."""
    if not _APPLY_CORE_RISK_OFF_TOPK:
        return {}

    from agent_trading.config.settings import AppSettings
    from agent_trading.db.transaction import transaction as _db_transaction
    from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
    from agent_trading.services.decision_orchestrator import DecisionOrchestratorService
    from agent_trading.services.regime_switch_gate import resolve_cached_trigger_status

    overrides: dict[str, dict[str, object]] = {}
    assessments_by_symbol: dict[str, DeterministicTriggerAssessment] = {}

    async with _db_transaction() as tx:
        repos = build_postgres_repositories(tx)
        settings = AppSettings()
        orchestrator = DecisionOrchestratorService(
            repos=repos,
            llm_provider=settings.llm_provider,
            provider_api_key=settings.provider_api_key or "",
            provider_base_url=settings.provider_base_url or "",
            provider_model_id=settings.provider_model_id or "",
            provider_timeout_seconds=settings.provider_timeout_seconds or 120,
            regime_switch_v1_trigger_status=resolve_cached_trigger_status(),
            regime_switch_v1_gate_override_enabled=(
                settings.regime_switch_v1_gate_override_enabled
            ),
            r3b_alpha_enabled=settings.entry_score_r3b_alpha_enabled,
            ev_gate_near_miss_override_enabled=(
                settings.ev_gate_near_miss_override_enabled
            ),
            loss_cut_shadow_enabled=settings.loss_cut_shadow_enabled,
            loss_cut_shadow_soft_threshold_pct=(
                settings.loss_cut_shadow_soft_threshold_pct
            ),
            loss_cut_shadow_hard_threshold_pct=(
                settings.loss_cut_shadow_hard_threshold_pct
            ),
            ar_shadow_bot_enabled=settings.ar_shadow_bot_enabled,
            ei_shadow_bot_enabled=settings.ei_shadow_bot_enabled,
            held_position_fdc_skip_shadow_enabled=(
                settings.held_position_fdc_skip_shadow_enabled
            ),
            held_position_reduce_skip_shadow_enabled=(
                settings.held_position_reduce_skip_shadow_enabled
            ),
            fdc_batch_queue_lifecycle_shadow_enabled=(
                settings.fdc_batch_queue_lifecycle_shadow_enabled
            ),
            fdc_actual_dispatch_enabled=settings.fdc_actual_dispatch_enabled,
        )
        for item in universe:
            if item.source_type != "core":
                continue
            order_type, price = _resolve_order_type_and_price(
                side="buy",
                decision_type=None,
                default_price=None,
            )
            request = SubmitOrderRequest(
                account_ref=ACCOUNT_ALIAS,
                client_order_id=f"prepass-{item.symbol}",
                correlation_id=f"prepass-{item.symbol}",
                strategy_id=str(STRATEGY_ID),
                symbol=item.symbol,
                market=item.market,
                side=OrderSide.BUY,
                order_type=order_type,
                quantity=Decimal("1"),
                price=price,
                metadata={
                    "source_type": item.source_type,
                    "market_segment": item.market_segment,
                    "index_memberships": list(item.index_memberships or ()),
                },
            )
            derivation = await orchestrator.derive_deterministic_trigger_for_request(
                request
            )
            if derivation.deterministic_trigger is None:
                continue
            assessments_by_symbol[item.symbol] = derivation.deterministic_trigger
        await tx.commit()

    if not assessments_by_symbol:
        return {}

    projected = project_core_risk_off_topk_exceptions(assessments_by_symbol)
    for symbol, assessment in projected.items():
        experiment = dict((assessment.metadata or {}).get("core_risk_off_experiment") or {})
        if not bool(experiment.get("shadow_topk_selected")):
            continue
        overrides[symbol] = {
            "core_risk_off_topk_v1": {
                "selected": True,
                "path": "core_risk_off_topk_v1",
                "shadow_rank": experiment.get("shadow_rank"),
                "shadow_group_size": experiment.get("shadow_group_size"),
            }
        }

    if overrides:
        logger.info(
            "Cycle authoritative core risk-off prepass selected=%d symbols=%s",
            len(overrides),
            ",".join(sorted(overrides)),
        )
    return overrides


_R3B_ALPHA_BENCHMARK_SYMBOL = "069500"
_R3B_ALPHA_BENCHMARK_MARKET = "KRX"


async def _build_r3b_alpha_percentile_overrides_for_cycle(
    repos: RepositoryContainer,
    *,
    universe: tuple[UniverseSymbol, ...],
) -> dict[str, float]:
    """cycle당 1회 entry_score R3b alpha의 candidate_percentile을
    사전 계산한다(SPPV-2.69, §54.5의 "3단계" — 이 세션에서 처음으로
    production 코드에 옮겨진 실제 precompute).

    `_build_core_risk_off_apply_overrides_for_cycle`과 동일한 구조
    (cycle당 1회 그날의 universe 전체를 순회해 dict로 사전 계산 →
    종목별로 `request.metadata`에 주입)를 따른다. 신규 알고리즘 없음
    — `services/r3b_alpha_percentile.py`(SPPV-2.67, shadow 스크립트
    로직 이식·200회 무작위 trial parity 검증 완료)를 그대로 호출할
    뿐이다.

    **`AppSettings.entry_score_r3b_alpha_enabled`(기본값 False)가
    꺼져 있으면 이 함수는 아무것도 하지 않고 빈 dict를 반환**한다 —
    비활성 상태에서 불필요한 DB 조회를 만들지 않기 위함이며, 동시에
    "기본값이면 기존 동작 100% 유지"를 보장하는 이 세션의 backward-
    compat 원칙과 일치한다.

    반환값은 ``{symbol: candidate_percentile}`` — candidate pool
    밖의 종목/신호 결측 종목은 키 자체가 없다(호출부는 `.get(symbol)`
    로 조회해 `None` fallback을 사용해야 한다).
    """
    from agent_trading.config.settings import AppSettings
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.r3b_alpha_percentile import (
        R3bAlphaInput,
        build_candidate_percentiles,
    )

    settings = AppSettings()
    if not settings.entry_score_r3b_alpha_enabled:
        return {}

    try:
        benchmark_instrument = await repos.instruments.get_by_symbol(
            symbol=_R3B_ALPHA_BENCHMARK_SYMBOL,
            market_code=_R3B_ALPHA_BENCHMARK_MARKET,
        )
        if benchmark_instrument is None:
            logger.warning(
                "R3b alpha precompute: 벤치마크(%s) instrument 조회 실패 — skip.",
                _R3B_ALPHA_BENCHMARK_SYMBOL,
            )
            return {}
        benchmark_snapshot = await repos.signal_feature_snapshots.get_latest_by_instrument(
            benchmark_instrument.instrument_id,
        )
        market_common_label = (
            classify_market_regime(benchmark_snapshot).regime_label
            if benchmark_snapshot is not None
            else None
        )
        if market_common_label is None:
            logger.info(
                "R3b alpha precompute: 벤치마크 국면 라벨 산출 실패(스냅샷 없음) — skip."
            )
            return {}

        items: list[R3bAlphaInput] = []
        for symbol_entry in universe:
            try:
                instrument = await repos.instruments.get_by_symbol(
                    symbol=symbol_entry.symbol,
                    market_code=symbol_entry.market,
                )
                if instrument is None:
                    continue
                snapshot = await repos.signal_feature_snapshots.get_latest_by_instrument(
                    instrument.instrument_id,
                )
                if snapshot is None:
                    continue
            except Exception:
                continue
            items.append(
                R3bAlphaInput(
                    symbol=symbol_entry.symbol,
                    market_common_label=market_common_label,
                    return_1m_pct=snapshot.return_1m_pct,
                    return_3m_pct=snapshot.return_3m_pct,
                    volatility_20d_pct=snapshot.volatility_20d_pct,
                )
            )

        percentiles = build_candidate_percentiles(items)
        if percentiles:
            logger.info(
                "R3b alpha precompute: market_common_label=%s candidates=%d symbols=%s",
                market_common_label,
                len(percentiles),
                ",".join(sorted(percentiles)),
            )
        return percentiles
    except Exception:
        logger.warning(
            "R3b alpha precompute failed(사이클에는 영향 없음 — percentile 미주입)",
            exc_info=True,
        )
        return {}


async def _record_pre_ai_guardrail_evaluation(
    repos: RepositoryContainer,
    *,
    account_alias: str,
    symbol: str,
    market: str,
    source_type: str,
    validation_result: ValidationResult,
    decision_cycle_id: str | None = None,
) -> None:
    """Persist a deterministic pre-AI gate block as a guardrail evaluation.

    ``decision_cycle_id``(Stage A-1b, 2026-08-20)는 관측성 전용 cycle
    식별자 — 판정 로직에는 관여하지 않는다.
    """
    account_id = None
    try:
        account = await repos.accounts.find_one(AccountLookup(account_alias=account_alias))
        account_id = account.account_id if account is not None else None
    except Exception:
        logger.warning(
            "Pre-AI guardrail account lookup failed while recording evaluation: "
            "account_alias=%s symbol=%s",
            account_alias,
            symbol,
            exc_info=True,
        )

    await persist_validation_result(
        repos,
        validation_context=build_validation_context(
            account_id=account_id,
            symbol=symbol,
            market=market,
            source_type=source_type,
            decision_cycle_id=decision_cycle_id,
            metadata={"account_alias": account_alias, "gate_phase": "pre_ai_gate"},
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version=validation_result.rule_set_version,
            blocking_rule_codes=list(validation_result.blocking_rule_codes),
            rule_results=dict(validation_result.rule_results),
            stop_reason=validation_result.stop_reason,
            message=validation_result.message,
        ),
    )


async def _record_scheduler_guardrail_evaluation(
    repos: RepositoryContainer,
    *,
    account_alias: str,
    symbol: str,
    market: str,
    source_type: str,
    validation_result: ValidationResult,
    trade_decision_id: object | None,
    decision_context_id: object | None,
) -> None:
    """Persist a scheduler gate dry-run decision as a guardrail evaluation."""
    account_id = None
    try:
        account = await repos.accounts.find_one(AccountLookup(account_alias=account_alias))
        account_id = account.account_id if account is not None else None
    except Exception:
        logger.warning(
            "Scheduler guardrail account lookup failed while recording evaluation: "
            "account_alias=%s symbol=%s",
            account_alias,
            symbol,
            exc_info=True,
        )

    await persist_validation_result(
        repos,
        validation_context=build_validation_context(
            decision_context_id=decision_context_id,
            trade_decision_id=trade_decision_id,
            account_id=account_id,
            symbol=symbol,
            market=market,
            source_type=source_type,
            metadata={
                "account_alias": account_alias,
                "gate_phase": "scheduler_gate",
            },
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version=validation_result.rule_set_version,
            blocking_rule_codes=list(validation_result.blocking_rule_codes),
            rule_results=dict(validation_result.rule_results),
            stop_reason=validation_result.stop_reason,
            message=validation_result.message,
        ),
    )


async def _record_pass2_general_lane_drop_guardrail_evaluation(
    candidate: dict[str, object],
    *,
    cycle_count: int,
    reason: str,
    decision_cycle_id: str | None = None,
) -> None:
    """Pass 2(Pass 1.5 dedupe 포함)에서 탈락한 general lane 후보를
    ``guardrail_evaluations``에 기록한다(Stage A-1a, 2026-08-20).

    ``_record_pre_ai_guardrail_evaluation()``(gate_phase=``pre_ai_gate``)
    과 population 계약(symbol/market/source_type/stop_reason/rule_results)
    은 최대한 맞추되, ``gate_phase=pass2_general_lane_drop``으로 명시적
    으로 구분한다 — 이 스킵은 이미 ``assemble()``(=AI 판단)이 끝난 뒤
    Pass 2에서 예산 소진/같은 cycle 내 symbol 중복 사유로 제출을
    포기한 것이라, AI 호출 **전**에 걸러지는 pre_ai_gate 스킵과는
    의미가 다르다 — 같은 경로인 척 섞지 않는다.

    판정 로직에는 전혀 관여하지 않는다(순수 기록 추가) — 이 함수 호출이
    실패해도 Pass 2 진행에는 영향을 주지 않는다(best-effort).
    """
    from agent_trading.db.transaction import transaction as _db_transaction
    from agent_trading.repositories.postgres.bootstrap import (
        build_postgres_repositories,
    )

    symbol = str(candidate.get("symbol", ""))
    market = str(candidate.get("market", ""))
    source_type = str(candidate.get("source_type", ""))
    final_trade_score = candidate.get("final_trade_score")
    try:
        async with _db_transaction() as tx:
            repos: RepositoryContainer = build_postgres_repositories(tx)
            account_id = None
            try:
                account = await repos.accounts.find_one(
                    AccountLookup(account_alias=ACCOUNT_ALIAS)
                )
                account_id = account.account_id if account is not None else None
            except Exception:
                account_id = None

            await persist_validation_result(
                repos,
                validation_context=build_validation_context(
                    decision_context_id=candidate.get("decision_context_id"),
                    trade_decision_id=candidate.get("trade_decision_id"),
                    account_id=account_id,
                    symbol=symbol,
                    market=market,
                    source_type=source_type,
                    decision_cycle_id=decision_cycle_id,
                    metadata={
                        "account_alias": ACCOUNT_ALIAS,
                        "gate_phase": "pass2_general_lane_drop",
                        "cycle": cycle_count,
                    },
                ),
                validation_result=ValidationResult.blocked(
                    rule_set_version="pass2_general_lane_drop_v1",
                    blocking_rule_codes=[reason],
                    rule_results={
                        "gate_phase": "pass2_general_lane_drop",
                        "cycle": cycle_count,
                        "final_trade_score": (
                            str(final_trade_score)
                            if final_trade_score is not None
                            else None
                        ),
                    },
                    stop_reason=reason,
                ),
            )
            await tx.commit()
    except Exception:
        logger.warning(
            "Failed to record Pass2 general lane drop guardrail evaluation: "
            "symbol=%s reason=%s",
            symbol, reason, exc_info=True,
        )


def _build_aggregate_summary(
    results: list[dict[str, object]],
    total_duration: float,
    *,
    universe: tuple[UniverseSymbol, ...] = (),
    universe_anchor: UniverseAnchorMetadata | None = None,
) -> dict[str, object]:
    """Build an aggregate summary from all cycle results."""
    total = len(results)
    success = sum(
        1
        for r in results
        if r.get("status") in ("SUBMITTED", "DRY_RUN", "SKIPPED")
    )
    skipped = sum(1 for r in results if r.get("status") == "SKIPPED")
    errors = sum(1 for r in results if r.get("status") in ("ERROR", "UNKNOWN"))
    source_counts = Counter(item.source_type for item in universe)
    processed_source_counts = Counter(
        str(r.get("source_type", "unknown") or "unknown")
        for r in results
    )
    ai_call_path_entries = [
        payload
        for payload in (r.get("ai_call_path") for r in results)
        if isinstance(payload, dict)
    ]
    skip_reason_counts: Counter[str] = Counter()
    for payload in ai_call_path_entries:
        raw_codes = payload.get("skip_reason_codes")
        if isinstance(raw_codes, (list, tuple)):
            for code in raw_codes:
                if code:
                    skip_reason_counts[str(code)] += 1
    risk_off_exception_entries = [
        r for r in results if bool(r.get("risk_off_exception_eligible"))
    ]
    risk_off_exception_ai_pass_count = 0
    risk_off_exception_submit_count = 0
    for row in risk_off_exception_entries:
        payload = row.get("ai_call_path")
        if isinstance(payload, dict):
            all_skipped = (
                bool(payload.get("ei_skipped"))
                and bool(payload.get("ar_skipped"))
                and bool(payload.get("fdc_skipped"))
            )
            if not all_skipped:
                risk_off_exception_ai_pass_count += 1
        if str(row.get("status")) == "SUBMITTED":
            risk_off_exception_submit_count += 1

    metrics: dict[str, object] = {
        "universe_symbol_count": len(universe),
        "processed_symbol_count": total,
        "held_position_count": source_counts.get("held_position", 0),
        "held_position_processed_count": processed_source_counts.get("held_position", 0),
        "universe_source_counts": dict(source_counts),
        "processed_source_counts": dict(processed_source_counts),
        "risk_off_exception_path": {
            "risk_off_exception_eligible_count": len(risk_off_exception_entries),
            "risk_off_exception_ai_pass_count": risk_off_exception_ai_pass_count,
            "risk_off_exception_submit_count": risk_off_exception_submit_count,
        },
        "ai_call_path": {
            "tracked_count": len(ai_call_path_entries),
            "ei_skipped_count": sum(
                1 for payload in ai_call_path_entries
                if bool(payload.get("ei_skipped"))
            ),
            "ar_skipped_count": sum(
                1 for payload in ai_call_path_entries
                if bool(payload.get("ar_skipped"))
            ),
            "fdc_skipped_count": sum(
                1 for payload in ai_call_path_entries
                if bool(payload.get("fdc_skipped"))
            ),
            "skip_reason_counts": dict(skip_reason_counts),
        },
    }
    if universe_anchor is not None:
        metrics["universe_anchor_source"] = universe_anchor.source
        metrics["universe_freeze_run_id"] = universe_anchor.universe_freeze_run_id
        metrics["freeze_purpose"] = universe_anchor.freeze_purpose
        metrics["freeze_reused"] = universe_anchor.freeze_reused
        metrics["universe_anchor"] = asdict(universe_anchor)

    return {
        "mode": "summary",
        "total_cycles": total,
        "success": success,
        "skipped": skipped,
        "error": errors,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "total_duration_seconds": round(total_duration, 3),
        "metrics": metrics,
    }


# ── Core cycle ──────────────────────────────────────────────────────────────


# Per-agent hard timeout: safety net for the assemble_and_submit() call.
# Phase 4 subprocess isolation provides SIGKILL-guaranteed timeout at the
# subprocess level (30s), so this outer timeout is a last-resort safety
# net rather than the primary timeout mechanism.
# Reduced from 420s to 150s to align with deepseek-chat P99 latency
# (~15.9s) with 9.4x safety margin covering all 3 agents + overhead.
# The scheduler-level _DECISION_TIMEOUT (600s) covers the entire
# asyncio.gather() for all universe symbols.
PER_AGENT_HARD_TIMEOUT = 150  # seconds

# ── FDC 실제 dispatch post-gather phase 소프트 데드라인(2026-08-27 2차
# 리뷰 보정 — PR #359) ────────────────────────────────────────────────
# ops-scheduler가 이 프로세스(run_decision_loop.py) 전체에 부여하는
# decision subprocess timeout(``scripts/run_ops_scheduler.py``
# ``DEFAULT_DECISION_SUBMIT_TIMEOUT_SECONDS``, 기본 420초)과 동일한 값을
# 여기서도 읽어 cycle 시작 시각 기준 소프트 데드라인을 계산한다 — gather()
# phase가 이미 소비한 시간을 제외한 나머지 예산만 FDC dispatch phase에
# 쓴다. ``_FDC_DISPATCH_PHASE_SAFETY_MARGIN_SECONDS``는 데드라인 도달 후
# CANCELLED 처리 + 프로세스 정상 종료에 필요한 여유다.
_DECISION_SUBPROCESS_TIMEOUT_CEILING_SECONDS = int(
    os.environ.get("OPS_SCHEDULER_DECISION_TIMEOUT_SECONDS", "420")
)
_FDC_DISPATCH_PHASE_SAFETY_MARGIN_SECONDS = 20

# ── T3 (Seeded News) timeout & freshness ─────────────────────────────────────
# T3 pipeline (KIS disclosure + NAVER news search) has no hard timeout
# and can block the critical path for minutes.  Decoupled via parallel
# execution with this timeout for the live pipeline.
_T3_TIMEOUT = 60            # T3 pipeline 전체 timeout (초)
_T3_FRESHNESS_SECONDS = 7200  # T3 freshness window (2시간)
_T3_GATHER_WAIT = 5         # decision 완료 후 T3 추가 대기시간 (초)

# ── T3 async task tracking ──────────────────────────────────────────────────
# Active T3 pipeline tasks running in background (fire-and-forget via
# asyncio.create_task).  These are drained at cycle end so that persisted
# events are available for the next cycle's freshness check.
_active_t3_tasks: set[asyncio.Task] = set()


async def _replay_fdc_ready_shadow_events_for_cycle(
    cycle_results: list[dict[str, object]],
    *,
    cycle_count: int,
) -> None:
    """FDC cycle-scoped batch queue lifecycle shadow(Phase 1, 2026-08-25
    2차 보정) — 사이클의 모든 심볼 처리(``asyncio.gather``)가 끝난 뒤,
    이번 사이클에서 수집된 FDC-ready 이벤트를 ``(fdc_ready_at, cycle_
    index)`` 기준으로 정렬해 순서대로 shadow 큐에 등록한다.

    ``cycle_index``는 별도로 저장하지 않고 ``enumerate(cycle_results)``의
    위치를 그대로 쓴다 — ``asyncio.gather()``는 완료 순서와 무관하게
    입력 코루틴 순서(=``enumerate(universe)`` 시점에 고정된 순서)를 그대로
    보존하므로, 이 위치값은 어떤 subprocess/코루틴 완료 순서에도 의존하지
    않는 안정적 tie-breaker다. 1차 보정까지는 DB INSERT 도착 순서
    (``enqueue_sequence`` 자동 채번)를 FIFO 순서로 오인했으나, 그 도착
    순서는 기존 limiter 대기·provider 응답·subprocess 종료 순서에 좌우돼
    실제 FDC-ready 순서와 다를 수 있었다 — 이 함수가 그 결함을 보정한다:
    DB 등록 자체를 사이클 종료 후 이 정렬된 순서대로 **순차** 재생해,
    ``enqueue_sequence``가 항상 진짜 FDC-ready 순서를 반영하게 만든다.

    shadow flag가 꺼져 있거나 이번 사이클에 FDC-ready 이벤트가 하나도
    없으면 DB에 전혀 접근하지 않는다(완전 no-op). 개별 항목의 등록
    실패는 예외를 삼켜 나머지 항목의 재생과 사이클 진행에 영향을 주지
    않는다(best-effort, 다른 shadow 관측 경로와 동일한 안전 원칙).
    """
    from agent_trading.config.settings import AppSettings
    from agent_trading.db.transaction import transaction as _db_transaction
    from agent_trading.repositories.postgres.bootstrap import (
        build_postgres_repositories,
    )

    settings = AppSettings()
    if not settings.fdc_batch_queue_lifecycle_shadow_enabled:
        return

    pending: list[tuple[int, dict[str, object]]] = []
    for idx, r in enumerate(cycle_results):
        if not isinstance(r, dict):
            continue
        raw_event = r.get("_fdc_ready_shadow_event")
        if isinstance(raw_event, dict):
            pending.append((idx, raw_event))

    if not pending:
        return

    def _sort_key(pair: tuple[int, dict[str, object]]) -> tuple[str, int]:
        idx, raw_event = pair
        return (str(raw_event.get("fdc_ready_at", "")), idx)

    pending.sort(key=_sort_key)

    try:
        async with _db_transaction() as tx:
            repos = build_postgres_repositories(tx)
            coordinator = FdcQuotaCoordinator(
                repo=repos.fdc_quota,
                target_rpm=settings.fdc_provider_target_rpm,
                window_seconds=settings.fdc_provider_rate_window_seconds,
                declared_rpm_limit=settings.gemini_provider_declared_rpm_limit,
            )
            for idx, raw_event in pending:
                symbol = str(raw_event.get("symbol", ""))
                try:
                    fdc_ready_at = datetime.fromisoformat(
                        str(raw_event.get("fdc_ready_at", ""))
                    )
                except ValueError:
                    logger.warning(
                        "fdc_batch_queue_lifecycle_shadow replay: invalid "
                        "fdc_ready_at cycle=%d cycle_index=%d symbol=%s",
                        cycle_count, idx, symbol,
                    )
                    continue
                decision_context_id_raw = raw_event.get("decision_context_id")
                decision_context_id = (
                    UUID(str(decision_context_id_raw))
                    if decision_context_id_raw
                    else None
                )
                try:
                    result = await coordinator.register_shadow_job_and_judge(
                        decision_cycle_id=raw_event.get("decision_cycle_id"),
                        decision_context_id=decision_context_id,
                        symbol=symbol,
                        source_type=str(raw_event.get("source_type", "core")),
                        fdc_ready_at=fdc_ready_at,
                    )
                    if isinstance(result, CoordinatorError):
                        logger.warning(
                            "fdc_batch_queue_lifecycle_shadow replay coordinator "
                            "error: cycle=%d cycle_index=%d symbol=%s "
                            "error_class=%s detail=%s",
                            cycle_count, idx, symbol,
                            result.error_class.value, result.detail,
                        )
                except Exception:
                    logger.warning(
                        "fdc_batch_queue_lifecycle_shadow replay failed: "
                        "cycle=%d cycle_index=%d symbol=%s",
                        cycle_count, idx, symbol,
                        exc_info=True,
                    )
            await tx.commit()
    except Exception:
        logger.warning(
            "fdc_batch_queue_lifecycle_shadow replay transaction failed: "
            "cycle=%d",
            cycle_count,
            exc_info=True,
        )


async def _run_one_cycle(
    cycle: int,
    *,
    submit: bool,
    dry_run: bool,
    output: str,
    symbol: str = SYMBOL,
    market: str = MARKET,
    source_type: str = "core",
    market_segment: str | None = None,
    index_memberships: tuple[str, ...] = (),
    dry_run_reason: str | None = None,
    remaining_general_buy_budget: int | None = None,
    runtime: dict[str, object],              # ★ 공유 runtime (외부에서 주입)
    cycle_precheck: dict[str, object] | None = None,  # ★ cycle precheck (외부에서 주입)
    universe_anchor: UniverseAnchorMetadata | None = None,
    deterministic_trigger_override: dict[str, object] | None = None,
    r3b_alpha_percentile: float | None = None,
    defer_actionable_for_pass2: bool = False,
    pending_candidates_sink: list[dict[str, object]] | None = None,
    cycle_index: int | None = None,
    decision_cycle_id: str | None = None,
    pending_fdc_dispatch_sink: list[dict[str, object]] | None = None,
    precomputed_agent_bundle: object | None = None,
    decision_context_id_override: object | None = None,
) -> dict[str, object]:
    """Execute a single decision cycle with shared runtime.

    ``pending_fdc_dispatch_sink``/``precomputed_agent_bundle``(2026-08-27
    2차 리뷰 보정 — PR #359): FDC 실제 dispatch(held_position REDUCE_
    CANDIDATE/SELL_CANDIDATE) 대상 symbol은 quota reservation을 기다리지
    않는다 — ``assemble_and_submit()``이 ``SubmitResult(status=
    "FDC_ACTUAL_DISPATCH_PENDING", ...)``을 즉시 반환하면, 이 함수는
    제출을 시도하지 않고 ``pending_fdc_dispatch_sink``에 재개에 필요한
    정보만 적재한 뒤 반환한다(``asyncio.gather()``를 막지 않는다).
    post-gather dispatcher(``_run_fdc_actual_dispatch_phase()``)가 별도
    concurrency(``FDC_WORKER_CONCURRENCY``)로 reservation 대기 + fdc_only
    실행을 완료한 뒤, 이 함수를 ``precomputed_agent_bundle``과 함께
    다시 호출해(``submit=True``) 나머지 파이프라인(override → EV gate →
    sizing → submit)을 완결한다 — 이때는 agent를 다시 호출하지 않는다.
    ``decision_context_id_override``를 함께 넘겨 1차 pre_fdc 호출이 쓴
    것과 동일한 decision_context_id를 재사용한다 — 그래야 pre_fdc/
    fdc_only 단계에서 이미 기록된 AgentRun이 2차 assemble()의
    ``_rehydrate_subprocess_agent_runs()``와 같은 decision_context_id로
    연결된다(새로 resolve하면 1차 기록과 어긋난다).

    ``defer_actionable_for_pass2``(D안, 2026-08-11 KST)가 True이면
    ``submit``/``dry_run``과 무관하게 ``assemble()``만 실행한다. AI 판단이
    actionable(BUY/APPROVE)이면 실제 제출을 시도하지 않고
    ``pending_candidates_sink``에 후보만 적재한 뒤 ``PENDING_PASS2``
    상태를 반환한다(호출자의 Pass 1.5/Pass 2가 이어받는다). non-actionable
    (WATCH/HOLD)이면 오늘과 동일하게 즉시 ``run_execution_pipeline()``을
    실행해 감사 추적(``execution_attempts``)을 그대로 남긴다. 상세 설계:
    ``docs/40_action_plans/submit_budget_two_stage_design_2026-08-11.md``.

    Per-symbol transaction을 생성하여 격리를 보장한다.
    Runtime (pool, httpx clients, agents)은 외부에서 주입받아 공유한다.

    Returns a serialized result dict.
    """
    start = time.monotonic()
    precheck: dict[str, object] | None = cycle_precheck
    logger.info(
        "[SYMBOL_START] cycle=%d symbol=%s market=%s submit=%s dry_run=%s source_type=%s",
        cycle, symbol, market, submit, dry_run, source_type,
    )


    try:
        # ★ Per-symbol transaction 생성 (격리 보장)
        # 변경 전: postgres_runtime()이 하나의 transaction을 모든 symbol이 공유
        # 변경 후: 각 symbol이 독립적 transaction 사용
        from agent_trading.config.settings import AppSettings
        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
        from agent_trading.services.decision_orchestrator import DecisionOrchestratorService
        from agent_trading.services.order_manager import OrderManager
        from agent_trading.services.reconciliation_service import ReconciliationService
        from agent_trading.services.regime_switch_gate import resolve_cached_trigger_status

        async with _db_transaction() as tx:
            repos: RepositoryContainer = build_postgres_repositories(tx)
            settings = AppSettings()
            orchestrator = DecisionOrchestratorService(
                repos=repos,
                llm_provider=settings.llm_provider,
                provider_api_key=settings.provider_api_key or "",
                provider_base_url=settings.provider_base_url or "",
                provider_model_id=settings.provider_model_id or "",
                provider_timeout_seconds=settings.provider_timeout_seconds or 120,
                regime_switch_v1_trigger_status=resolve_cached_trigger_status(),
                regime_switch_v1_gate_override_enabled=(
                    settings.regime_switch_v1_gate_override_enabled
                ),
                r3b_alpha_enabled=settings.entry_score_r3b_alpha_enabled,
                ev_gate_near_miss_override_enabled=(
                    settings.ev_gate_near_miss_override_enabled
                ),
                loss_cut_shadow_enabled=settings.loss_cut_shadow_enabled,
                loss_cut_shadow_soft_threshold_pct=(
                    settings.loss_cut_shadow_soft_threshold_pct
                ),
                loss_cut_shadow_hard_threshold_pct=(
                    settings.loss_cut_shadow_hard_threshold_pct
                ),
                ar_shadow_bot_enabled=settings.ar_shadow_bot_enabled,
                ei_shadow_bot_enabled=settings.ei_shadow_bot_enabled,
                held_position_fdc_skip_shadow_enabled=(
                    settings.held_position_fdc_skip_shadow_enabled
                ),
                held_position_reduce_skip_shadow_enabled=(
                    settings.held_position_reduce_skip_shadow_enabled
                ),
                fdc_batch_queue_lifecycle_shadow_enabled=(
                    settings.fdc_batch_queue_lifecycle_shadow_enabled
                ),
                fdc_actual_dispatch_enabled=settings.fdc_actual_dispatch_enabled,
            )
            reconciliation_service = ReconciliationService(repos=repos)
            order_manager = OrderManager(
                repos=repos,
                reconciliation_service=reconciliation_service,
            )

            pre_ai_validation_result, pre_ai_skip_details = await _evaluate_pre_ai_validation_result(
                repos,
                account_alias=ACCOUNT_ALIAS,
                symbol=symbol,
                market=market,
                source_type=source_type,
                remaining_general_buy_budget=remaining_general_buy_budget,
                db_conn=tx.connection,
            )
            pre_ai_skip_reason = (
                pre_ai_validation_result.stop_reason
                if pre_ai_validation_result is not None
                else None
            )
            if pre_ai_skip_reason is not None:
                try:
                    await _record_pre_ai_guardrail_evaluation(
                        repos,
                        account_alias=ACCOUNT_ALIAS,
                        symbol=symbol,
                        market=market,
                        source_type=source_type,
                        decision_cycle_id=decision_cycle_id,
                        validation_result=pre_ai_validation_result
                        if pre_ai_validation_result is not None
                        else ValidationResult.blocked(
                            rule_set_version="pre_ai_gate_v1",
                            blocking_rule_codes=[pre_ai_skip_reason],
                            rule_results={"details": pre_ai_skip_details},
                            stop_reason=pre_ai_skip_reason,
                        ),
                    )
                except Exception:
                    logger.warning(
                        "Failed to record pre-AI guardrail evaluation: symbol=%s reason=%s",
                        symbol,
                        pre_ai_skip_reason,
                        exc_info=True,
                    )
                result = SubmitResult(
                    status="SKIPPED",
                    error_phase="pre_ai_gate",
                    error_message=pre_ai_skip_reason,
                    stop_reason=pre_ai_skip_reason,
                    is_skipped=True,
                )
                duration = time.monotonic() - start
                logger.info(
                    "[SYMBOL_DONE] cycle=%d symbol=%s status=SKIPPED duration=%.1fs "
                    "pre_ai_skip_reason=%s details=%s",
                    cycle,
                    symbol,
                    duration,
                    pre_ai_skip_reason,
                    pre_ai_skip_details,
                )
                serialized = _serialize_cycle_result(
                    cycle,
                    result,
                    duration,
                    symbol=symbol,
                    market=market,
                    precheck=precheck,
                    dry_run=dry_run,
                    source_type=source_type,
                    dry_run_reason=dry_run_reason,
                    universe_anchor=universe_anchor,
                )
                serialized["skip_reason"] = pre_ai_skip_reason
                serialized["skip_details"] = pre_ai_skip_details
                return serialized

            # ── 3. Build request ────────────────────────────────────────
            # NOTE: 초기 request는 MARKET + price=None으로 시작한다.
            # quote fetch는 execution_service._resolve_quote() 단일 경로에서 처리하고,
            # 저유동성 BUY는 execution_service가 LIMIT 강제/차단까지 담당한다.
            #
            # 2026-08-21: 기본 side는 source_type별로 다르다 — held_position은
            # 이미 보유 중인 포지션이라 실제 actionable 판단은 항상
            # REDUCE/EXIT(=SELL) 방향이고 신규 매수(APPROVE/BUY)는 이 lane에서
            # 구조적으로 허용되지 않는다(FDC prompt의 held_position scope
            # 제약과 동일한 전제). FDC가 permit 거부(queue timeout 등)·
            # timeout·parse error로 fallback해 side가 빈 값(``""``)이 되면
            # decision_factory.resolve_order_side()가 이 request.side로
            # 대체하므로, 그 fallback 값 자체를 held_position의 실제 방향과
            # 일치하는 SELL로 맞춘다 — 이전에는 core/held_position 구분 없이
            # 항상 BUY였고, 그 결과 non-actionable(HOLD/WATCH) fallback 건의
            # 최종 trade_decisions.side가 실제로는 매수 신호가 전혀 없었음에도
            # BUY로 저장되는 표시 오류가 있었다(2026-08-21 실측 조사).
            # core/event_overlay/market_overlay는 기존과 동일하게 BUY 유지.
            default_side = (
                OrderSide.SELL if source_type == "held_position" else OrderSide.BUY
            )
            order_type, price = _resolve_order_type_and_price(
                side="buy",
                decision_type=None,
                default_price=None,
            )
            request = SubmitOrderRequest(
                account_ref=ACCOUNT_ALIAS,
                client_order_id=f"paper-loop-{symbol}-{cycle}-{int(start)}",
                correlation_id=f"paper-loop-{symbol}-{cycle}-{int(start)}",
                strategy_id=str(STRATEGY_ID),
                symbol=symbol,
                market=market,
                side=default_side,
                order_type=order_type,
                quantity=Decimal("1"),
                price=price,
                metadata={
                    "source_type": source_type,
                    "market_segment": market_segment,
                    "index_memberships": list(index_memberships or ()),
                    "deterministic_trigger_override": (
                        dict(deterministic_trigger_override)
                        if isinstance(deterministic_trigger_override, dict)
                        else None
                    ),
                    "r3b_alpha_percentile": r3b_alpha_percentile,
                    "universe_anchor": (
                        asdict(universe_anchor)
                        if universe_anchor is not None
                        else None
                    ),
                },
            )

            # ── 3.5 Seeded news → degraded path with parallel T3 ─────────
            # T3 pipeline is decoupled from the critical decision/submit path.
            # Decision path: reads persisted T3 events from DB only (fast, non-blocking).
            # T3 live path: runs in parallel via create_task, results persisted
            # for future cycles.  Freshness check prevents unnecessary live calls.
            _SEEDED_NEWS_ENABLED = os.environ.get("SEEDED_NEWS_ENABLED", "1") == "1"
            seeded_events: list[ExternalEventEntity] = []

            if _SEEDED_NEWS_ENABLED:
                # ── T3 pipeline skip for market_overlay only ──
                # held_position은 REDUCE/EXIT 판단에 최신 T3 이벤트가 직접
                # 영향을 줄 수 있으므로 live pipeline을 허용한다.
                # market_overlay는 no-event 정책이 다르고 Naver quota 보호
                # 효과가 커서 기존대로 skip 유지.
                if source_type == "market_overlay":
                    logger.debug(
                        "Skipping T3 live pipeline for symbol=%s source_type=%s",
                        symbol, source_type,
                    )
                    # Still read persisted events for decision context
                    seeded_events = await _collect_persisted_seeded_events(repos, symbol)
                else:
                    # ── Decision path: read persisted T3 events (non-blocking) ──
                    seeded_events = await _collect_persisted_seeded_events(repos, symbol)

                    # ── T3 live path: run synchronously (await) before assemble ──
                    t3_fresh = await _is_t3_fresh_for_symbol(repos, symbol)
                    if not t3_fresh:
                        # ── NAVER quota preemptive check ──
                        # If NAVER daily quota is >= 90% exhausted, skip the
                        # live pipeline entirely to avoid 429 timeouts.
                        from agent_trading.brokers.naver_news_adapter import (
                            NaverNewsSearchAdapter,
                        )
                        if NaverNewsSearchAdapter.is_quota_exhausted():
                            logger.warning(
                                "T3 live pipeline skipped for symbol=%s: "
                                "NAVER quota exhausted (%.1f%%)",
                                symbol,
                                NaverNewsSearchAdapter.get_daily_usage_ratio() * 100,
                            )
                        else:
                            # Fire-and-forget: T3 pipeline runs in background,
                            # decision path continues immediately (not blocked).
                            task = asyncio.create_task(
                                _run_t3_live_pipeline_shielded(
                                    runtime, repos, symbol, source_type=source_type
                                )
                            )
                            _active_t3_tasks.add(task)
                            task.add_done_callback(_active_t3_tasks.discard)

                    # ── Logging ──
                    freshness_hint = "fresh" if t3_fresh else "stale"
                    logger.info(
                        "Cycle %d symbol=%s: T3 decision path: %d persisted events "
                        "live_pipeline=%s",
                        cycle, symbol, len(seeded_events),
                        "skipped (fresh)" if t3_fresh else "sync_executed",
                    )
            else:
                logger.info(
                    "Cycle %d symbol=%s: T3 skipped (SEEDED_NEWS_ENABLED=0)",
                    cycle, symbol,
                )

            # ── 4. Execute cycle ────────────────────────────────────────
            if dry_run:
                # Dry-run: assemble + sizing only
                # Per-agent hard timeout: prevents LLM API stall from blocking
                # the cycle indefinitely.
                intent = await asyncio.wait_for(
                    orchestrator.assemble(
                        request,
                        seeded_events=seeded_events,
                        decision_cycle_id=decision_cycle_id,
                    ),
                    timeout=PER_AGENT_HARD_TIMEOUT,
                )
                sizing_inputs = orchestrator.build_sizing_inputs(intent)
                sizing_result = calculate_sizing(sizing_inputs)

                # Build synthetic SubmitResult for consistent serialization
                result = SubmitResult(
                    status="DRY_RUN",
                    order_intent=intent,
                    trade_decision_id=str(intent.trade_decision_id) if intent.trade_decision_id else None,
                    decision_context_id=intent.decision_context_id,
                    stop_reason=dry_run_reason,
                )

                if (
                    dry_run_reason is not None
                    and dry_run_reason != "cli_dry_run"
                    and intent.trade_decision_id is not None
                    and intent.decision_context_id is not None
                ):
                    _now = datetime.now(timezone.utc)
                    attempt = ExecutionAttemptEntity(
                        execution_attempt_id=uuid4(),
                        trade_decision_id=intent.trade_decision_id,
                        decision_context_id=intent.decision_context_id,
                        status="non_trade",
                        stop_phase="scheduler_gate",
                        stop_reason=dry_run_reason,
                        phase_trace=[],
                        started_at=_now,
                        completed_at=_now,
                        created_at=_now,
                    )
                    await repos.execution_attempts.add(attempt)
                    try:
                        await _record_scheduler_guardrail_evaluation(
                            repos,
                            account_alias=ACCOUNT_ALIAS,
                            symbol=symbol,
                            market=market,
                            source_type=source_type,
                            validation_result=ValidationResult.blocked(
                                rule_set_version="scheduler_gate_v1",
                                blocking_rule_codes=[dry_run_reason],
                                rule_results={"gate_phase": "scheduler_gate"},
                                stop_reason=dry_run_reason,
                            ),
                            trade_decision_id=intent.trade_decision_id,
                            decision_context_id=intent.decision_context_id,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to record scheduler guardrail evaluation: symbol=%s reason=%s",
                            symbol,
                            dry_run_reason,
                            exc_info=True,
                        )
                    logger.info(
                        "Recorded scheduler dry-run attempt: symbol=%s trade_decision_id=%s reason=%s",
                        symbol,
                        intent.trade_decision_id,
                        dry_run_reason,
                    )

                if sizing_result.applied_constraints:
                    logger.info(
                        "Cycle %d (dry-run): sizing constraints=%s quantity=%s",
                        cycle,
                        sizing_result.applied_constraints,
                        sizing_result.quantity,
                    )
            elif submit:
                # Full pipeline: assemble → submit
                # order_manager와 broker는 runtime에서 공유 객체 사용
                broker = runtime["primary_broker_adapter"]
                # Per-agent hard timeout: prevents LLM API stall from blocking
                # the cycle indefinitely.
                result = await asyncio.wait_for(
                    orchestrator.assemble_and_submit(
                        request,
                        order_manager=order_manager,
                        broker=broker,
                        seeded_events=seeded_events,
                        decision_cycle_id=decision_cycle_id,
                        precomputed_agent_bundle=precomputed_agent_bundle,
                        decision_context_id=decision_context_id_override,
                    ),
                    timeout=PER_AGENT_HARD_TIMEOUT,
                )
                if result is not None:
                    logger.info(
                        "Cycle %d submit result: status=%s error_phase=%s "
                        "error_message=%s trade_decision_id=%s",
                        cycle,
                        result.status,
                        getattr(result, "error_phase", None),
                        getattr(result, "error_message", None),
                        getattr(result, "trade_decision_id", None),
                    )
                    if (
                        result.status == "FDC_ACTUAL_DISPATCH_PENDING"
                        and pending_fdc_dispatch_sink is not None
                    ):
                        # FDC quota 예약 대기가 필요한 held-position job —
                        # 여기서 기다리지 않는다(gather()를 막지 않기 위함).
                        # post-gather dispatcher가 job_id로 예약을 완료한
                        # 뒤 이 symbol을 precomputed_agent_bundle과 함께
                        # 재실행해 나머지 파이프라인을 마무리한다.
                        pending_fdc_dispatch_sink.append({
                            "cycle_index": cycle_index,
                            "symbol": symbol,
                            "market": market,
                            "source_type": source_type,
                            "market_segment": market_segment,
                            "index_memberships": index_memberships,
                            "job_id": result.fdc_dispatch_job_id,
                            "pre_fdc_result": result.fdc_dispatch_pre_fdc_result,
                            "assembled_context": result.fdc_dispatch_assembled_context,
                            "provider_runtime": result.fdc_dispatch_provider_runtime,
                            "subprocess_timeout": result.fdc_dispatch_subprocess_timeout,
                            "request": request,
                            "seeded_events": seeded_events,
                            "decision_cycle_id": decision_cycle_id,
                            "universe_anchor": universe_anchor,
                            "deterministic_trigger_override": (
                                deterministic_trigger_override
                            ),
                            "r3b_alpha_percentile": r3b_alpha_percentile,
                        })
            elif defer_actionable_for_pass2:
                # D안 Pass 1(분석 전용) — assemble()만 실행하고, 실제 제출
                # 여부/시점은 Pass 1.5/Pass 2(호출자, _run_loop)로 미룬다.
                # budget 확인/소비는 여기서 전혀 하지 않는다(2026-08-11 KST).
                intent = await asyncio.wait_for(
                    orchestrator.assemble(
                        request,
                        seeded_events=seeded_events,
                        decision_cycle_id=decision_cycle_id,
                    ),
                    timeout=PER_AGENT_HARD_TIMEOUT,
                )
                is_actionable = (
                    build_submit_order_request_from_decision(intent) is not None
                )
                if is_actionable and pending_candidates_sink is not None:
                    pending_candidates_sink.append({
                        "cycle_index": cycle_index,
                        "symbol": symbol,
                        "market": market,
                        "source_type": source_type,
                        "intent": intent,
                        "trade_decision_id": intent.trade_decision_id,
                        "decision_context_id": intent.decision_context_id,
                        "request": request,
                        "final_trade_score": intent.ai_backend_inputs.final_trade_score,
                        "analysis_completed_at": datetime.now(timezone.utc),
                    })
                    result = SubmitResult(
                        status="PENDING_PASS2",
                        order_intent=intent,
                        trade_decision_id=(
                            str(intent.trade_decision_id)
                            if intent.trade_decision_id else None
                        ),
                        decision_context_id=intent.decision_context_id,
                    )
                else:
                    # non-actionable(WATCH/HOLD) — 오늘과 동일하게 즉시
                    # run_execution_pipeline()을 실행해 execution_attempts
                    # 감사 추적을 그대로 남긴다. budget과 무관(실제 제출까지
                    # 가지 않고 non-actionable로 조기 종료된다).
                    broker = runtime["primary_broker_adapter"]
                    execution_service = ExecutionService(repos=repos)
                    _phase_start = time.monotonic()
                    _phase_trace: list[PhaseTraceEntry] = []

                    def _add_phase(phase: str, status: str) -> None:
                        nonlocal _phase_start
                        _now_m = time.monotonic()
                        _phase_trace.append(
                            PhaseTraceEntry(
                                phase=phase,
                                elapsed_ms=int((_now_m - _phase_start) * 1000),
                                status=status,
                            )
                        )
                        _phase_start = _now_m

                    result = await asyncio.wait_for(
                        execution_service.run_execution_pipeline(
                            intent,
                            intent.trade_decision_id,
                            request,
                            order_manager,
                            broker,
                            actor_type="system",
                            actor_id="decision_orchestrator",
                            _add_phase=_add_phase,
                            _phase_trace=_phase_trace,
                        ),
                        timeout=PER_AGENT_HARD_TIMEOUT,
                    )
            else:
                # Should not happen (CLI defaults ensure submit=True or dry_run)
                result = SubmitResult(
                    status="ERROR",
                    error_phase="config",
                    error_message="Neither --submit nor --dry-run was set.",
                )

            # ── 4.5 Collect EI Agent output ──────────────────────────────
            ei_output: dict[str, object] | None = None
            if result is not None and result.order_intent is not None:
                ai_inputs = result.order_intent.ai_backend_inputs
                ei_output = {
                    "event_bias": ai_inputs.event_bias,
                    "event_conflict": ai_inputs.event_conflict,
                    "event_reason_codes": list(ai_inputs.event_reason_codes),
                }

            # FDC cycle-scoped batch queue lifecycle shadow(Phase 1, 2차
            # 보정) — assemble()이 노출한 관측값을 JSON 직렬화 가능한 dict
            # 로 변환해 결과 dict에 실어 보낸다(이 dict는 `output=="json"`
            # 일 때 그대로 `json.dumps()`되므로 dataclass 인스턴스를 직접
            # 담으면 안 된다). 실제 shadow DB 등록은 여기서 하지 않는다 —
            # 사이클의 모든 심볼 처리가 끝난 뒤 `_replay_fdc_ready_shadow_
            # events_for_cycle()`이 (fdc_ready_at, cycle_index) 순으로
            # 정렬해 한 번에 재생한다(진짜 FDC-ready 순서 보장).
            _pending_shadow_event = orchestrator.pending_fdc_ready_shadow_event
            fdc_ready_shadow_event: dict[str, object] | None = None
            if _pending_shadow_event is not None:
                fdc_ready_shadow_event = {
                    "decision_cycle_id": _pending_shadow_event.decision_cycle_id,
                    "decision_context_id": (
                        str(_pending_shadow_event.decision_context_id)
                        if _pending_shadow_event.decision_context_id is not None
                        else None
                    ),
                    "symbol": _pending_shadow_event.symbol,
                    "source_type": _pending_shadow_event.source_type,
                    "fdc_ready_at": _pending_shadow_event.fdc_ready_at.isoformat(),
                }

            # ── 5. Commit per-symbol transaction ─────────────────────────
            await tx.commit()

            duration = time.monotonic() - start
            logger.info(
                "[SYMBOL_DONE] cycle=%d symbol=%s status=%s duration=%.1fs",
                cycle, symbol,
                result.status if result is not None else "ERROR",
                duration,
            )
            serialized = _serialize_cycle_result(
                cycle,
                result,
                duration,
                symbol=symbol,
                market=market,
                precheck=precheck,
                dry_run=dry_run,
                ei_output=ei_output,
                source_type=source_type,
                dry_run_reason=dry_run_reason,
                universe_anchor=universe_anchor,
            )
            serialized["_fdc_ready_shadow_event"] = fdc_ready_shadow_event
            return serialized

    except asyncio.TimeoutError:
        duration = time.monotonic() - start
        _dc_id = getattr(request, 'decision_context_id', None) if 'request' in dir() else None
        logger.error(
            "PER_AGENT_HARD_TIMEOUT=%ds exceeded after %.1fs — "
            "raising to skip this symbol only.  symbol=%s decision_context_id=%s",
            PER_AGENT_HARD_TIMEOUT, duration, symbol, _dc_id,
        )
        # Cancel all pending asyncio tasks to allow C-level I/O (e.g. httpx
        # socket read) to unblock.  Without explicit cancellation, the event
        # loop may remain blocked on C-level I/O.
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        # Allow cancellations to propagate through the event loop
        await asyncio.sleep(0.5)
        # Raise to let _process_one()'s except Exception handler catch this
        # and record ERROR status, so remaining symbols continue processing.
        raise RuntimeError(
            f"TIMEOUT for symbol={symbol} "
            f"(PER_AGENT_HARD_TIMEOUT={PER_AGENT_HARD_TIMEOUT}s)"
        )
    except Exception as exc:
        duration = time.monotonic() - start
        logger.exception("[SYMBOL_DONE] cycle=%d symbol=%s status=ERROR duration=%.1fs error=%s", cycle, symbol, duration, exc)
        return _serialize_cycle_result(
            cycle,
            None,
            duration,
            symbol=symbol,
            market=market,
            precheck=precheck,
            dry_run=dry_run,
            error=str(exc),
            source_type=source_type,
            universe_anchor=universe_anchor,
        )


# ── Seeded news persistence ─────────────────────────────────────────────────


async def persist_seeded_events(
    events: list[ExternalEventEntity],
    repo: ExternalEventRepository,
) -> int:
    """
    Persist seeded news events to external_events table with dedup.

    Returns count of newly persisted events.
    - DB: long-term storage, analysis, audit trail
    - Transient injection to EI still happens separately via orchestrator.assemble()
    """
    persisted = 0
    skipped = 0
    for event in events:
        try:
            existing = await repo.find_by_dedup_key(event.dedup_key_hash)
            if existing is None:
                await repo.add(event)
                persisted += 1
            else:
                skipped += 1
        except Exception:
            logger.exception("Failed to persist seeded event: %s", event.dedup_key_hash)
            # Non-fatal: transient injection still works

    if persisted > 0 or skipped > 0:
        logger.info(
            "Seeded events persisted=%d skipped=%d total=%d",
            persisted, skipped, len(events),
        )
    return persisted


def _convert_disclosure_seeds_to_events(
    seeds: list,
    tier: str = "T2",
) -> list[ExternalEventEntity]:
    """Convert KIS disclosure seed DTOs to ExternalEventEntity list.

    These are KIS disclosure events (not seeded_news), so they have:
    - event_type = "Y|{headline}" (KIS disclosure prefix)
    - source_reliability_tier = ``tier`` (default "T2")

    When ``tier="T2"`` (default), this does NOT affect
    ``has_fresh_t3_events()`` since the tier is T2.  But provides
    decision context via ``_collect_persisted_seeded_events()``.

    When ``tier="T3"`` (degraded mode), KIS disclosure seeds are
    stored as T3 events, which enables ``has_fresh_t3_events()``
    freshness check and ``_collect_persisted_seeded_events()``
    to include them in the decision context.
    """
    from uuid import uuid4

    from agent_trading.domain.models import DisclosureTitleDTO

    events: list[ExternalEventEntity] = []
    for seed in seeds:
        assert isinstance(seed, DisclosureTitleDTO), (
            f"Expected DisclosureTitleDTO, got {type(seed).__name__}"
        )
        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type=f"Y|{seed.headline}",
            source_name="kis_disclosure",
            source_reliability_tier=tier,
            symbol=seed.symbol,
            market="KR",
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            severity="medium",
            direction="neutral",
            headline=seed.headline,
        )
        events.append(event)
    return events


# ── T3 degraded path helpers ─────────────────────────────────────────────────


async def _collect_persisted_seeded_events(
    repos: RepositoryContainer,
    symbol: str,
) -> list[ExternalEventEntity]:
    """Read persisted T3 events from external_events table.

    This is the **degraded** path: only events persisted by previous
    T3 runs are available.  Returns [] if none found — the decision
    cycle proceeds gracefully without seeded news.

    Freshness: events within 72h window (same as current list_by_symbol
    default).  The caller decides whether to fire live pipeline based
    on _T3_FRESHNESS_SECONDS.

    Uses ``include_seeded_news=True`` so that ``event_type='seeded_news'``
    events (which do not carry the listed-event prefix) are included in
    the query result alongside listed OpenDART events.
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=72)
        events = await repos.external_events.list_by_symbol(
            symbol=symbol,
            since=since,
            include_seeded_news=True,
        )
        # Filter to T3 events only (seeded news = T3 reliability tier)
        t3_events = [e for e in events if e.source_reliability_tier == "T3"]
        return t3_events
    except Exception:
        logger.exception(
            "Failed to read persisted seeded events for symbol=%s", symbol,
        )
        return []


async def _is_t3_fresh_for_symbol(
    repos: RepositoryContainer,
    symbol: str,
) -> bool:
    """Check if T3 events exist for symbol within freshness window.

    Returns ``True`` on DB error (fail-closed) to protect NAVER quota
    by preventing unnecessary T3 live pipeline execution.
    """
    try:
        return await repos.external_events.has_fresh_t3_events(
            symbol=symbol,
            freshness_seconds=_T3_FRESHNESS_SECONDS,
        )
    except Exception:
        logger.warning(
            "T3 freshness check failed for symbol=%s — assuming fresh to protect NAVER quota",
            symbol,
        )
        return True  # fail-closed: DB 장애 시 "fresh"로 간주하여 live pipeline 실행 방지


async def _run_t3_live_pipeline(
    runtime: dict[str, object],
    repos: RepositoryContainer,
    symbol: str,
    source_type: str = "core",
) -> None:
    """Run live T3 pipeline (KIS disclosure + NAVER news) with timeout.

    This is designed to run **as a parallel task** via asyncio.create_task()
    alongside the decision path.  Results are persisted to DB for
    consumption by future cycles.

    On timeout, persists any partially collected events so that subsequent
    cycles can benefit from them even when NAVER API is degraded.

    Parameters
    ----------
    source_type : str
        Source type for query count policy.
        - ``"core"``: max_queries=1
        - ``"event_overlay"``: max_queries=1
        - ``"held_position"`` / ``"market_overlay"``: 이 경로에 도달하지 않음

    Log tags:
    - "T3 used live" — live pipeline 성공, DB persist 완료
    - "T3 partial persist on timeout" — timeout 시 partial persist 성공
    - "T3 skipped" — timeout 또는 disable로 skip
    """
    # Declare variables outside try so they are accessible in except blocks
    t0 = time.monotonic()
    seeds = None
    candidates = None
    seeded_events = None
    seed_errors = None

    try:
        # ── Preemptive NAVER quota check (이중 방어) ──
        from agent_trading.brokers.naver_news_adapter import (
            NaverNewsSearchAdapter,
        )
        naver_quota_exhausted = NaverNewsSearchAdapter.is_quota_exhausted()

        disclosure_seed_service = runtime.get("disclosure_seed_service")
        seeded_news_service = runtime.get("seeded_news_service")
        if disclosure_seed_service is None or seeded_news_service is None:
            logger.info("symbol=%s T3 skipped: services not available", symbol)
            return

        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.external_events import (
            PostgresExternalEventRepository,
        )

        # Step 1: Fetch disclosure titles (KIS API)
        seeds = await asyncio.wait_for(
            disclosure_seed_service.fetch_disclosure_titles([symbol]),
            timeout=_T3_TIMEOUT,
        )
        if not seeds:
            logger.info("symbol=%s T3 skipped: no disclosure seeds", symbol)
            return

        # ── Degraded mode: NAVER quota exhausted → persist KIS disclosure as T3 ──
        if naver_quota_exhausted:
            logger.warning(
                "symbol=%s T3 degraded mode: NAVER quota exhausted (%.1f%%), "
                "persisting %d KIS disclosure seeds as T3 events",
                symbol,
                NaverNewsSearchAdapter.get_daily_usage_ratio() * 100,
                len(seeds),
            )
            # Persist KIS disclosure seeds as T3 events so that
            # has_fresh_t3_events() freshness check and
            # _collect_persisted_seeded_events() can include them.
            partial_events = _convert_disclosure_seeds_to_events(seeds, tier="T3")
            async with _db_transaction() as tx:
                tx_repo = PostgresExternalEventRepository(tx)
                persisted = await persist_seeded_events(partial_events, tx_repo)
            logger.info(
                "symbol=%s T3 degraded: %d disclosure seeds persisted=%d as T3",
                symbol, len(seeds), persisted,
            )
            return

        # Step 2: Process seeds via NAVER news search
        # Source type별 Naver query 수 정책
        _source_type_max_queries: dict[str, int | None] = {
            "core": 1,
            "event_overlay": 1,
            "held_position": 1,
        }
        max_queries = _source_type_max_queries.get(source_type, None)
        candidates, metrics = await asyncio.wait_for(
            seeded_news_service.process_seeds(seeds, max_queries=max_queries),
            timeout=_T3_TIMEOUT,
        )

        # ── 429 감지: NAVER quota exhausted → degraded fallback ──
        if metrics.quota_exhausted_count > 0:
            logger.warning(
                "T3 degraded for symbol=%s: NAVER quota exhausted (%d seeds affected) — "
                "persisting KIS disclosure seeds as T3 events",
                symbol,
                metrics.quota_exhausted_count,
            )
            # KIS disclosure seeds를 T3 이벤트로 직접 persist (degraded mode)
            try:
                partial_events = _convert_disclosure_seeds_to_events(seeds, tier="T3")
                async with _db_transaction() as tx:
                    tx_repo = PostgresExternalEventRepository(tx)
                    partial_persisted = await persist_seeded_events(partial_events, tx_repo)
                    logger.info(
                        "T3 degraded persist for symbol=%s: %d events persisted",
                        symbol,
                        partial_persisted,
                    )
            except Exception:
                logger.exception(
                    "T3 degraded persist failed for symbol=%s", symbol,
                )
            return  # early return: pipeline 완료

        if not candidates:
            logger.info("symbol=%s T3 skipped: no candidates after processing", symbol)
            return

        # Step 3: Convert to ExternalEventEntity
        from agent_trading.services.seeded_news_converter import (
            convert_seeded_candidates,
        )
        seeded_events = convert_seeded_candidates(candidates)

        # Step 4: Persist to DB (use own transaction since parent context is closed)
        async with _db_transaction() as tx:
            ee_repo = PostgresExternalEventRepository(tx)
            persisted = await persist_seeded_events(seeded_events, ee_repo)
        logger.info(
            "symbol=%s T3 used live: %d events from %d candidates "
            "persisted=%d",
            symbol,
            len(seeded_events), len(candidates),
            persisted,
        )

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        logger.warning(
            "T3 live pipeline timed out after %.1fs for symbol=%s "
            "(source_type=%s, seeds=%d, candidates=%d, seed_errors=%d)",
            elapsed, symbol, source_type, len(seeds or []),
            len(candidates or []),
            len(seed_errors or []),
        )
        # Lazy imports for transaction-scoped repository
        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.external_events import (
            PostgresExternalEventRepository,
        )

        persisted = 0
        try:
            async with _db_transaction() as tx:
                tx_repo = PostgresExternalEventRepository(tx)

                if seeded_events is not None:
                    # Step 3 (convert) completed, Step 4 (persist) timed out
                    persisted = await persist_seeded_events(seeded_events, tx_repo)
                    logger.info(
                        "symbol=%s T3 partial persist on timeout: %d events",
                        symbol, len(seeded_events),
                    )
                elif candidates is not None:
                    # Step 2 (process) completed, Step 3 (convert) timed out
                    from agent_trading.services.seeded_news_converter import (
                        convert_seeded_candidates,
                    )
                    partial_events = convert_seeded_candidates(candidates)
                    persisted = await persist_seeded_events(partial_events, tx_repo)
                    logger.info(
                        "symbol=%s T3 partial persist on timeout: "
                        "%d candidates -> %d events",
                        symbol, len(candidates), len(partial_events),
                    )
                elif seeds is not None and len(seeds) > 0:
                    # Step 1 (disclosure) completed, Step 2 (process) timed out
                    # Persist KIS disclosure seeds as T3 events so that
                    # has_fresh_t3_events() recognizes them and prevents
                    # redundant T3 pipeline re-execution within the freshness window.
                    # Also provides decision context via _collect_persisted_seeded_events().
                    partial_events = _convert_disclosure_seeds_to_events(seeds, tier="T3")
                    persisted = await persist_seeded_events(partial_events, tx_repo)
                    logger.info(
                        "symbol=%s T3 partial persist on timeout: "
                        "%d disclosure seeds -> %d events (step 1 only)",
                        symbol, len(seeds), len(partial_events),
                    )
                else:
                    logger.warning(
                        "symbol=%s T3 skipped: live pipeline timed out after %ds "
                        "(no partial data to persist)",
                        symbol, _T3_TIMEOUT,
                    )
                # tx.__aexit__ auto-commits on success
        except Exception:
            logger.exception(
                "T3 partial persist failed for symbol=%s", symbol,
            )
        if persisted:
            logger.info(
                "T3 partial persist: %d seeded events for symbol=%s",
                persisted, symbol,
            )
    except Exception:
        logger.exception(
            "symbol=%s T3 skipped: live pipeline failed", symbol,
        )


async def _run_t3_live_pipeline_shielded(
    runtime: dict[str, object],
    repos: RepositoryContainer,
    symbol: str,
    source_type: str = "core",
) -> None:
    """Wrapper that runs ``_run_t3_live_pipeline`` under ``asyncio.shield()``.

    ``asyncio.shield()`` prevents external ``cancel()`` (e.g. from
    ``_run_one_cycle()``'s ``all_tasks().cancel()``) from propagating to the
    T3 live pipeline task, ensuring partial persist runs to completion.

    This is used via ``asyncio.create_task(_run_t3_live_pipeline_shielded(...))``
    rather than ``asyncio.create_task(asyncio.shield(...))``, because
    ``asyncio.shield()`` returns a ``Future`` while ``create_task()`` requires a
    coroutine.
    """
    return await asyncio.shield(
        _run_t3_live_pipeline(runtime, repos, symbol, source_type=source_type)
    )


# ── D안 Pass 1.5 + Pass 2 (submit budget 2단계 분리, 2026-08-11 KST) ─────────
# 상세 설계: docs/40_action_plans/submit_budget_two_stage_design_2026-08-11.md
#
# 우선순위 정렬 기준(고정, 로그에도 동일하게 남긴다):
#   1차 source_type — core > event_overlay > market_overlay
#   2차 final_trade_score 내림차순
#   3차 analysis_completed_at 오름차순(먼저 분석 끝난 것 우선)
_GENERAL_LANE_SOURCE_TYPE_PRIORITY: dict[str, int] = {
    "core": 0,
    "event_overlay": 1,
    "market_overlay": 2,
}


def _general_lane_priority_key(
    candidate: dict[str, object],
) -> tuple[int, Decimal, datetime]:
    source_rank = _GENERAL_LANE_SOURCE_TYPE_PRIORITY.get(
        str(candidate.get("source_type")), 99
    )
    score = candidate.get("final_trade_score")
    score_key = -(score if isinstance(score, Decimal) else Decimal("-Infinity"))
    analysis_completed_at = candidate.get("analysis_completed_at") or datetime.now(
        timezone.utc
    )
    return (source_rank, score_key, analysis_completed_at)


def _general_lane_dropped_result(
    cycle_count: int,
    candidate: dict[str, object],
    reason: str,
) -> dict[str, object]:
    return _serialize_cycle_result(
        cycle_count,
        SubmitResult(
            status="SKIPPED",
            stop_reason=reason,
            order_intent=candidate.get("intent"),
            trade_decision_id=(
                str(candidate["trade_decision_id"])
                if candidate.get("trade_decision_id")
                else None
            ),
            decision_context_id=candidate.get("decision_context_id"),
        ),
        0.0,
        symbol=str(candidate.get("symbol")),
        market=str(candidate.get("market")),
        source_type=str(candidate.get("source_type")),
    )


def _emit_general_lane_pass2_output(
    result: dict[str, object], *, cycle_count: int, output: str,
) -> None:
    """Pass 2에서 확정된 결과를 오늘과 동일한 방식으로 stdout/log에 남긴다.

    ``_process_one()``의 "Output per-symbol result" 블록과 동일한 형식이다
    — ``run_ops_scheduler.py``의 stdout JSON 파서(``_extract_json_objects``
    등)가 Pass 2 결과도 오늘과 동일하게 한 줄씩 읽을 수 있어야 한다.
    """
    if output == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        logger.info(
            "Cycle %d symbol=%s:%s complete(pass2) — status=%s duration=%.2fs",
            cycle_count,
            result.get("symbol"),
            result.get("market"),
            result.get("status", "UNKNOWN"),
            result.get("duration_seconds", 0),
        )


async def _submit_general_lane_candidate(
    candidate: dict[str, object],
    *,
    cycle_count: int,
    runtime: dict[str, object],
) -> dict[str, object]:
    """Pass 2: 이미 확정된 actionable intent를 실제로 제출한다.

    ``assemble()``을 다시 호출하지 않는다 — Pass 1이 만든 ``intent``를
    그대로 ``ExecutionService.run_execution_pipeline()``에 넘겨 AI 비용을
    중복으로 지불하지 않는다.
    """
    from agent_trading.db.transaction import transaction as _db_transaction
    from agent_trading.repositories.postgres.bootstrap import (
        build_postgres_repositories,
    )
    from agent_trading.services.order_manager import OrderManager
    from agent_trading.services.reconciliation_service import ReconciliationService

    symbol = str(candidate["symbol"])
    market = str(candidate["market"])
    source_type = str(candidate["source_type"])
    _start = time.monotonic()
    try:
        async with _db_transaction() as tx:
            repos: RepositoryContainer = build_postgres_repositories(tx)

            # ── Pass 2 진입 직전 재검증: reentry cooldown/저orderable cash 등
            # pre_ai_gate 사유를 다시 확인한다(Pass 1과 동일 함수 재호출 —
            # 그 사이 새로 발생한 조건만 새로 걸린다). "포지션이 새로 생겼는지"
            # 자체는 이 함수가 general 신규진입 경로에서 하드 블록하지 않으므로
            # (일부러 그렇게 설계됨 — HOLD/REDUCE 판단을 막지 않기 위해)
            # 완전히 커버되지 않는다 — 대신 run_execution_pipeline() 내부의
            # duplicate-buy guard(_evaluate_buy_duplicate_validation_result)가
            # "이미 활성 매수 주문이 있는" 케이스를 잡아준다. cash/duplicate/
            # stale snapshot/quote는 run_execution_pipeline()이 호출 시점에
            # 자체적으로 재확인한다.
            revalidation, _details = await _evaluate_pre_ai_validation_result(
                repos,
                account_alias=ACCOUNT_ALIAS,
                symbol=symbol,
                market=market,
                source_type=source_type,
                remaining_general_buy_budget=None,
                db_conn=tx.connection,
            )
            if revalidation is not None and revalidation.stop_reason:
                duration = time.monotonic() - _start
                return _serialize_cycle_result(
                    cycle_count,
                    SubmitResult(
                        status="SKIPPED",
                        stop_reason=f"pass2_stale_{revalidation.stop_reason}",
                        order_intent=candidate.get("intent"),
                        trade_decision_id=(
                            str(candidate["trade_decision_id"])
                            if candidate.get("trade_decision_id")
                            else None
                        ),
                        decision_context_id=candidate.get("decision_context_id"),
                    ),
                    duration,
                    symbol=symbol, market=market, source_type=source_type,
                )

            # ── market session 재확인(경량) ──────────────────────────────
            # run_ops_scheduler.py의 session_gate가 이 subprocess 자체를
            # 이미 intraday 구간에서만 기동하지만, Pass 1→Pass 2 사이 시간이
            # 벌어져 장마감 경계를 넘을 가능성에 대한 최소 방어선이다.
            now_kst = datetime.now(KST)
            if (now_kst.hour, now_kst.minute) >= (15, 30):
                duration = time.monotonic() - _start
                return _serialize_cycle_result(
                    cycle_count,
                    SubmitResult(
                        status="SKIPPED",
                        stop_reason="pass2_market_session_closed",
                        order_intent=candidate.get("intent"),
                        trade_decision_id=(
                            str(candidate["trade_decision_id"])
                            if candidate.get("trade_decision_id")
                            else None
                        ),
                        decision_context_id=candidate.get("decision_context_id"),
                    ),
                    duration,
                    symbol=symbol, market=market, source_type=source_type,
                )

            reconciliation_service = ReconciliationService(repos=repos)
            order_manager = OrderManager(
                repos=repos, reconciliation_service=reconciliation_service,
            )
            execution_service = ExecutionService(repos=repos)
            broker = runtime["primary_broker_adapter"]

            _phase_start = time.monotonic()
            _phase_trace: list[PhaseTraceEntry] = []

            def _add_phase(phase: str, status: str) -> None:
                nonlocal _phase_start
                _now_m = time.monotonic()
                _phase_trace.append(
                    PhaseTraceEntry(
                        phase=phase,
                        elapsed_ms=int((_now_m - _phase_start) * 1000),
                        status=status,
                    )
                )
                _phase_start = _now_m

            result = await asyncio.wait_for(
                execution_service.run_execution_pipeline(
                    candidate["intent"],
                    candidate["trade_decision_id"],
                    candidate["request"],
                    order_manager,
                    broker,
                    actor_type="system",
                    actor_id="decision_orchestrator",
                    _add_phase=_add_phase,
                    _phase_trace=_phase_trace,
                ),
                timeout=PER_AGENT_HARD_TIMEOUT,
            )
            await tx.commit()
        duration = time.monotonic() - _start
        return _serialize_cycle_result(
            cycle_count, result, duration,
            symbol=symbol, market=market, source_type=source_type,
        )
    except Exception as exc:
        duration = time.monotonic() - _start
        logger.exception("Pass2 submit failed symbol=%s: %s", symbol, exc)
        return _serialize_cycle_result(
            cycle_count, None, duration, symbol=symbol, market=market,
            source_type=source_type, error=str(exc),
        )


async def _run_general_lane_pass2(
    pending_general_candidates: list[dict[str, object]],
    *,
    cycle_results: list[dict[str, object]],
    cycle_count: int,
    max_general_submits_this_cycle: int,
    submit_budget_consumed_count: int,
    runtime: dict[str, object],
    output: str = "json",
    decision_cycle_id: str | None = None,
) -> int:
    """Pass 1.5(dedupe+정렬) + Pass 2(순차 제출)를 실행하고, 갱신된
    ``submit_budget_consumed_count``를 반환한다.

    ``cycle_results``는 ``cycle_index``로 in-place 갱신한다(PENDING_PASS2
    placeholder를 최종 결과로 교체).
    """
    # ── Pass 1.5: symbol 단위 dedupe(같은 symbol이 여러 source_type으로
    # 동시에 universe에 들어온 경우 우선순위가 가장 높은 1건만 남긴다) ──
    best_by_symbol: dict[str, dict[str, object]] = {}
    for candidate in pending_general_candidates:
        symbol = str(candidate["symbol"])
        existing = best_by_symbol.get(symbol)
        if existing is None or _general_lane_priority_key(
            candidate
        ) < _general_lane_priority_key(existing):
            if existing is not None:
                logger.info(
                    "SUBMIT_PIPELINE_TRACE candidate_dropped cycle=%d symbol=%s "
                    "source_type=%s reason=symbol_duplicate_in_cycle",
                    cycle_count, symbol, existing["source_type"],
                )
                dropped = _general_lane_dropped_result(
                    cycle_count, existing, "symbol_duplicate_in_cycle",
                )
                cycle_results[existing["cycle_index"]] = dropped
                await _record_pass2_general_lane_drop_guardrail_evaluation(
                    existing, cycle_count=cycle_count,
                    reason="symbol_duplicate_in_cycle",
                    decision_cycle_id=decision_cycle_id,
                )
                _emit_general_lane_pass2_output(
                    dropped, cycle_count=cycle_count, output=output,
                )
            best_by_symbol[symbol] = candidate
        else:
            logger.info(
                "SUBMIT_PIPELINE_TRACE candidate_dropped cycle=%d symbol=%s "
                "source_type=%s reason=symbol_duplicate_in_cycle",
                cycle_count, symbol, candidate["source_type"],
            )
            dropped = _general_lane_dropped_result(
                cycle_count, candidate, "symbol_duplicate_in_cycle",
            )
            cycle_results[candidate["cycle_index"]] = dropped
            await _record_pass2_general_lane_drop_guardrail_evaluation(
                candidate, cycle_count=cycle_count,
                reason="symbol_duplicate_in_cycle",
                decision_cycle_id=decision_cycle_id,
            )
            _emit_general_lane_pass2_output(
                dropped, cycle_count=cycle_count, output=output,
            )

    sorted_candidates = sorted(
        best_by_symbol.values(), key=_general_lane_priority_key
    )
    for rank, candidate in enumerate(sorted_candidates):
        score = candidate.get("final_trade_score")
        logger.info(
            "SUBMIT_PIPELINE_TRACE candidate_enqueued cycle=%d symbol=%s "
            "source_type=%s priority_rank=%d source_type_rank=%d "
            "final_trade_score=%s analysis_completed_at=%s",
            cycle_count, candidate["symbol"], candidate["source_type"], rank,
            _GENERAL_LANE_SOURCE_TYPE_PRIORITY.get(
                str(candidate["source_type"]), 99
            ),
            str(score) if score is not None else "none",
            candidate["analysis_completed_at"].isoformat(),
        )

    # ── Pass 2: 순차 제출, 그 순간의 budget 여유 안에서만 ──────────────
    for candidate in sorted_candidates:
        symbol = str(candidate["symbol"])
        source_type = str(candidate["source_type"])
        remaining = max_general_submits_this_cycle - submit_budget_consumed_count
        if remaining <= 0:
            logger.info(
                "SUBMIT_BUDGET_TRACE blocked cycle=%d symbol=%s source_type=%s "
                "submit_budget_consumed_count=%d general_submit_inflight_count=0 "
                "max_general_submits_this_cycle=%d stop_reason=%s pass=2",
                cycle_count, symbol, source_type, submit_budget_consumed_count,
                max_general_submits_this_cycle, "submit_budget_consumed_core",
            )
            logger.info(
                "SUBMIT_PIPELINE_TRACE submit_skipped cycle=%d symbol=%s "
                "reason=budget_exhausted remaining=0",
                cycle_count, symbol,
            )
            dropped = _general_lane_dropped_result(
                cycle_count, candidate, "submit_budget_consumed_core",
            )
            cycle_results[candidate["cycle_index"]] = dropped
            await _record_pass2_general_lane_drop_guardrail_evaluation(
                candidate, cycle_count=cycle_count,
                reason="submit_budget_consumed_core",
                decision_cycle_id=decision_cycle_id,
            )
            _emit_general_lane_pass2_output(
                dropped, cycle_count=cycle_count, output=output,
            )
            continue

        logger.info(
            "SUBMIT_PIPELINE_TRACE submit_attempt cycle=%d symbol=%s "
            "source_type=%s submit_budget_consumed_count_before=%d "
            "max_general_submits_this_cycle=%d",
            cycle_count, symbol, source_type, submit_budget_consumed_count,
            max_general_submits_this_cycle,
        )
        submit_result = await _submit_general_lane_candidate(
            candidate, cycle_count=cycle_count, runtime=runtime,
        )
        cycle_results[candidate["cycle_index"]] = submit_result
        _emit_general_lane_pass2_output(
            submit_result, cycle_count=cycle_count, output=output,
        )
        status = submit_result.get("status", "UNKNOWN")
        if status in ("SUBMITTED", "RECONCILE_REQUIRED"):
            submit_budget_consumed_count += 1
            logger.info(
                "SUBMIT_PIPELINE_TRACE submit_consumed cycle=%d symbol=%s "
                "status=%s submit_budget_consumed_count_after=%d",
                cycle_count, symbol, status, submit_budget_consumed_count,
            )
        else:
            logger.info(
                "SUBMIT_PIPELINE_TRACE submit_skipped cycle=%d symbol=%s "
                "reason=%s remaining=%d",
                cycle_count, symbol, status,
                max_general_submits_this_cycle - submit_budget_consumed_count,
            )

    return submit_budget_consumed_count


async def _run_fdc_actual_dispatch_phase(
    pending_jobs: list[dict[str, object]],
    *,
    runtime: dict[str, object],
    cycle_precheck: dict[str, object] | None,
    output: str,
    cycle_count: int,
    phase_deadline_monotonic: float,
) -> list[dict[str, object]]:
    """post-gather FDC 실제 dispatch phase(2026-08-27 2차 리뷰 보정 —
    PR #359, 설계 문서 §4/§6/§7/§17). ``asyncio.gather(*coros)``로 모든
    symbol 처리가 끝난 **뒤에만** 실행되며, symbol 처리용 semaphore
    (``_SEMAPHORE_MAX``)와 무관한 별도 semaphore(``FDC_WORKER_
    CONCURRENCY``)로 quota reservation 대기 + fdc_only 실행만 동시성을
    제한한다.

    ``phase_deadline_monotonic``(``time.monotonic()`` 기준)을 넘기면 아직
    reservation을 받지 못했거나 완결되지 않은 job은 더 이상 진행하지
    않고 ``CANCELLED``(reason="process_terminated_carryover_lost")로
    종결한다 — 이 dispatcher를 실행 중인 프로세스 인스턴스가 곧 종료돼
    carryover를 더 이상 들고 있을 수 없기 때문이며, 기존 recovery scan이
    이미 쓰는 3가지 reason 중 하나를 그대로 재사용한다(설계 문서 §5,
    신규 4번째 reason을 도입하지 않는다). ops-scheduler decision
    subprocess timeout(420초) 안에서 이 phase가 끝나도록, 호출자
    (``_run_loop()``)가 gather() phase 소요 시간을 뺀 나머지를
    ``phase_deadline_monotonic``으로 넘긴다.
    """
    if not pending_jobs:
        return []

    from agent_trading.config.settings import _resolve_fdc_worker_concurrency

    repos: RepositoryContainer = runtime["repositories"]
    semaphore = asyncio.Semaphore(_resolve_fdc_worker_concurrency())

    async def _complete_one(job: dict[str, object]) -> dict[str, object]:
        async with semaphore:
            remaining = phase_deadline_monotonic - time.monotonic()
            if remaining <= 0:
                try:
                    await repos.fdc_quota.mark_job_terminal(
                        job_id=job["job_id"], status="CANCELLED",
                        reason="process_terminated_carryover_lost",
                    )
                except Exception:
                    logger.exception(
                        "FDC dispatch deadline cancel failed: job_id=%s symbol=%s",
                        job["job_id"], job["symbol"],
                    )
                return {
                    "status": "CANCELLED", "symbol": job["symbol"],
                    "market": job["market"], "job_id": str(job["job_id"]),
                    "duration_seconds": 0.0,
                }
            try:
                bundle = await asyncio.wait_for(
                    complete_fdc_actual_dispatch(
                        fdc_quota_repo=repos.fdc_quota,
                        provider_runtime=job["provider_runtime"] or {},
                        subprocess_timeout=job["subprocess_timeout"] or 90,
                        job_id=job["job_id"],
                        pre_fdc_result=job["pre_fdc_result"],
                        correlation_id=job["request"].correlation_id,
                        decision_context_id=job["request"].decision_context_id,
                        assembled_context=job["assembled_context"],
                    ),
                    timeout=max(1.0, remaining),
                )
            except asyncio.TimeoutError:
                try:
                    await repos.fdc_quota.mark_job_terminal(
                        job_id=job["job_id"], status="CANCELLED",
                        reason="process_terminated_carryover_lost",
                    )
                except Exception:
                    logger.exception(
                        "FDC dispatch timeout cancel failed: job_id=%s symbol=%s",
                        job["job_id"], job["symbol"],
                    )
                return {
                    "status": "CANCELLED", "symbol": job["symbol"],
                    "market": job["market"], "job_id": str(job["job_id"]),
                    "duration_seconds": 0.0,
                }
            except Exception as exc:
                logger.exception(
                    "FDC actual dispatch failed unexpectedly: job_id=%s symbol=%s: %s",
                    job["job_id"], job["symbol"], exc,
                )
                return {
                    "status": "ERROR", "symbol": job["symbol"],
                    "market": job["market"], "job_id": str(job["job_id"]),
                    "error": str(exc), "duration_seconds": 0.0,
                }

            # second pass — 이미 완결된 agent_bundle로 override/EV-gate/
            # sizing/submit만 재실행한다(agent를 다시 호출하지 않는다).
            return await _run_one_cycle(
                cycle=cycle_count,
                submit=True,
                dry_run=False,
                output=output,
                symbol=job["symbol"],
                market=job["market"],
                source_type=job["source_type"],
                market_segment=job["market_segment"],
                index_memberships=job["index_memberships"],
                runtime=runtime,
                cycle_precheck=cycle_precheck,
                universe_anchor=job["universe_anchor"],
                deterministic_trigger_override=job["deterministic_trigger_override"],
                r3b_alpha_percentile=job["r3b_alpha_percentile"],
                cycle_index=job["cycle_index"],
                decision_cycle_id=job["decision_cycle_id"],
                precomputed_agent_bundle=bundle,
                decision_context_id_override=job["request"].decision_context_id,
            )

    coros = [_complete_one(job) for job in pending_jobs]
    return list(await asyncio.gather(*coros))


# ── Main loop ───────────────────────────────────────────────────────────────


async def _run_loop(
    *,
    interval: int,
    max_cycles: int,
    submit: bool,
    dry_run: bool,
    allow_general_submit: bool,
    max_general_submits_this_cycle: int,
    output: str,
    decision_cycle_id: str | None = None,
) -> int:
    """Main loop: run decision cycles until shutdown or count limit.

    ``decision_cycle_id``(Stage A-1b, 2026-08-20)는 관측성 전용 cycle
    식별자다 — scheduler(``run_ops_scheduler.py``)가 cycle 시작 시 이미
    확정한 값을 그대로 전달받는다. 이 프로세스 자체의 내부 ``cycle_count``
    는 매 subprocess 호출마다 1부터 다시 시작해 하루 전체를 가로지르는
    식별자로 쓸 수 없다 — 그래서 scheduler가 넘겨준 값을 그대로 쓰고,
    한 프로세스 안에서 여러 cycle이 도는 수동 실행 상황을 대비해서만
    ``#{cycle_count}``를 덧붙여 구분한다. 판정 로직에는 전혀 관여하지
    않는다.
    """
    logger.info(
        "Starting paper decision loop "
        "(interval=%ds, max_cycles=%s, submit=%s, dry_run=%s, output=%s) ...",
        interval,
        "infinite" if max_cycles <= 0 else str(max_cycles),
        submit,
        dry_run,
        output,
    )
    logger.info("Set %s to change interval (default=%d).", ENV_INTERVAL, DEFAULT_INTERVAL_SECONDS)
    universe, universe_anchor = await _load_trading_universe_with_anchor()
    logger.info(
        "Trading universe (%d): %s",
        len(universe),
        ", ".join(f"{item.symbol}:{item.market}" for item in universe),
    )
    logger.info(
        "Trading universe anchor: source=%s freeze_run_id=%s freeze_purpose=%s freeze_reused=%s",
        universe_anchor.source,
        universe_anchor.universe_freeze_run_id,
        universe_anchor.freeze_purpose,
        universe_anchor.freeze_reused,
    )
    logger.info("Set %s to change universe (comma-separated symbols).", ENV_TRADING_UNIVERSE)

    _install_signal_handlers()

    cycle_count = 0
    total_success = 0
    total_fail = 0
    results: list[dict[str, object]] = []
    loop_start = time.monotonic()

    # ── Runtime: 루프 진입 시 1회 생성, 모든 symbol이 공유 ──────────────
    # 변경 전: _run_one_cycle()이 각 symbol마다 postgres_runtime() 생성
    # 변경 후: _run_loop()에서 1회 생성, per-symbol transaction만 분리
    async with postgres_runtime(run_migrations=False) as runtime:
        # ── 최초 1회 seed (FK 체인) ─────────────────────────────────────
        # 변경 전: 각 symbol의 _run_one_cycle()에서 _seed_if_empty() 호출
        # 변경 후: 루프 진입 시 1회만 실행
        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories

        async with _db_transaction() as tx:
            seed_repos = build_postgres_repositories(tx)
            seeded = await _seed_if_empty(seed_repos)
            if seeded:
                logger.info("Initial seed completed.")
            else:
                logger.debug("Seed already exists (skipped).")
            await tx.commit()

        # ── FDC 실제 dispatch 재기동 recovery scan(§17.7, 2026-08-27 신설
        # — PR #359 리뷰 보정) ────────────────────────────────────────
        # 이 프로세스(run_decision_loop.py)는 ops-scheduler가 cycle마다
        # 새로 spawn하는 subprocess다 — 이전 invocation이 FDC 실제
        # dispatch 대기 도중 강제 종료됐다면(예: scheduler timeout),
        # 그 job의 in-memory carryover는 소실됐지만 DB의 fdc_queue_jobs
        # row는 non-terminal 상태로 남아있을 수 있다. 이 스캔이 그런
        # job을 CANCELLED(reason=process_terminated_carryover_lost)로
        # 정리한다 — idempotent(이미 terminal인 job은 건드리지 않음).
        # flag가 꺼져 있으면(이 기능을 아예 쓰지 않으면) 스캔도 생략한다.
        from agent_trading.config.settings import AppSettings as _AppSettingsForRecovery
        from agent_trading.services.fdc_quota_coordinator import DEFAULT_QUOTA_SCOPE

        if _AppSettingsForRecovery().fdc_actual_dispatch_enabled:
            async with _db_transaction() as recovery_tx:
                recovery_repos = build_postgres_repositories(recovery_tx)
                cancelled_count = await recovery_repos.fdc_quota.cancel_stale_real_jobs(
                    quota_scope=DEFAULT_QUOTA_SCOPE,
                )
                await recovery_tx.commit()
            if cancelled_count:
                logger.warning(
                    "FDC actual-dispatch recovery scan: cancelled %d "
                    "stale non-terminal real job(s) from a previous "
                    "process (reason=process_terminated_carryover_lost).",
                    cancelled_count,
                )
            else:
                logger.debug("FDC actual-dispatch recovery scan: no stale jobs.")

        while not _shutdown_event.is_set():
            # Check cycle limit
            if max_cycles > 0 and cycle_count >= max_cycles:
                logger.info("Reached requested cycle count (%d).", max_cycles)
                break

            cycle_count += 1
            _cycle_start_monotonic = time.monotonic()
            logger.info("=== Decision Cycle %d ===", cycle_count)

            # Stage A-1b(2026-08-20): scheduler가 넘겨준 decision_cycle_id를
            # 그대로 쓰되, 한 프로세스 안에서 여러 cycle이 도는 경우(수동
            # 실행)만 대비해 cycle_count를 덧붙여 구분한다. 운영 경로
            # (scheduler --count 1)에서는 cycle_count가 항상 1이라 사실상
            # 무영향이다.
            cycle_decision_cycle_id = (
                f"{decision_cycle_id}#{cycle_count}"
                if decision_cycle_id is not None
                else None
            )

            # ── Cycle당 1회 precheck (snapshot sync health) ─────────────
            # 변경 전: 각 symbol의 _run_one_cycle()에서 _run_precheck() 호출
            # 변경 후: cycle당 1회만 실행, 모든 symbol이 동일한 precheck 공유
            cycle_precheck: dict[str, object] | None = None
            try:
                async with _db_transaction() as tx:
                    precheck_repos = build_postgres_repositories(tx)
                    cycle_precheck = await _run_precheck(precheck_repos)
                    await tx.commit()
            except Exception as exc:
                logger.warning("Cycle pre-check failed: %s", exc)

            # ── Cycle당 1회 국면 혼합도 관측(SPPV-2.63, 관측 전용) ──────
            # BUY/SELL 판정과 완전히 분리된 순수 로깅 — 실패해도 사이클에
            # 영향 없음(_run_mixedness_check 내부에서 예외를 전부 흡수).
            try:
                async with _db_transaction() as tx:
                    mixedness_repos = build_postgres_repositories(tx)
                    await _run_mixedness_check(mixedness_repos)
                    await tx.commit()
            except Exception as exc:
                logger.warning("Mixedness check failed (관측 전용, 사이클에는 영향 없음): %s", exc)

            # ── Cycle당 1회 R3b alpha candidate_percentile precompute ──
            # (SPPV-2.69) — entry_score_r3b_alpha_enabled가 꺼져 있으면
            # (기본값) 함수 내부에서 즉시 빈 dict를 반환해 DB 조회조차
            # 하지 않는다. 실패해도 사이클에 영향 없음(예외 전부 흡수).
            cycle_r3b_alpha_percentiles: dict[str, float] = {}
            try:
                async with _db_transaction() as tx:
                    r3b_alpha_repos = build_postgres_repositories(tx)
                    cycle_r3b_alpha_percentiles = (
                        await _build_r3b_alpha_percentile_overrides_for_cycle(
                            r3b_alpha_repos,
                            universe=universe,
                        )
                    )
                    await tx.commit()
            except Exception as exc:
                logger.warning(
                    "R3b alpha precompute failed(사이클에는 영향 없음): %s", exc
                )

            # Semaphore-based parallel symbol processing.
            # Max 5 concurrent symbols to avoid overwhelming broker/LLM resources
            # while reducing total wall-clock time from ~190s to ~40s for 35 symbols.
            #
            # 2026-08-18 rollback: 이 값을 3으로 낮췄던 완화책(PR #286)은
            # 429 감소 효과가 실측으로 입증되지 않았고 cycle latency만
            # 거의 2배로 늘려, 원래 값 5로 되돌렸다. FDC provider 호출
            # 자체의 rate limit 대응은 이제
            # ``agent_trading.services.ai_agents.fdc_rate_limiter``의
            # 프로세스 간 공유 rate limiter가 담당한다(§work log 참고).
            _SEMAPHORE_MAX = 5
            sem = asyncio.Semaphore(_SEMAPHORE_MAX)
            cycle_deterministic_trigger_overrides: dict[str, dict[str, object]] = {}
            try:
                cycle_deterministic_trigger_overrides = (
                    await _build_core_risk_off_apply_overrides_for_cycle(
                        universe=universe,
                    )
                )
            except Exception:
                logger.warning(
                    "Cycle %d: failed to build authoritative core risk-off overrides",
                    cycle_count,
                    exc_info=True,
                )
            submit_budget_consumed_count = 0
            # D안(2026-08-11 KST) 이후 general lane은 더 이상 AI 판단 전에
            # slot을 예약하지 않으므로 항상 0이다 — HP-무관 SUBMIT_BUDGET_TRACE
            # lane_enter 로그의 기존 필드 형식만 유지하기 위해 남겨둔다.
            general_submit_inflight_count = 0
            # held_position REDUCE/EXIT sell은 위험 축소 목적이므로
            # 일반 BUY lane과 분리하고, cycle cap 없이 같은 symbol 중복만 막는다.
            held_position_sell_cycle_count = 0
            held_position_sell_cycle_symbols: set[str] = set()
            _general_submit_lock = asyncio.Lock()
            # D안 Pass 1.5/Pass 2용 — 이번 cycle에서 actionable(BUY/APPROVE)로
            # 확정된 general lane 후보(메모리 한정, DB schema 변경 없음).
            pending_general_candidates: list[dict[str, object]] = []
            # FDC 실제 dispatch 대기(2026-08-27 2차 리뷰 보정) — held_position
            # REDUCE/SELL lane에서 quota reservation이 필요한 job의 재개
            # 정보. gather() 이후 post-gather dispatcher(_run_fdc_actual_
            # dispatch_phase())가 이 리스트를 소비한다.
            pending_fdc_dispatch_jobs: list[dict[str, object]] = []

            async def _process_one(item: object, item_index: int) -> dict[str, object]:
                """Process a single universe item with semaphore concurrency cap."""
                nonlocal submit_budget_consumed_count
                nonlocal general_submit_inflight_count
                nonlocal held_position_sell_cycle_count
                nonlocal held_position_sell_cycle_symbols
                async with sem:
                    item_source_type = getattr(item, "source_type", "core")

                    # SUBMIT_BUDGET_TRACE: symbol이 submit lane 판정에 들어가기
                    # 직전의 budget/inflight 스냅샷(원인 추적 전용, 판정 로직에는
                    # 영향을 주지 않는다).
                    _lane_enter_effective_count = (
                        submit_budget_consumed_count + general_submit_inflight_count
                    )
                    logger.info(
                        "SUBMIT_BUDGET_TRACE lane_enter cycle=%d symbol=%s "
                        "source_type=%s submit=%s dry_run=%s "
                        "allow_general_submit=%s max_general_submits_this_cycle=%d "
                        "submit_budget_consumed_count=%d "
                        "general_submit_inflight_count=%d "
                        "effective_general_submit_count=%d "
                        "held_position_lane_bypass=%s",
                        cycle_count, item.symbol, item_source_type, submit, dry_run,
                        allow_general_submit, max_general_submits_this_cycle,
                        submit_budget_consumed_count, general_submit_inflight_count,
                        _lane_enter_effective_count,
                        item_source_type == "held_position",
                    )

                    async def _execute_symbol_cycle(
                        *,
                        symbol_submit: bool,
                        symbol_dry_run: bool,
                        symbol_dry_run_reason: str | None,
                        remaining_general_buy_budget: int | None,
                        defer_actionable_for_pass2: bool = False,
                        pending_candidates_sink: list[dict[str, object]] | None = None,
                    ) -> dict[str, object]:
                        try:
                            return await _run_one_cycle(
                                cycle=cycle_count,
                                submit=symbol_submit,
                                dry_run=symbol_dry_run,
                                output=output,
                                symbol=item.symbol,
                                market=item.market,
                                source_type=item.source_type,
                                market_segment=getattr(item, "market_segment", None),
                                index_memberships=tuple(
                                    getattr(item, "index_memberships", ()) or ()
                                ),
                                dry_run_reason=symbol_dry_run_reason,
                                remaining_general_buy_budget=remaining_general_buy_budget,
                                runtime=runtime,
                                cycle_precheck=cycle_precheck,
                                universe_anchor=universe_anchor,
                                decision_cycle_id=cycle_decision_cycle_id,
                                deterministic_trigger_override=(
                                    cycle_deterministic_trigger_overrides.get(item.symbol)
                                ),
                                r3b_alpha_percentile=(
                                    cycle_r3b_alpha_percentiles.get(item.symbol)
                                ),
                                defer_actionable_for_pass2=defer_actionable_for_pass2,
                                pending_candidates_sink=pending_candidates_sink,
                                cycle_index=item_index,
                                pending_fdc_dispatch_sink=pending_fdc_dispatch_jobs,
                            )
                        except Exception as exc:
                            logger.exception(
                                "Cycle %d symbol=%s:%s: unexpected error in parallel processing: %s",
                                cycle_count, item.symbol, item.market, exc,
                            )
                            return {
                                "status": "ERROR",
                                "symbol": item.symbol,
                                "market": item.market,
                                "error": str(exc),
                                "duration_seconds": 0.0,
                            }

                    if submit and not dry_run and item_source_type != "held_position":
                        # D안 Pass 1(2026-08-11 KST): 예약 없이 분석만 수행한다.
                        # budget 확인/소비는 이 함수 밖(cycle 메인 루프의
                        # Pass 1.5/Pass 2)에서만 일어난다 — 상세 설계는
                        # docs/40_action_plans/submit_budget_two_stage_design_2026-08-11.md.
                        #
                        # 2026-08-12 KST 추가: scheduler가 cycle 시작 **전**에
                        # DB 실측으로 이미 확정한 cycle-level `allow_general_
                        # submit=False`(당일 daily budget이 이 cycle 전체에
                        # 대해 0으로 고정된 상태)인 경우에만 예외적으로
                        # `remaining_general_buy_budget=0`을 넘겨 pre_ai_gate의
                        # 기존 GENERAL_BUY_BUDGET_EXHAUSTED 분기를 열어
                        # assemble() 호출 전에 차단한다. `allow_general_submit`은
                        # symbol별로 변하는 동적 값이 아니라 이 cycle 전체에
                        # 대해 이미 고정된 상수이므로, D안이 제거한 "cycle 내
                        # 동시 경합 phantom 차단"을 재도입하지 않는다 — 상세
                        # 근거는 위 설계 문서 "12. AI 토큰 낭비 방지" 참조.
                        result = await _execute_symbol_cycle(
                            symbol_submit=False,
                            symbol_dry_run=False,
                            symbol_dry_run_reason=None,
                            remaining_general_buy_budget=(
                                0 if not allow_general_submit else None
                            ),
                            defer_actionable_for_pass2=True,
                            pending_candidates_sink=pending_general_candidates,
                        )
                        if (
                            result.get("status") == "SKIPPED"
                            and result.get("error_phase") == "pre_ai_gate"
                        ):
                            # allow_general_submit=False로 pre_ai_gate가
                            # assemble() 이전에 차단한 경우 — "analysis_
                            # complete"는 분석이 실제로 수행됐다는 뜻이므로
                            # 오해를 막기 위해 별도 이벤트로 남긴다.
                            logger.info(
                                "SUBMIT_PIPELINE_TRACE pre_ai_skipped cycle=%d symbol=%s "
                                "source_type=%s stop_reason=%s duration_seconds=%s",
                                cycle_count, item.symbol, item_source_type,
                                result.get("stop_reason"),
                                result.get("duration_seconds"),
                            )
                        else:
                            logger.info(
                                "SUBMIT_PIPELINE_TRACE analysis_complete cycle=%d symbol=%s "
                                "source_type=%s decision_type=%s trade_decision_id=%s "
                                "pending_pass2=%s duration_seconds=%s",
                                cycle_count, item.symbol, item_source_type,
                                result.get("decision_type"), result.get("trade_decision_id"),
                                result.get("status") == "PENDING_PASS2",
                                result.get("duration_seconds"),
                            )
                    else:
                        lane_decision = evaluate_symbol_submit_lane(
                            submit=submit,
                            dry_run=dry_run,
                            allow_general_submit=allow_general_submit,
                            source_type=item_source_type,
                            submit_budget_consumed_count=submit_budget_consumed_count,
                            max_general_submits_this_cycle=max_general_submits_this_cycle,
                            held_position_sell_cycle_count=held_position_sell_cycle_count,
                            held_position_sell_cycle_symbols=held_position_sell_cycle_symbols,
                            symbol=item.symbol,
                        )
                        result = await _execute_symbol_cycle(
                            symbol_submit=lane_decision.submit,
                            symbol_dry_run=lane_decision.dry_run,
                            symbol_dry_run_reason=lane_decision.dry_run_reason,
                            remaining_general_buy_budget=max(
                                0,
                                max_general_submits_this_cycle - submit_budget_consumed_count,
                            ),
                        )

                    # HP sell block 이유 로깅 (explainability)
                    is_held_position_item = item_source_type == "held_position"
                    if is_held_position_item and not lane_decision.submit and submit and not dry_run:
                        reasons = []
                        if item.symbol in held_position_sell_cycle_symbols:
                            reasons.append("symbol_duplicate")
                        if reasons:
                            logger.info(
                                "HP sell block: symbol=%s reasons=%s",
                                item.symbol, ",".join(reasons),
                            )

                    status = result.get("status", "UNKNOWN")
                    if status in ("SUBMITTED", "RECONCILE_REQUIRED"):
                        async with _general_submit_lock:
                            # 3중 조건: source_type == held_position AND decision_type in (reduce, exit) AND side == sell
                            result_decision_type = str(result.get("decision_type", "")).lower()
                            result_side = str(result.get("side", "")).lower()
                            is_held_position_sell = is_held_position_sell_path(
                                source_type=getattr(item, "source_type", "core"),
                                decision_type=result_decision_type,
                                side=result_side,
                            )
                            if is_held_position_sell:
                                # held_position sell은 일일 상한 없음 (위험 축소 목적).
                                # cycle 내 중복 방지용 카운터만 증가.
                                held_position_sell_cycle_count += 1
                                held_position_sell_cycle_symbols.add(item.symbol)

                    # Output per-symbol result
                    if output == "json":
                        print(json.dumps(result, ensure_ascii=False))
                    else:
                        precheck_str = ""
                        precheck_data = result.get("precheck")
                        if isinstance(precheck_data, dict):
                            h = precheck_data.get("health_status", "?")
                            precheck_str = f" [health={h}]"
                        logger.info(
                            "Cycle %d/%s symbol=%s:%s complete — status=%s duration=%.2fs%s",
                            cycle_count,
                            "∞" if max_cycles == 0 else str(max_cycles),
                            item.symbol,
                            item.market,
                            status,
                            result.get("duration_seconds", 0),
                            precheck_str,
                        )

                    return result

            # Process ALL symbols concurrently with semaphore cap
            coros = [
                _process_one(item, idx) for idx, item in enumerate(universe)
            ]
            cycle_results: list[dict[str, object]] = list(
                await asyncio.gather(*coros)
            )

            # ── FDC 실제 dispatch post-gather phase(2026-08-27 2차 리뷰
            # 보정 — PR #359) ────────────────────────────────────────
            # symbol asyncio.gather()가 끝난 뒤에만 실행된다 — quota
            # reservation 대기가 gather()를 막지 않는다는 계약을 여기서
            # 보장한다. FDC_ACTUAL_DISPATCH_ENABLED가 꺼져 있으면
            # pending_fdc_dispatch_jobs는 항상 빈 리스트이므로(해당
            # lane에 진입조차 하지 않음) 이 블록은 사실상 no-op이다.
            if pending_fdc_dispatch_jobs:
                _phase_deadline = (
                    _cycle_start_monotonic
                    + _DECISION_SUBPROCESS_TIMEOUT_CEILING_SECONDS
                    - _FDC_DISPATCH_PHASE_SAFETY_MARGIN_SECONDS
                )
                fdc_dispatch_results = await _run_fdc_actual_dispatch_phase(
                    pending_fdc_dispatch_jobs,
                    runtime=runtime,
                    cycle_precheck=cycle_precheck,
                    output=output,
                    cycle_count=cycle_count,
                    phase_deadline_monotonic=_phase_deadline,
                )
                cycle_results.extend(fdc_dispatch_results)
                logger.info(
                    "Cycle %d FDC actual-dispatch phase complete: jobs=%d "
                    "results=%d",
                    cycle_count, len(pending_fdc_dispatch_jobs),
                    len(fdc_dispatch_results),
                )

            # FDC cycle-scoped batch queue lifecycle shadow(Phase 1, 2차
            # 보정) — 사이클의 모든 심볼 처리가 끝난 직후, Pass 2가
            # cycle_results를 변형하기 전에 FDC-ready 이벤트를 정렬·재생한다.
            # Pass 2는 이미 확정된 actionable 후보의 실제 제출만 다루고
            # FDC를 다시 호출하지 않으므로, 이 시점 이후에는 이번 사이클의
            # FDC-ready 이벤트가 더 늘어나지 않는다.
            try:
                await _replay_fdc_ready_shadow_events_for_cycle(
                    cycle_results, cycle_count=cycle_count,
                )
            except Exception:
                logger.warning(
                    "fdc_batch_queue_lifecycle_shadow replay call failed: cycle=%d",
                    cycle_count,
                    exc_info=True,
                )

            # ── D안 Pass 1.5 + Pass 2 (2026-08-11 KST) ──────────────────────
            # Pass 1(위 _process_one)은 budget과 무관하게 분석만 수행했다.
            # 여기서 actionable(BUY/APPROVE) 후보만 모아 symbol 단위로
            # dedupe하고, 명시적 우선순위로 정렬한 뒤, cycle budget이 남아
            # 있는 동안만 순차적으로 실제 제출한다. 상세 설계:
            # docs/40_action_plans/submit_budget_two_stage_design_2026-08-11.md
            if pending_general_candidates:
                submit_budget_consumed_count = await _run_general_lane_pass2(
                    pending_general_candidates,
                    cycle_results=cycle_results,
                    cycle_count=cycle_count,
                    max_general_submits_this_cycle=max_general_submits_this_cycle,
                    submit_budget_consumed_count=submit_budget_consumed_count,
                    runtime=runtime,
                    output=output,
                    decision_cycle_id=cycle_decision_cycle_id,
                )

            try:
                await _apply_core_risk_off_shadow_projection_for_cycle(cycle_results)
            except Exception:
                logger.warning(
                    "Cycle %d: failed to apply core risk-off shadow projection",
                    cycle_count,
                    exc_info=True,
                )
            results.extend(cycle_results)

            # ── Drain T3 background tasks ────────────────────────────────────
            # Wait for all fire-and-forget T3 pipelines to complete so that
            # persisted events are available for the next cycle's freshness check.
            if _active_t3_tasks:
                pending = list(_active_t3_tasks)
                _active_t3_tasks.clear()
                await asyncio.gather(*pending, return_exceptions=True)
                logger.debug(
                    "Drained %d T3 background task(s) after cycle %d.",
                    len(pending), cycle_count,
                )

            # Aggregate success/fail counts from parallel results
            for r in cycle_results:
                s = r.get("status", "UNKNOWN")
                if s in ("SUBMITTED", "DRY_RUN", "SKIPPED"):
                    total_success += 1
                else:
                    total_fail += 1

            # Wait for next cycle (or shutdown)
            if max_cycles > 0 and cycle_count >= max_cycles:
                break

            logger.debug(
                "Waiting %d seconds before next cycle …",
                interval,
            )
            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(),
                    timeout=interval,
                )
                # Shutdown event was set during sleep
                break
            except asyncio.TimeoutError:
                pass

    # ── Runtime context exit: pool/agents 정리 ──────────────────────────
    # postgres_runtime()의 __aexit__에서 shutdown_postgres_runtime() 호출

    # ── Final summary ──
    total_duration = time.monotonic() - loop_start
    summary = _build_aggregate_summary(
        results,
        total_duration,
        universe=universe,
        universe_anchor=universe_anchor,
    )

    if output == "json":
        print(json.dumps(summary, ensure_ascii=False))
    else:
        logger.info("=" * 60)
        logger.info("Paper decision loop complete.")
        logger.info("  total cycles : %d", summary["total_cycles"])
        logger.info("  success      : %d", summary["success"])
        logger.info("  skipped      : %d", summary["skipped"])
        logger.info("  error        : %d", summary["error"])
        if summary["total_cycles"] > 0:
            logger.info("  success rate : %.1f%%", summary["success_rate"])
        logger.info("  total time   : %.1fs", summary["total_duration_seconds"])
        logger.info("=" * 60)

    return 0 if total_fail == 0 else 1


# ── CLI ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Paper continuous decision loop — run orchestrator "
                    "assemble/submit repeatedly for paper operations.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help=f"Seconds between decision cycles (default: {DEFAULT_INTERVAL_SECONDS}s, "
             f"overridable via {ENV_INTERVAL}).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of cycles to run (0 = infinite, default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run assemble + sizing only — no broker submit.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        default=True,
        help="Run full assemble → submit pipeline (default).",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format: ``text`` (human-readable) or ``json`` (machine-readable).",
    )
    parser.add_argument(
        "--allow-general-submit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow general/core submit lane. Disable to keep only held_position sell submits.",
    )
    parser.add_argument(
        "--max-general-submits-this-cycle",
        type=int,
        default=1,
        help="Maximum number of general/core or market_overlay submits to allow in this cycle.",
    )
    parser.add_argument(
        "--decision-cycle-id",
        type=str,
        default=None,
        help=(
            "Stage A-1b(정책평가 인프라, 2026-08-20): 관측성 전용 cycle "
            "식별자. run_ops_scheduler.py가 cycle 시작 시 이미 알고 있는 "
            "값(run_date+due_at 기반)을 넘겨준다 — guardrail_evaluations에 "
            "저장돼 같은 cycle의 pre-AI gate 스킵/Pass 2 drop을 함께 "
            "묶어 조회할 수 있게 한다. 판정 로직에는 관여하지 않으며, "
            "생략하면(단독/수동 실행) NULL로 저장된다."
        ),
    )
    return parser.parse_args(argv)


def _load_env() -> None:
    """Load .env if python-dotenv is available.

    Existing environment variables are not overwritten, which keeps Docker or
    manually exported runtime settings authoritative.
    """
    if load_dotenv is not None:
        load_dotenv()


def main(argv: list[str] | None = None) -> int:
    """Entry point for the continuous decision loop.

    .. note::
       This script is named ``run_decision_loop`` for historical
       reasons (it was introduced during the paper-trading milestone),
       but the core runtime logic is **mode-agnostic**.  The same
       ``assemble()`` → sizing → submit pipeline works identically
       for both paper and live modes.  Only the broker credentials /
       endpoint / rate-limit configuration (driven by ``AppSettings``)
       differ between environments.

       To switch to live mode, change the following env vars:
       ``KIS_ENV=live``, ``KIS_APP_KEY`` / ``KIS_APP_SECRET`` for live,
       ``KIS_ACCOUNT_NUMBER`` for live, ``KIS_BASE_URL`` / ``KIS_WS_URL``
       for live endpoints, and ``KIS_REAL_REST_RPS`` for live rate limits.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] paper-decision-loop: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # SIGTERM 핸들러 등록은 _install_signal_handlers()에서 loop.add_signal_handler()로 처리됨

    _load_env()

    args = _parse_args(argv)

    interval = args.interval or _read_interval()
    max_cycles = args.count

    # Validate conflicting options
    if args.dry_run and args.submit:
        # --submit is the default; --dry-run overrides
        logger.info("--dry-run overrides --submit. Running assemble + sizing only.")
        submit = False
        dry_run = True
    elif args.dry_run:
        submit = False
        dry_run = True
    else:
        submit = args.submit
        dry_run = False

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        exit_code = loop.run_until_complete(
            _run_loop(
                interval=interval,
                max_cycles=max_cycles,
                submit=submit,
                dry_run=dry_run,
                allow_general_submit=args.allow_general_submit,
                max_general_submits_this_cycle=max(0, args.max_general_submits_this_cycle),
                output=args.output,
                decision_cycle_id=args.decision_cycle_id,
            )
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting.")
        exit_code = 0
    finally:
        try:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
