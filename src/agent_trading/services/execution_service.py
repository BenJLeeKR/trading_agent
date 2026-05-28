"""Execution pipeline service — handles the order execution lifecycle.

Design rules
------------
1. Owns execution-specific state (quote circuit breaker, sell guard resolver,
   snapshot freshness threshold).
2. No AI agent references — all AI/decision logic stays in
   ``DecisionOrchestratorService``.
3. ``phase_trace`` is always an explicit parameter, never an instance attribute.
4. Uses ``self._repos`` for data access (passed in via constructor).
5. No domain entity imports outside ``TYPE_CHECKING`` — uses only what's
   needed at runtime.
"""

from __future__ import annotations

import asyncio
import logging
import time as time_module
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    ExecutionAttemptEntity,
    GuardrailEvaluationEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus
from agent_trading.domain.models import Quote, SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import OrderSyncService
from agent_trading.services.sizing_engine import SizingInputs, calculate_sizing
from agent_trading.services.sell_guard import AvailableSellQtyResolver, SellAvailability
from agent_trading.services.common_types import (
    AccountSnapshotFreshness,
    OrderIntent,
    PhaseTraceEntry,
    SubmitResult,
    phase_trace_to_dicts,
)
from agent_trading.services.translation import (
    build_submit_order_request_from_decision,
    decimal_or_none,
)

if TYPE_CHECKING:
    from agent_trading.domain.entities import (
        CashBalanceSnapshotEntity,
        ConfigVersionEntity,
        DecisionContextEntity,
        ExecutionAttemptEntity,
        ExternalEventEntity,
        InstrumentEntity,
        PositionSnapshotEntity,
        RiskLimitSnapshotEntity,
        TradeDecisionEntity,
    )
    from agent_trading.services.ai_agents.schemas import (
        ExecutionPreferences,
        SizingHint,
    )

logger = logging.getLogger(__name__)

# Phase 5.5: post-submit sync timeout (seconds)
_PHASE55_SYNC_TIMEOUT: int = 5

# Phase 1.5 quote circuit breaker (EXE-002)
_CIRCUIT_BREAKER_THRESHOLD = 3  # 연속 실패 횟수 → 서킷 오픈
_CIRCUIT_BREAKER_COOLDOWN = 60  # 서킷 오픈 지속 시간(초)
_QUOTE_CACHE_TTL = 180  # quote 캐시 TTL(초) — cycle-local cache: submit mode ~120초 커버


__all__: list[str] = [
    "ExecutionService",
]


# ======================================================================
# ExecutionService
# ======================================================================


class ExecutionService:
    """Handles the execution pipeline: sizing → guard → translate → create → submit.

    Owns execution-specific state (quote circuit breaker, sell guard resolver,
    snapshot freshness threshold).  Does **not** own AI agent state or decision
    pipeline state.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        *,
        stale_threshold_seconds: int = 900,
        # --- Phase 5.5: post-submit sync ---
        sync_service: OrderSyncService | None = None,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self._repos = repos
        self._stale_threshold_seconds = stale_threshold_seconds
        # --- Phase 5.5 ---
        self._sync_service = sync_service
        self._snapshot_refresh_cb = snapshot_refresh_cb
        # --- Phase 1.5+: Duplicate Sell Guard ---
        self._sell_guard_resolver = AvailableSellQtyResolver(repos=repos)
        # --- EXE-002: quote circuit breaker + cache state ---
        self._quote_failures: dict[str, int] = {}  # symbol → 연속 실패 횟수
        self._quote_skip_until: dict[str, datetime] = {}  # symbol → 서킷 오픈 deadline
        self._quote_cache: dict[str, tuple[Quote, datetime]] = {}  # symbol → (quote, cached_at)

    # ------------------------------------------------------------------
    # P2.1: _finalize_attempt — EA status update consolidation
    # ------------------------------------------------------------------

    async def _finalize_attempt(
        self,
        attempt_id: UUID | None,
        status: str,
        *,
        stop_phase: str = "",
        stop_reason: str = "",
        order_request_id: UUID | None = None,
        phase_trace: list[PhaseTraceEntry],
    ) -> None:
        """Consolidated EA ``update_status()`` call.

        Wraps the 9-site repetition of:

        .. code-block:: python

            await self._repos.execution_attempts.update_status(
                _attempt_id, status,
                stop_phase=..., stop_reason=...,
                phase_trace=phase_trace_to_dicts(_phase_trace),
                order_request_id=...,
                completed_at=datetime.now(timezone.utc),
            )

        into a single method call.

        When ``attempt_id is None``, this is a no-op (EA creation may fail
        non-fatally and the pipeline continues with ``attempt_id=None``).
        """
        if attempt_id is None:
            return
        try:
            await self._repos.execution_attempts.update_status(
                attempt_id,
                status,
                stop_phase=stop_phase,
                stop_reason=stop_reason,
                phase_trace=phase_trace_to_dicts(tuple(phase_trace)),
                order_request_id=order_request_id,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception:
            logger.warning(
                "Failed to finalize execution_attempt_id=%s status=%s (non-fatal)",
                attempt_id, status,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # P2.3: _resolve_quote — quote resolution with circuit breaker
    # ------------------------------------------------------------------

    async def _resolve_quote(
        self,
        symbol: str,
        market: str,
        broker: BrokerAdapter,
        *,
        _add_phase: Callable[[str, str], None],
        is_hp_sell: bool = False,
    ) -> tuple[Quote | dict[str, object], Decimal | None]:
        """Resolve a live broker quote with circuit breaker + cache.

        Returns ``(quote, reference_price)``.

        When ``is_hp_sell`` is True (held-position REDUCE/EXIT SELL), the
        quote is bypassed entirely and returns empty quote with ``None``
        reference price, avoiding 10s per-symbol broker overhead.
        """
        if is_hp_sell:
            logger.info(
                "HP_SELL_QUOTE_BYPASS: symbol=%s skipping broker.get_quote(), "
                "using smoke price fallback",
                symbol,
            )
            return {}, None

        _add_phase(f"quote_resolution/{symbol}", "start")
        logger.info(
            "PHASE_TRACE: symbol=%s phase=quote_resolution start",
            symbol,
        )

        reference_price: Decimal | None = None

        # EXE-002: circuit breaker check
        skip_until = self._quote_skip_until.get(symbol)
        if skip_until and datetime.now(timezone.utc) < skip_until:
            logger.info(
                "PHASE_TRACE 1.5 quote_circuit_breaker_skip/%s", symbol,
            )
            _add_phase(f"quote_resolution/{symbol}", "circuit_breaker_skip")
            return {}, None

        # EXE-002: cache check
        cached = self._quote_cache.get(symbol)
        quote: Quote | None = None
        if cached is not None:
            cached_quote, cached_at = cached
            if (datetime.now(timezone.utc) - cached_at).total_seconds() < _QUOTE_CACHE_TTL:
                quote = cached_quote
                logger.info(
                    "PHASE_TRACE 1.5 quote_cache_hit/%s", symbol,
                )
                _add_phase(f"quote_resolution/{symbol}", "cache_hit")
            else:
                del self._quote_cache[symbol]

        if quote is None:  # 캐시 미스 → 실제 호출 (with retry + backoff)
            MAX_RETRIES = 2
            BACKOFF_BASE = 0.5
            BACKOFF_MAX = 5.0
            last_exc: Exception | None = None

            for attempt in range(MAX_RETRIES):
                try:
                    quote = await asyncio.wait_for(
                        broker.get_quote(symbol, market),
                        timeout=10.0,
                    )
                    # 캐시 저장
                    self._quote_cache[symbol] = (quote, datetime.now(timezone.utc))
                    # 실패 카운트 리셋
                    self._quote_failures.pop(symbol, None)
                    logger.info(
                        "PHASE_TRACE: symbol=%s phase=quote_resolution done quote=%s",
                        symbol, str(quote),
                    )
                    _add_phase(f"quote_resolution/{symbol}", "ok")
                    break  # 성공 → retry 루프 탈출
                except (asyncio.TimeoutError, Exception) as exc:
                    last_exc = exc
                    # EGW00201 (KIS rate limit)인 경우에만 retry
                    if "EGW00201" in str(exc) and attempt < MAX_RETRIES - 1:
                        wait = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
                        logger.warning(
                            "KIS rate limit (EGW00201) for %s, retry %d/%d in %.1fs",
                            symbol, attempt + 1, MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        # EGW00201이 아니거나 마지막 시도 실패 → 루프 탈출 후 fallback
                        break

            if quote is None:
                # 모든 retry 실패 → 실패 추적 + fallback quote
                failures = self._quote_failures.get(symbol, 0) + 1
                self._quote_failures[symbol] = failures
                if failures >= _CIRCUIT_BREAKER_THRESHOLD:
                    self._quote_skip_until[symbol] = datetime.now(timezone.utc) + timedelta(
                        seconds=_CIRCUIT_BREAKER_COOLDOWN
                    )
                    logger.warning(
                        "CADENCE_TRACE quote_circuit_breaker_open symbol=%s "
                        "failures=%d cooldown=%ds",
                        symbol, failures, _CIRCUIT_BREAKER_COOLDOWN,
                    )
                logger.warning(
                    "Phase 1.5: broker quote timeout or error for symbol=%s — "
                    "proceeding with best-effort fallback (empty quote).",
                    symbol,
                    exc_info=True,
                )
                quote = Quote(
                    symbol=symbol,
                    market=market,
                    bid=None,
                    ask=None,
                    last=None,
                    as_of=datetime.now(timezone.utc),
                )
                _add_phase(f"quote_resolution/{symbol}", "error")

        # Priority: last > ask > bid
        if quote is not None:
            if quote.last is not None and quote.last > 0:
                reference_price = quote.last
            elif quote.ask is not None and quote.ask > 0:
                reference_price = quote.ask
            elif quote.bid is not None and quote.bid > 0:
                reference_price = quote.bid
            if reference_price is not None:
                logger.info(
                    "Phase 1.5: resolved reference_price=%s from quote "
                    "(last=%s ask=%s bid=%s) for symbol=%s MARKET order",
                    reference_price, quote.last, quote.ask, quote.bid,
                    symbol,
                )

        return quote or {}, reference_price

    # ------------------------------------------------------------------
    # P1.3: _check_account_snapshot_freshness
    # ------------------------------------------------------------------

    async def _check_account_snapshot_freshness(
        self, account_id: UUID
    ) -> AccountSnapshotFreshness:
        """Check whether a specific account's snapshots are fresh.

        Returns an ``AccountSnapshotFreshness`` summary for the given
        ``account_id``.  Uses the same ``_stale_threshold_seconds`` as the
        run-level summary.

        **Zero-position account policy**: if ``list_latest_by_account()``
        returns an empty list, the positions are considered fresh *iff* a
        cash snapshot exists and is fresh (because the sync function
        fetches cash and positions together).
        """
        now = datetime.now(timezone.utc)

        # 1. Cash snapshot
        cash_snapshot = await self._repos.cash_balance_snapshots.get_latest_by_account(
            account_id
        )
        if cash_snapshot is None:
            return AccountSnapshotFreshness(
                account_id=account_id,
                latest_cash_snapshot_at=None,
                latest_position_snapshot_at=None,
                is_cash_stale=True,
                is_position_stale=True,
                is_stale=True,
            )

        is_cash_stale = (
            now - cash_snapshot.snapshot_at
        ).total_seconds() > self._stale_threshold_seconds

        # 2. Position snapshots
        position_snapshots = (
            await self._repos.position_snapshots.list_latest_by_account(account_id)
        )
        latest_position_snapshot_at: datetime | None = None
        is_position_stale = False

        if position_snapshots:
            latest_position_snapshot_at = max(s.snapshot_at for s in position_snapshots)
            is_position_stale = (
                now - latest_position_snapshot_at
            ).total_seconds() > self._stale_threshold_seconds

        # Zero-position account policy: empty positions + cash fresh = pass
        is_stale = is_cash_stale or is_position_stale
        if is_stale:
            logger.warning(
                "Snapshot freshness check: account_id=%s "
                "cash_stale=%s (snapshot_at=%s, age=%.1fs) "
                "pos_stale=%s (latest_snapshot_at=%s) "
                "threshold=%ds",
                account_id,
                is_cash_stale,
                cash_snapshot.snapshot_at,
                (now - cash_snapshot.snapshot_at).total_seconds(),
                is_position_stale,
                latest_position_snapshot_at,
                self._stale_threshold_seconds,
            )
        return AccountSnapshotFreshness(
            account_id=account_id,
            latest_cash_snapshot_at=cash_snapshot.snapshot_at,
            latest_position_snapshot_at=latest_position_snapshot_at,
            is_cash_stale=is_cash_stale,
            is_position_stale=is_position_stale,
            is_stale=is_stale,
        )

    # ------------------------------------------------------------------
    # _build_sizing_inputs (moved from DecisionOrchestratorService)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_sizing_inputs(
        intent: OrderIntent,
        reference_price: Decimal | None = None,
    ) -> SizingInputs:
        """Build ``SizingInputs`` from an ``OrderIntent``.

        Extracts position, cash, NAV, and config data from the assembled
        context and maps them to the sizing engine's input format.

        **Key resolution order** (nested ``risk.*`` / ``execution.*`` first,
        then legacy flat key fallback):

        * ``max_single_position_pct`` ← ``risk.max_single_position_pct``
          | ``max_position_size`` (legacy)
        * ``min_cash_buffer_pct``    ← ``risk.min_cash_buffer_pct``
          | ``min_cash_buffer_pct`` (legacy flat)
        * ``max_order_value``        ← ``execution.max_order_value``
          | ``max_order_value`` (legacy flat)
        """
        ctx = intent.context
        ai = intent.ai_backend_inputs
        req = intent.request

        config = ctx.config_version.config_json if ctx.config_version else {}
        risk = config.get("risk", {})
        execution = config.get("execution", {})

        pos_qty = ctx.position_snapshot.quantity if ctx.position_snapshot else None
        pos_avg_price = ctx.position_snapshot.average_price if ctx.position_snapshot else None
        available_cash = ctx.cash_balance_snapshot.available_cash if ctx.cash_balance_snapshot else None
        orderable_amount = ctx.cash_balance_snapshot.orderable_amount if ctx.cash_balance_snapshot else None
        nav = ctx.risk_limit_snapshot.nav if ctx.risk_limit_snapshot else None
        # Fallback: risk_limit_snapshot이 없으면 cash_balance_snapshot.total_asset을 NAV로 사용
        if nav is None and ctx.cash_balance_snapshot is not None and ctx.cash_balance_snapshot.total_asset is not None:
            nav = ctx.cash_balance_snapshot.total_asset
            logger.warning(
                "risk_limit_snapshot not available; using cash_balance_snapshot.total_asset as NAV fallback. "
                "account_id=%s nav=%s",
                ctx.cash_balance_snapshot.account_id, nav,
            )

        # ── Resolve keys with legacy flat-key fallback ──────────────────
        max_single_position_pct = decimal_or_none(
            risk.get("max_single_position_pct")
            or config.get("max_position_size")
        )
        min_cash_buffer_pct = decimal_or_none(
            risk.get("min_cash_buffer_pct")
            or config.get("min_cash_buffer_pct")
        )
        max_order_value = decimal_or_none(
            execution.get("max_order_value")
            or config.get("max_order_value")
        )

        # ── Operational visibility logging ──────────────────────────────
        max_pct_source = (
            "risk.max_single_position_pct"
            if risk.get("max_single_position_pct")
            else "max_position_size (legacy)"
        )
        cash_buffer_source = (
            "risk.min_cash_buffer_pct"
            if risk.get("min_cash_buffer_pct")
            else "min_cash_buffer_pct (legacy flat)"
        )
        max_ov_source = (
            "execution.max_order_value"
            if execution.get("max_order_value")
            else "max_order_value (legacy flat)"
        )

        # ── Cash source logging (operational traceability) ──
        if orderable_amount is not None:
            logger.info(
                "Cash source: orderable_amount=%s (preferred) | "
                "available_cash=%s (fallback)",
                orderable_amount, available_cash,
            )
        else:
            logger.info(
                "Cash source: available_cash=%s (fallback, orderable_amount not available)",
                available_cash,
            )

        logger.info(
            "SizingInputs: max_single_position_pct=%s (src=%s) "
            "min_cash_buffer_pct=%s (src=%s) "
            "max_order_value=%s (src=%s) nav=%s",
            max_single_position_pct, max_pct_source,
            min_cash_buffer_pct, cash_buffer_source,
            max_order_value, max_ov_source,
            nav,
        )

        return SizingInputs(
            decision_type=ai.decision_type,
            side=req.side,
            requested_quantity=req.quantity,
            requested_price=req.price,
            reference_price=reference_price,
            sizing_hint=ai.sizing_hint,
            current_position_qty=pos_qty,
            current_position_avg_price=pos_avg_price,
            available_cash=available_cash,
            orderable_amount=orderable_amount,
            nav=nav,
            max_single_position_pct=max_single_position_pct,
            min_cash_buffer_pct=min_cash_buffer_pct,
            max_order_value=max_order_value,
            min_order_qty=decimal_or_none(execution.get("min_order_qty")),
            max_order_qty=decimal_or_none(execution.get("max_order_qty")),
        )

    # ------------------------------------------------------------------
    # Main pipeline entry point
    # ------------------------------------------------------------------

    async def run_execution_pipeline(
        self,
        intent: OrderIntent,
        trade_decision_id: UUID | None,
        request: SubmitOrderRequest,
        order_manager: OrderManager,
        broker: BrokerAdapter,
        *,
        actor_type: str = "system",
        actor_id: str = "decision_orchestrator",
        _add_phase: Callable[[str, str], None],
        _phase_trace: list[PhaseTraceEntry],
    ) -> SubmitResult:
        """Execution pipeline: sizing → guard → translate → create → submit.

        Called by ``DecisionOrchestratorService.assemble_and_submit()`` after
        the decision pipeline has produced ``(intent, trade_decision_id)``.
        """
        _symbol = intent.request.symbol

        # ── ExecutionAttempt 생성 (running) ──
        # (moved from DecisionOrchestratorService._run_decision_pipeline)
        attempt_id: UUID | None = None
        if trade_decision_id is not None and intent.decision_context_id is not None:
            try:
                _now = datetime.now(timezone.utc)
                attempt = ExecutionAttemptEntity(
                    execution_attempt_id=uuid4(),
                    trade_decision_id=trade_decision_id,
                    decision_context_id=intent.decision_context_id,
                    status="running",
                    started_at=_now,
                    created_at=_now,
                )
                saved = await self._repos.execution_attempts.add(attempt)
                attempt_id = saved.execution_attempt_id
                logger.info(
                    "[ATTEMPT_CREATED] execution_attempt_id=%s trade_decision_id=%s",
                    attempt_id,
                    trade_decision_id,
                )
            except Exception:
                logger.warning(
                    "ExecutionAttempt creation failed (non-fatal). "
                    "trade_decision_id=%s",
                    trade_decision_id,
                    exc_info=True,
                )
                attempt_id = None

        # ── Phase 1.5: deterministic sizing engine ──
        logger.info(
            "Phase 1.5: sizing engine — decision_type=%s side=%s quantity=%s",
            intent.ai_backend_inputs.decision_type,
            intent.request.side,
            intent.request.quantity,
        )

        # Resolve reference_price for MARKET orders from live broker quote.
        reference_price: Decimal | None = None

        # Held position sell (REDUCE/EXIT SELL): quote is optional reference only.
        _is_hp_sell = (
            intent.request.side == OrderSide.SELL
            and intent.ai_backend_inputs.decision_type in ("REDUCE", "EXIT")
        )

        if _is_hp_sell:
            logger.info(
                "HP_SELL_QUOTE_BYPASS: symbol=%s skipping broker.get_quote(), "
                "using smoke price fallback",
                intent.request.symbol,
            )
            quote: dict[str, object] = {}
        elif intent.request.price is None:
            _resolved_quote, reference_price = await self._resolve_quote(
                intent.request.symbol,
                intent.request.market,
                broker,
                _add_phase=_add_phase,
                is_hp_sell=False,
            )
            quote = _resolved_quote
        else:
            quote = {}

        _sizing_t0 = time_module.monotonic()
        _add_phase(f"sizing/{_symbol}", "start")
        logger.info(
            "PHASE_TRACE symbol=%s phase=sizing_start elapsed_ms=0 status=start",
            _symbol,
        )
        sizing_inputs = self._build_sizing_inputs(intent, reference_price=reference_price)
        sizing_result = calculate_sizing(sizing_inputs)

        _sizing_elapsed = time_module.monotonic() - _sizing_t0
        logger.info(
            "Sizing Phase 1.5: request_qty=%s sizing_qty=%s "
            "applied_constraints=%s skip_reason=%s",
            intent.request.quantity,
            sizing_result.quantity,
            sizing_result.applied_constraints,
            sizing_result.skip_reason or "none",
        )

        # For SELL/REDUCE/EXIT: fallback to request quantity when sizing returns 0.
        effective_qty = sizing_result.quantity
        if effective_qty <= 0 and intent.request.side == OrderSide.SELL:
            req_qty = intent.request.quantity
            if req_qty > 0:
                effective_qty = req_qty
                logger.info(
                    "Phase 1.5: sizing returned 0 for SELL; "
                    "fallback to request quantity=%s (skip_reason=%s)",
                    req_qty,
                    sizing_result.skip_reason,
                )

        if effective_qty <= 0:
            # held_position sell skip audit
            if (intent is not None and intent.request.side == OrderSide.SELL
                    and intent.ai_backend_inputs.decision_type in ("REDUCE", "EXIT")):
                logger.warning(
                    "HELD_POSITION_SELL skipped at sizing: symbol=%s "
                    "decision_type=%s skip_reason=%s trade_decision_id=%s",
                    intent.request.symbol,
                    intent.ai_backend_inputs.decision_type,
                    sizing_result.skip_reason,
                    trade_decision_id,
                )
                _sizing_elapsed_hp = time_module.monotonic() - _sizing_t0
                logger.info(
                    "PHASE_TRACE symbol=%s phase=sizing_skip_held_position elapsed_ms=%d "
                    "status=skip_reason=%s",
                    _symbol, int(_sizing_elapsed_hp * 1000),
                    sizing_result.skip_reason or "unknown",
                )
            logger.info(
                "Phase 1.5 SKIPPED (sizing): reason=%s, trade_decision_id=%s",
                sizing_result.skip_reason,
                trade_decision_id,
            )
            _add_phase(f"sizing/{_symbol}", "skipped")
            await self._finalize_attempt(
                attempt_id, "stopped",
                stop_phase="sizing",
                stop_reason="sizing_rejected",
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                trade_decision_id=trade_decision_id,
                error_message=sizing_result.skip_reason or "Sizing rejected order",
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                is_skipped=True,
                status="SKIPPED",
                error_phase="sizing",
            )

        # Apply sizing result
        if effective_qty != intent.request.quantity:
            sized_request = replace(intent.request, quantity=effective_qty)
            intent = replace(intent, request=sized_request)
            logger.info(
                "Phase 1.5: quantity overridden by sizing — original=%s sized=%s",
                intent.request.quantity,
                effective_qty,
            )

        if sizing_result.applied_constraints:
            logger.info(
                "Phase 1.5: constraints applied=%s sized_quantity=%s",
                sizing_result.applied_constraints,
                sizing_result.quantity,
            )

        _add_phase(f"sizing/{_symbol}", "ok")
        logger.info(
            "PHASE_TRACE symbol=%s phase=sizing_done elapsed_ms=%d status=ok",
            _symbol, int((time_module.monotonic() - _sizing_t0) * 1000),
        )

        # ── Phase 1.5+: Duplicate Sell Guard (SELL only) ──
        _sell_guard_t0 = time_module.monotonic()
        _add_phase(f"sell_guard/{_symbol}", "start")
        logger.info(
            "PHASE_TRACE symbol=%s phase=sell_guard_start elapsed_ms=0 status=start",
            _symbol,
        )
        if intent.request.side == OrderSide.SELL and effective_qty > 0:
            account_id: UUID | None = (
                intent.context.decision_context.account_id
                if intent.context is not None
                and intent.context.decision_context is not None
                else None
            )
            if account_id is not None:
                try:
                    sell_availability: SellAvailability = (
                        await self._sell_guard_resolver.resolve(
                            account_id=account_id,
                            symbol=intent.request.symbol,
                            requested_qty=effective_qty,
                        )
                    )
                    if sell_availability.is_blocked:
                        # held_position sell skip audit
                        if (intent.request.side == OrderSide.SELL
                                and intent.ai_backend_inputs.decision_type in ("REDUCE", "EXIT")):
                            logger.warning(
                                "HELD_POSITION_SELL skipped at sell_guard: symbol=%s "
                                "decision_type=%s reason=%s trade_decision_id=%s",
                                intent.request.symbol,
                                intent.ai_backend_inputs.decision_type,
                                sell_availability.blocking_reason,
                                trade_decision_id,
                            )
                        logger.info(
                            "Phase 1.5+ SELL GUARD BLOCKED: "
                            "symbol=%s requested=%s reason=%s "
                            "trade_decision_id=%s",
                            intent.request.symbol,
                            effective_qty,
                            sell_availability.blocking_reason,
                            trade_decision_id,
                        )
                        _add_phase(f"sell_guard/{_symbol}", "skipped")
                        await self._finalize_attempt(
                            attempt_id, "stopped",
                            stop_phase="sell_guard",
                            stop_reason="sell_guard_blocked",
                            phase_trace=_phase_trace,
                        )
                        return SubmitResult.build(
                            order_intent=intent,
                            trade_decision_id=trade_decision_id,
                            error_message=(
                                sell_availability.blocking_reason
                                or "Sell guard blocked duplicate sell"
                            ),
                            phase_trace=tuple(_phase_trace) if _phase_trace else (),
                            is_skipped=True,
                            status="SKIPPED",
                        )
                    logger.info(
                        "Phase 1.5+ SELL GUARD ALLOW: "
                        "symbol=%s available=%s requested=%s",
                        intent.request.symbol,
                        sell_availability.available_sell_qty,
                        effective_qty,
                    )
                except Exception as exc:
                    logger.warning(
                        "Phase 1.5+ sell guard check failed for "
                        "symbol=%s: %s — allowing through",
                        intent.request.symbol, exc,
                    )
            else:
                logger.debug(
                    "Phase 1.5+: no account_id available, skipping sell guard",
                )

        logger.info(
            "PHASE_TRACE symbol=%s phase=sell_guard_done elapsed_ms=%d status=ok",
            _symbol, int((time_module.monotonic() - _sell_guard_t0) * 1000),
        )

        # ── Phase 2: validate intent (skip HOLD/WATCH) ──
        _validate_t0 = time_module.monotonic()
        logger.info(
            "PHASE_TRACE symbol=%s phase=validate_start elapsed_ms=0 status=start",
            _symbol,
        )
        _dt = intent.ai_backend_inputs.decision_type
        logger.info(
            "Phase 2: validate intent — decision_type=%s",
            _dt,
        )
        submit_request = build_submit_order_request_from_decision(intent)
        if submit_request is None:
            skip_reason = "watch" if _dt == "WATCH" else "hold"
            # held_position sell skip audit
            if (intent.request.side == OrderSide.SELL
                    and _dt in ("REDUCE", "EXIT")):
                logger.warning(
                    "HELD_POSITION_SELL skipped at Phase 2 (translation): "
                    "symbol=%s decision_type=%s skip_reason=%s "
                    "trade_decision_id=%s",
                    intent.request.symbol,
                    _dt,
                    skip_reason,
                    trade_decision_id,
                )
            logger.info(
                "Phase 2 SKIPPED (%s): decision_type=%s, trade_decision_id=%s",
                skip_reason,
                _dt,
                trade_decision_id,
            )
            logger.info(
                "PHASE_TRACE symbol=%s phase=validate_skip_%s elapsed_ms=%d status=skipped",
                _symbol, skip_reason,
                int((time_module.monotonic() - _validate_t0) * 1000),
            )
            _add_phase(f"translation/{_symbol}", "skipped")
            reason = "decision_hold" if _dt == "HOLD" else "decision_watch"
            await self._finalize_attempt(
                attempt_id, "non_trade",
                stop_phase="translation",
                stop_reason=reason,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                trade_decision_id=trade_decision_id,
                error_message=(
                    f"Decision type '{_dt}' "
                    f"produced no order request"
                ),
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                is_skipped=True,
                status="SKIPPED",
            )

        _add_phase(f"translation/{_symbol}", "ok")

        # ── Phase 3: OrderManager.create_order() ──
        _order_create_t0 = time_module.monotonic()
        _add_phase(f"order_create/{_symbol}", "start")
        logger.info(
            "PHASE_TRACE symbol=%s phase=order_create_start elapsed_ms=0 status=start",
            _symbol,
        )
        logger.info(
            "Phase 3: create_order — client_order_id=%s symbol=%s side=%s",
            submit_request.client_order_id,
            submit_request.symbol,
            submit_request.side,
        )
        try:
            order = await order_manager.create_order(
                submit_request,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 3 FAILED (order_create): client_order_id=%s",
                submit_request.client_order_id,
            )
            _add_phase(f"order_create/{_symbol}", "error")
            await self._finalize_attempt(
                attempt_id, "stopped",
                stop_phase="order_create",
                stop_reason="order_create_failed",
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"create_order() failed: {exc}",
                trade_decision_id=trade_decision_id,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                status="ERROR",
                error_phase="order_create",
            )

        # ── Phase 4a: transition DRAFT → VALIDATED ──
        _add_phase(f"transition_validated/{_symbol}", "start")
        logger.info(
            "Phase 4a: transition_to(VALIDATED) — order_id=%s",
            order.order_request_id,
        )
        try:
            validated_order = await order_manager.transition_to(
                order,
                OrderStatus.VALIDATED,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 4a FAILED (order_create): transition to VALIDATED "
                "failed for order_id=%s",
                order.order_request_id,
            )
            await self._finalize_attempt(
                attempt_id, "stopped",
                stop_phase="transition",
                stop_reason="transition_failed",
                order_request_id=order.order_request_id,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"transition_to(VALIDATED) failed: {exc}",
                trade_decision_id=trade_decision_id,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                status="ERROR",
                error_phase="transition",
            )

        # ── Phase 4b: transition VALIDATED → PENDING_SUBMIT ──
        _add_phase(f"transition_pending_submit/{_symbol}", "start")
        logger.info(
            "Phase 4b: transition_to(PENDING_SUBMIT) — order_id=%s",
            validated_order.order_request_id,
        )
        try:
            pending_order = await order_manager.transition_to(
                validated_order,
                OrderStatus.PENDING_SUBMIT,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 4b FAILED (order_create): transition to PENDING_SUBMIT "
                "failed for order_id=%s",
                validated_order.order_request_id,
            )
            await self._finalize_attempt(
                attempt_id, "stopped",
                stop_phase="transition",
                stop_reason="transition_failed",
                order_request_id=validated_order.order_request_id,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"transition_to(PENDING_SUBMIT) failed: {exc}",
                trade_decision_id=trade_decision_id,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                status="ERROR",
                error_phase="transition",
            )

        _order_create_elapsed = time_module.monotonic() - _order_create_t0
        logger.info(
            "PHASE_TRACE symbol=%s phase=order_create_done elapsed_ms=%d status=ok",
            _symbol, int(_order_create_elapsed * 1000),
        )
        logger.info(
            "PHASE_TRACE symbol=%s phase=validate_done elapsed_ms=%d status=ok",
            _symbol, int((time_module.monotonic() - _validate_t0) * 1000),
        )

        # ── Phase 4c: stale snapshot guard (account-level preferred) ──
        _stale_guard_t0 = time_module.monotonic()
        _add_phase(f"stale_snapshot_guard/{_symbol}", "start")
        logger.info(
            "PHASE_TRACE symbol=%s phase=stale_snapshot_guard_start elapsed_ms=0 status=start",
            _symbol,
        )
        account_id: UUID | None = (
            intent.context.decision_context.account_id
            if intent.context is not None
            and intent.context.decision_context is not None
            else None
        )

        # held_position sell bypass check: 위험 축소 목적의 sell은 stale snapshot이어도 진행
        _is_held_position_sell: bool = (
            intent.request.side == OrderSide.SELL
            and intent.ai_backend_inputs.decision_type in ("REDUCE", "EXIT")
        )

        if account_id is not None:
            freshness = await self._check_account_snapshot_freshness(account_id)
            if freshness.is_stale:
                # held_position sell bypass: stale snapshot이어도 위험 축소를 위해 진행
                if _is_held_position_sell:
                    logger.warning(
                        "Phase 4c HELD_POSITION_SELL bypass stale snapshot: "
                        "account_id=%s cash_stale=%s pos_stale=%s "
                        "threshold=%ds trade_decision_id=%s symbol=%s",
                        account_id,
                        freshness.is_cash_stale,
                        freshness.is_position_stale,
                        self._stale_threshold_seconds,
                        trade_decision_id,
                        intent.request.symbol,
                    )
                else:
                    logger.info(
                        "Phase 4c BLOCKED STALE_SNAPSHOT_ACCOUNT: account_id=%s "
                        "cash_stale=%s pos_stale=%s threshold=%ds trade_decision_id=%s",
                        account_id,
                        freshness.is_cash_stale,
                        freshness.is_position_stale,
                        self._stale_threshold_seconds,
                        trade_decision_id,
                    )
                    try:
                        guardrail_eval = GuardrailEvaluationEntity(
                            guardrail_evaluation_id=uuid4(),
                            decision_context_id=intent.decision_context_id,
                            trade_decision_id=trade_decision_id,
                            order_request_id=pending_order.order_request_id,
                            rule_set_version="stale_snapshot_guard_v1",
                            overall_passed=False,
                            evaluated_at=datetime.now(timezone.utc),
                            rule_results={
                                "is_stale": True,
                                "stale_level": "account",
                                "account_id": str(account_id),
                                "latest_cash_snapshot_at": (
                                    str(freshness.latest_cash_snapshot_at)
                                    if freshness.latest_cash_snapshot_at
                                    else None
                                ),
                                "latest_position_snapshot_at": (
                                    str(freshness.latest_position_snapshot_at)
                                    if freshness.latest_position_snapshot_at
                                    else None
                                ),
                                "is_cash_stale": freshness.is_cash_stale,
                                "is_position_stale": freshness.is_position_stale,
                                "stale_threshold_seconds": self._stale_threshold_seconds,
                            },
                            blocking_rule_codes=["STALE_SNAPSHOT_ACCOUNT"],
                        )
                        await self._repos.guardrail_evaluations.add(guardrail_eval)
                    except Exception:
                        logger.warning(
                            "Failed to record guardrail evaluation for stale snapshot (account)",
                            exc_info=True,
                        )

                    logger.info(
                        "PHASE_TRACE symbol=%s phase=stale_snapshot_guard_blocked "
                        "elapsed_ms=%d status=stale_account",
                        _symbol,
                        int((time_module.monotonic() - _stale_guard_t0) * 1000),
                    )
                    _add_phase(f"stale_snapshot_guard/{_symbol}", "skipped")
                    await self._finalize_attempt(
                        attempt_id, "stopped",
                        stop_phase="stale_snapshot_guard",
                        stop_reason="stale_snapshot",
                        order_request_id=pending_order.order_request_id,
                        phase_trace=_phase_trace,
                    )
                    return SubmitResult.build(
                        order_intent=intent,
                        error_message=(
                            f"Account-level snapshot stale: account_id={account_id}, "
                            f"cash_stale={freshness.is_cash_stale}, "
                            f"pos_stale={freshness.is_position_stale}, "
                            f"threshold={self._stale_threshold_seconds}s"
                        ),
                        trade_decision_id=trade_decision_id,
                        phase_trace=tuple(_phase_trace) if _phase_trace else (),
                        is_skipped=True,
                        status="SKIPPED",
                        error_phase="stale_snapshot",
                    )
        else:
            # Fallback: run-level summary
            health = await self._repos.snapshot_sync_runs.get_sync_health_summary(
                stale_threshold_seconds=self._stale_threshold_seconds,
            )
            if health.is_stale:
                # held_position sell bypass: stale snapshot이어도 위험 축소를 위해 진행
                if _is_held_position_sell:
                    logger.warning(
                        "Phase 4c HELD_POSITION_SELL bypass stale snapshot "
                        "(run-level fallback): "
                        "last_successful_run_at=%s threshold=%ds "
                        "trade_decision_id=%s symbol=%s",
                        health.last_successful_run_at,
                        self._stale_threshold_seconds,
                        trade_decision_id,
                        intent.request.symbol,
                    )
                else:
                    logger.info(
                        "Phase 4c BLOCKED stale_snapshot (run-level fallback): "
                        "last_successful_run_at=%s threshold=%ds trade_decision_id=%s",
                        health.last_successful_run_at,
                        self._stale_threshold_seconds,
                        trade_decision_id,
                    )
                    try:
                        guardrail_eval = GuardrailEvaluationEntity(
                            guardrail_evaluation_id=uuid4(),
                            decision_context_id=intent.decision_context_id,
                            trade_decision_id=trade_decision_id,
                            order_request_id=pending_order.order_request_id,
                            rule_set_version="stale_snapshot_guard_v1",
                            overall_passed=False,
                            evaluated_at=datetime.now(timezone.utc),
                            rule_results={
                                "is_stale": True,
                                "stale_level": "run",
                                "last_successful_run_at": (
                                    str(health.last_successful_run_at)
                                    if health.last_successful_run_at
                                    else None
                                ),
                                "stale_threshold_seconds": self._stale_threshold_seconds,
                                "last_run_status": health.last_status,
                            },
                            blocking_rule_codes=["STALE_SNAPSHOT"],
                        )
                        await self._repos.guardrail_evaluations.add(guardrail_eval)
                    except Exception:
                        logger.warning(
                            "Failed to record guardrail evaluation for stale snapshot (run-level)",
                            exc_info=True,
                        )

                    logger.info(
                        "PHASE_TRACE symbol=%s phase=stale_snapshot_guard_blocked "
                        "elapsed_ms=%d status=stale_run",
                        _symbol,
                        int((time_module.monotonic() - _stale_guard_t0) * 1000),
                    )
                    _add_phase(f"stale_snapshot_guard/{_symbol}", "skipped")
                    await self._finalize_attempt(
                        attempt_id, "stopped",
                        stop_phase="stale_snapshot_guard",
                        stop_reason="stale_snapshot",
                        order_request_id=pending_order.order_request_id,
                        phase_trace=_phase_trace,
                    )
                    return SubmitResult.build(
                        order_intent=intent,
                        error_message=(
                            f"Snapshot sync is stale (run-level fallback): "
                            f"last successful run at "
                            f"{health.last_successful_run_at}, "
                            f"threshold={self._stale_threshold_seconds}s"
                        ),
                        trade_decision_id=trade_decision_id,
                        phase_trace=tuple(_phase_trace) if _phase_trace else (),
                        is_skipped=True,
                        status="SKIPPED",
                        error_phase="stale_snapshot",
                    )

        logger.info(
            "PHASE_TRACE symbol=%s phase=stale_snapshot_guard_passed "
            "elapsed_ms=%d status=ok",
            _symbol,
            int((time_module.monotonic() - _stale_guard_t0) * 1000),
        )

        # ── Phase 5: submit to broker ──
        _decision_type: str = "unknown"
        if intent.ai_backend_inputs is not None:
            _decision_type = intent.ai_backend_inputs.decision_type or "unknown"
        _submit_symbol = (
            submit_request.symbol
            if hasattr(submit_request, "symbol")
            else "unknown"
        )
        logger.info(
            "PHASE_TRACE symbol=%s phase=submit_start elapsed_ms=0 status=start",
            _symbol,
        )
        logger.info(
            "[SUBMIT_START] symbol=%s decision_type=%s side=%s order_id=%s",
            _submit_symbol,
            _decision_type,
            submit_request.side if hasattr(submit_request, "side") else "unknown",
            pending_order.order_request_id,
        )
        _add_phase(f"broker_submit/{_symbol}", "start")
        _submit_t0 = time_module.monotonic()
        try:
            submitted_order = await order_manager.submit_order_to_broker(
                pending_order,
                broker,
                submit_request,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            _submit_elapsed = time_module.monotonic() - _submit_t0
            logger.info(
                "PHASE_TRACE symbol=%s phase=submit_done elapsed_ms=%d status=ok",
                _symbol, int(_submit_elapsed * 1000),
            )
            logger.info(
                "[SUBMIT_DONE] symbol=%s elapsed=%.1fs status=%s order_id=%s",
                _submit_symbol,
                _submit_elapsed,
                submitted_order.status.value if hasattr(submitted_order, "status") else "unknown",
                pending_order.order_request_id,
            )
            # broker_submit 결과에 따라 phase_trace 상태 설정
            if submitted_order.status == OrderStatus.SUBMITTED:
                _add_phase(f"broker_submit/{_symbol}", "ok")
            elif submitted_order.status == OrderStatus.RECONCILE_REQUIRED:
                _add_phase(f"broker_submit/{_symbol}", "reconcile")
            elif submitted_order.status == OrderStatus.REJECTED:
                _add_phase(f"broker_submit/{_symbol}", "error")
            else:
                _add_phase(f"broker_submit/{_symbol}", "ok")
        except Exception as exc:
            _submit_elapsed = time_module.monotonic() - _submit_t0
            logger.info(
                "PHASE_TRACE symbol=%s phase=submit_done elapsed_ms=%d status=error",
                _symbol, int(_submit_elapsed * 1000),
            )
            logger.info(
                "[SUBMIT_DONE] symbol=%s elapsed=%.1fs status=ERROR order_id=%s",
                _submit_symbol,
                _submit_elapsed,
                pending_order.order_request_id,
            )
            logger.exception(
                "Phase 5 FAILED (order_submit): order_id=%s symbol=%s "
                "decision_type=%s trade_decision_id=%s",
                pending_order.order_request_id,
                submit_request.symbol if hasattr(submit_request, "symbol") else "unknown",
                _decision_type,
                trade_decision_id,
            )
            _add_phase(f"broker_submit/{_symbol}", "error")
            await self._finalize_attempt(
                attempt_id, "failed",
                stop_phase="broker_submit",
                stop_reason="broker_submit_failed",
                order_request_id=pending_order.order_request_id,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"submit_order_to_broker() failed: {exc}",
                trade_decision_id=trade_decision_id,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                status="ERROR",
                error_phase="order_submit",
            )

        # ── Phase 5.5: post-submit sync (fire-and-forget with timeout) ──
        if (
            submitted_order.status == OrderStatus.SUBMITTED
            and self._sync_service is not None
        ):
            try:
                broker_orders = (
                    await self._repos.broker_orders.list_by_order_request(
                        submitted_order.order_request_id,
                    )
                )
                if broker_orders:
                    bo = broker_orders[0]
                    await asyncio.wait_for(
                        self._sync_service.sync_order_post_submit(
                            account_ref=submit_request.account_ref,
                            broker=broker,
                            broker_order_id=bo.broker_order_id,
                            snapshot_refresh_cb=self._snapshot_refresh_cb,
                        ),
                        timeout=_PHASE55_SYNC_TIMEOUT,
                    )
                    logger.info(
                        "Phase 5.5 sync complete: "
                        "order_id=%s broker_order_id=%s",
                        submitted_order.order_request_id,
                        bo.broker_order_id,
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "Phase 5.5 sync TIMEOUT (order_id=%s) — "
                    "submit result preserved",
                    submitted_order.order_request_id,
                )
            except Exception as exc:
                logger.warning(
                    "Phase 5.5 sync FAILED (order_id=%s): %s — "
                    "submit result preserved",
                    submitted_order.order_request_id,
                    exc,
                )

        # ── Map final order status to SubmitResult.status ──
        final_status = submitted_order.status
        if final_status == OrderStatus.SUBMITTED:
            result_status = "SUBMITTED"
        elif final_status == OrderStatus.RECONCILE_REQUIRED:
            result_status = "RECONCILE_REQUIRED"
        elif final_status == OrderStatus.REJECTED:
            result_status = "REJECTED"
        else:
            result_status = f"UNEXPECTED:{final_status.value}"

        await self._finalize_attempt(
            attempt_id,
            "submitted" if result_status == "SUBMITTED"
            else "reconcile_required" if result_status == "RECONCILE_REQUIRED"
            else "failed" if result_status == "REJECTED"
            else "submitted",
            stop_phase="completed",
            order_request_id=submitted_order.order_request_id,
            phase_trace=_phase_trace,
        )
        logger.info(
            "Pipeline complete: status=%s order_id=%s trade_decision_id=%s",
            result_status,
            submitted_order.order_request_id,
            trade_decision_id,
        )
        return SubmitResult.build(
            order_intent=intent,
            trade_decision_id=trade_decision_id,
            phase_trace=tuple(_phase_trace) if _phase_trace else (),
            is_submitted=(result_status == "SUBMITTED"),
            is_skipped=(result_status in ("RECONCILE_REQUIRED", "REJECTED")),
            status=result_status,
            submit_response=submitted_order,
        )


