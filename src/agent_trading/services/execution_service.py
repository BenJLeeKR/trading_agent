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
    SymbolTradeStateEntity,
)
from agent_trading.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PipelineStopReason,
)
from agent_trading.domain.models import Quote, SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup, OrderQuery
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import OrderSyncService
from agent_trading.services.sizing_engine import SizingInputs, SizingResult, calculate_sizing
from agent_trading.services.sell_guard import AvailableSellQtyResolver, SellAvailability
from agent_trading.services.common_types import (
    AccountSnapshotFreshness,
    OrderIntent,
    PhaseTraceEntry,
    SubmitResult,
    phase_trace_to_dicts,
)
from agent_trading.services.guardrail_audit import (
    persist_blocking_guardrail_evaluation,
)
from agent_trading.services.held_position_policy import (
    is_held_position_sell_path,
)
from agent_trading.services.holding_profile_policy import (
    parse_datetime_or_none,
)
from agent_trading.services.translation import (
    build_submit_order_request_from_decision,
    calculate_max_order_value,
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
_BUY_DUPLICATE_COOLDOWN_SECONDS = 15 * 60
_SINGLE_SHARE_PROBE_MIN_ORDER_VALUE = Decimal("500000")
_SINGLE_SHARE_PROBE_HIGH_EDGE_BPS = Decimal("35")
_SINGLE_SHARE_PROBE_REVERSE_COOLDOWN = timedelta(minutes=20)
_LOW_LIQUIDITY_VOLUME_THRESHOLD = Decimal("3000")
_LOW_LIQUIDITY_TURNOVER_THRESHOLD = Decimal("50000000")
_SEVERE_LOW_LIQUIDITY_VOLUME_THRESHOLD = Decimal("500")
_SEVERE_LOW_LIQUIDITY_TURNOVER_THRESHOLD = Decimal("10000000")
_EXECUTION_INFEASIBLE_TRIGGER_REASONS = frozenset({
    "eligibility_low_average_volume",
    "eligibility_low_turnover",
    "eligibility_participation_rate_blocked",
})
_SINGLE_SHARE_REVERSE_SELL_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.VALIDATED,
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.FILLED,
    OrderStatus.RECONCILE_REQUIRED,
}


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

    @staticmethod
    def _resolve_zero_quantity_outcome(
        intent: OrderIntent,
        sizing_result: SizingResult,
    ) -> tuple[str, str, str]:
        """Classify zero-quantity sizing outcomes into canonical stop reasons."""
        if sizing_result.skip_reason == "non_actionable_decision":
            decision_type = (intent.ai_backend_inputs.decision_type or "").upper()
            stop_reason = (
                PipelineStopReason.DECISION_HOLD.value
                if decision_type == "HOLD"
                else PipelineStopReason.DECISION_WATCH.value
            )
            return ("non_trade", stop_reason, stop_reason)
        return (
            "stopped",
            PipelineStopReason.SIZING_REJECTED.value,
            sizing_result.skip_reason or "Sizing rejected order",
        )

    @staticmethod
    def _build_execution_liquidity_metadata(
        *,
        action: str,
        source_type: str,
        reason: str,
        price_source: str | None = None,
        limit_price: Decimal | None = None,
        quote: Quote | None = None,
    ) -> dict[str, object]:
        return {
            "action": action,
            "source_type": source_type,
            "reason": reason,
            "price_source": price_source,
            "limit_price": (str(limit_price) if limit_price is not None else None),
            "accumulated_volume": (
                str(quote.accumulated_volume)
                if quote is not None and quote.accumulated_volume is not None
                else None
            ),
            "accumulated_turnover": (
                str(quote.accumulated_turnover)
                if quote is not None and quote.accumulated_turnover is not None
                else None
            ),
        }

    @staticmethod
    def _resolve_limit_price_for_low_liquidity_buy(
        quote: Quote | None,
        reference_price: Decimal | None,
    ) -> tuple[Decimal | None, str | None]:
        if quote is not None and quote.ask is not None and quote.ask > 0:
            return quote.ask, "quote.ask"
        if reference_price is not None and reference_price > 0:
            return reference_price, "reference_price"
        if quote is not None and quote.last is not None and quote.last > 0:
            return quote.last, "quote.last"
        return None, None

    def _classify_buy_execution_liquidity_policy(
        self,
        *,
        intent: OrderIntent,
        source_type: str,
        quote: Quote | None,
        reference_price: Decimal | None,
        sizing_result: SizingResult,
    ) -> tuple[str, str, dict[str, object]]:
        """자동 BUY의 저유동성 실행 정책을 분류한다."""
        if (
            intent.request.side != OrderSide.BUY
            or intent.request.order_type != OrderType.MARKET
            or source_type == "manual"
        ):
            return ("allow", "not_applicable", {})

        trigger = (
            intent.context.deterministic_trigger
            if intent.context is not None
            else None
        )
        eligibility_reasons = tuple(
            getattr(trigger, "eligibility_reasons", ()) or ()
        )
        trigger_blocked = any(
            reason in _EXECUTION_INFEASIBLE_TRIGGER_REASONS
            for reason in eligibility_reasons
        )

        accumulated_volume = quote.accumulated_volume if quote is not None else None
        accumulated_turnover = quote.accumulated_turnover if quote is not None else None
        severe_live_low_liquidity = (
            accumulated_volume is not None
            and accumulated_turnover is not None
            and accumulated_volume > 0
            and accumulated_turnover > 0
            and accumulated_volume < _SEVERE_LOW_LIQUIDITY_VOLUME_THRESHOLD
            and accumulated_turnover < _SEVERE_LOW_LIQUIDITY_TURNOVER_THRESHOLD
        )
        moderate_live_low_liquidity = (
            accumulated_volume is not None
            and accumulated_turnover is not None
            and accumulated_volume > 0
            and accumulated_turnover > 0
            and (
                accumulated_volume < _LOW_LIQUIDITY_VOLUME_THRESHOLD
                or accumulated_turnover < _LOW_LIQUIDITY_TURNOVER_THRESHOLD
            )
        )
        participation_capped = any(
            code in {
                "intraday_volume_participation_cap",
                "intraday_turnover_participation_cap",
                "average_daily_volume_participation_cap",
            }
            for code in sizing_result.applied_constraints
        )

        limit_price, price_source = self._resolve_limit_price_for_low_liquidity_buy(
            quote,
            reference_price,
        )

        if trigger_blocked or severe_live_low_liquidity:
            reason = (
                "trigger_execution_infeasible"
                if trigger_blocked
                else "severe_live_low_liquidity"
            )
            return (
                "block",
                reason,
                self._build_execution_liquidity_metadata(
                    action="block",
                    source_type=source_type,
                    reason=reason,
                    price_source=price_source,
                    limit_price=limit_price,
                    quote=quote,
                ),
            )

        if moderate_live_low_liquidity or participation_capped:
            reason = (
                "moderate_live_low_liquidity"
                if moderate_live_low_liquidity
                else "participation_cap_activated"
            )
            if limit_price is None:
                return (
                    "block",
                    "missing_limit_price_for_low_liquidity",
                    self._build_execution_liquidity_metadata(
                        action="block",
                        source_type=source_type,
                        reason="missing_limit_price_for_low_liquidity",
                        quote=quote,
                    ),
                )
            return (
                "force_limit",
                reason,
                self._build_execution_liquidity_metadata(
                    action="force_limit",
                    source_type=source_type,
                    reason=reason,
                    price_source=price_source,
                    limit_price=limit_price,
                    quote=quote,
                ),
            )

        return ("allow", "no_low_liquidity_signal", {})

    async def _classify_single_share_probe_churn_policy(
        self,
        *,
        intent: OrderIntent,
        source_type: str,
        reference_price: Decimal | None,
    ) -> tuple[str, str, dict[str, object]]:
        """신규 1주 BUY churn 조합을 submit 직전에 차단한다."""
        if intent.request.side != OrderSide.BUY:
            return ("allow", "not_buy", {})
        if intent.request.quantity != Decimal("1"):
            return ("allow", "qty_not_single_share", {})
        if source_type == "manual":
            return ("allow", "manual_bypass", {})

        current_position_qty = (
            intent.context.position_snapshot.quantity
            if intent.context is not None
            and intent.context.position_snapshot is not None
            else None
        )
        if current_position_qty is not None and current_position_qty > 0:
            return ("allow", "existing_position_not_probe", {})

        effective_price = (
            intent.request.price
            or reference_price
            or intent.request.price_band_upper
            or intent.request.price_band_lower
        )
        estimated_order_value = (
            effective_price * intent.request.quantity
            if effective_price is not None and effective_price > 0
            else None
        )
        edge_after_cost_bps = intent.ai_backend_inputs.edge_after_cost_bps
        high_edge_exception = (
            source_type in {"core", "event_overlay"}
            and edge_after_cost_bps is not None
            and edge_after_cost_bps >= _SINGLE_SHARE_PROBE_HIGH_EDGE_BPS
        )
        signal_snapshot = (
            intent.context.signal_feature_snapshot
            if intent.context is not None
            else None
        )
        atr_14_pct = (
            signal_snapshot.atr_14_pct
            if signal_snapshot is not None
            else None
        )
        volatility_20d_pct = (
            signal_snapshot.volatility_20d_pct
            if signal_snapshot is not None
            else None
        )
        high_volatility = (
            (atr_14_pct is not None and atr_14_pct >= Decimal("3"))
            or (
                volatility_20d_pct is not None
                and volatility_20d_pct >= Decimal("4")
            )
        )
        risk_off = (
            intent.ai_backend_inputs.risk_opinion != "allow"
            or intent.ai_backend_inputs.risk_score >= 0.6
        )
        metadata: dict[str, object] = {
            "source_type": source_type,
            "quantity": str(intent.request.quantity),
            "estimated_order_value": (
                str(estimated_order_value) if estimated_order_value is not None else None
            ),
            "min_probe_order_value": str(_SINGLE_SHARE_PROBE_MIN_ORDER_VALUE),
            "edge_after_cost_bps": (
                str(edge_after_cost_bps) if edge_after_cost_bps is not None else None
            ),
            "high_edge_exception": high_edge_exception,
            "high_volatility": high_volatility,
            "risk_off": risk_off,
            "order_type": intent.request.order_type.value,
        }

        if source_type == "reconciliation_overlay":
            metadata["reason"] = "overlay_single_share_buy_blocked"
            return (
                "block",
                PipelineStopReason.OVERLAY_SINGLE_SHARE_BUY_BLOCKED.value,
                metadata,
            )

        account_id: UUID | None = (
            intent.context.decision_context.account_id
            if intent.context is not None
            and intent.context.decision_context is not None
            else None
        )
        if account_id is None:
            account = await self._repos.accounts.find_one(
                AccountLookup(account_alias=intent.request.account_ref)
            )
            account_id = account.account_id if account is not None else None
        if account_id is not None:
            recent_orders = await self._repos.orders.list(
                OrderQuery(
                    account_id=account_id,
                    created_from=datetime.now(timezone.utc) - _SINGLE_SHARE_PROBE_REVERSE_COOLDOWN,
                    created_to=datetime.now(timezone.utc),
                    limit=50,
                )
            )
            instrument_id = (
                intent.context.position_snapshot.instrument_id
                if intent.context is not None and intent.context.position_snapshot is not None
                else None
            )
            if instrument_id is not None:
                recent_orders = [
                    order
                    for order in recent_orders
                    if order.instrument_id == instrument_id
                ]
            recent_sell_orders = [
                order
                for order in recent_orders
                if order.side == OrderSide.SELL
                and order.status in _SINGLE_SHARE_REVERSE_SELL_STATUSES
            ]
            metadata["recent_sell_order_count"] = len(recent_sell_orders)
            if recent_sell_orders:
                metadata["reason"] = "reverse_trade_single_share_blocked"
                return (
                    "block",
                    PipelineStopReason.REVERSE_TRADE_SINGLE_SHARE_BLOCKED.value,
                    metadata,
                )

        if (
            intent.request.order_type == OrderType.MARKET
            and high_volatility
            and risk_off
        ):
            metadata["reason"] = "probe_churn_single_share_blocked"
            return (
                "block",
                PipelineStopReason.PROBE_CHURN_SINGLE_SHARE_BLOCKED.value,
                metadata,
            )

        if (
            estimated_order_value is not None
            and estimated_order_value < _SINGLE_SHARE_PROBE_MIN_ORDER_VALUE
            and not high_edge_exception
        ):
            metadata["reason"] = "probe_churn_single_share_blocked"
            return (
                "block",
                PipelineStopReason.PROBE_CHURN_SINGLE_SHARE_BLOCKED.value,
                metadata,
            )

        metadata["reason"] = "allow"
        return ("allow", "allow", metadata)

    async def _sync_symbol_trade_state_order_link(
        self,
        *,
        intent: OrderIntent,
        order_request_id: UUID,
        trade_decision_id: UUID | None,
    ) -> None:
        decision_context = (
            intent.context.decision_context
            if intent.context is not None
            else None
        )
        if decision_context is None:
            return

        instrument = await self._repos.instruments.get_by_symbol(
            symbol=intent.request.symbol,
            market_code=intent.request.market,
        )
        if instrument is None:
            instrument = await self._repos.instruments.get_by_symbol_any_market(
                intent.request.symbol
            )
        if instrument is None:
            return

        current_state = await self._repos.symbol_trade_states.get_by_account_and_instrument(
            decision_context.account_id,
            instrument.instrument_id,
        )
        if current_state is None:
            return

        metadata = dict(current_state.metadata_json)
        policy_payload = metadata.get("holding_profile_policy")
        policy_metadata = (
            dict(policy_payload)
            if isinstance(policy_payload, dict)
            else {}
        )
        metadata["last_order_request_id"] = str(order_request_id)
        if trade_decision_id is not None:
            metadata["last_trade_decision_id"] = str(trade_decision_id)

        decision_type = (intent.ai_backend_inputs.decision_type or "").strip().upper()
        state_value = current_state.state
        if intent.request.side == OrderSide.BUY:
            state_value = "entry_pending"
        elif intent.request.side == OrderSide.SELL and decision_type == "REDUCE":
            state_value = "reduce_pending"
        elif intent.request.side == OrderSide.SELL and decision_type in {"SELL", "EXIT"}:
            state_value = "exit_pending"

        await self._repos.symbol_trade_states.upsert(
            SymbolTradeStateEntity(
                symbol_trade_state_id=current_state.symbol_trade_state_id,
                account_id=current_state.account_id,
                instrument_id=current_state.instrument_id,
                symbol=current_state.symbol,
                market=current_state.market,
                state=state_value,
                holding_profile=current_state.holding_profile,
                position_quantity=current_state.position_quantity,
                last_entry_order_request_id=(
                    order_request_id
                    if intent.request.side == OrderSide.BUY
                    else current_state.last_entry_order_request_id
                ),
                last_exit_order_request_id=(
                    order_request_id
                    if intent.request.side == OrderSide.SELL
                    else current_state.last_exit_order_request_id
                ),
                last_entry_source_type=current_state.last_entry_source_type,
                last_entry_at=current_state.last_entry_at,
                last_reduce_at=current_state.last_reduce_at,
                last_exit_at=current_state.last_exit_at,
                minimum_hold_until=parse_datetime_or_none(
                    policy_metadata.get("minimum_hold_until")
                ) or current_state.minimum_hold_until,
                reentry_cooldown_until=parse_datetime_or_none(
                    policy_metadata.get("reentry_cooldown_until")
                ) or current_state.reentry_cooldown_until,
                sell_cooldown_until=parse_datetime_or_none(
                    policy_metadata.get("sell_cooldown_until")
                ) or current_state.sell_cooldown_until,
                last_signal_feature_snapshot_id=current_state.last_signal_feature_snapshot_id,
                last_decision_context_id=decision_context.decision_context_id,
                last_reason_codes=list(intent.ai_backend_inputs.reason_codes),
                thesis_state_hash=current_state.thesis_state_hash,
                metadata_json=metadata,
                created_at=current_state.created_at,
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def _sync_trade_decision_execution_sizing(
        self,
        *,
        trade_decision_id: UUID | None,
        request: SubmitOrderRequest,
        original_request_quantity: Decimal,
        effective_qty: Decimal,
        sizing_result: SizingResult,
    ) -> None:
        """Sizing 결과를 trade_decision의 분석용 수량 필드에 반영한다."""
        if trade_decision_id is None:
            return

        max_order_value = calculate_max_order_value(request.price, effective_qty)
        payload = {
            "requested_quantity_before_sizing": str(original_request_quantity),
            "resolved_quantity": str(effective_qty),
            "max_order_value": (
                str(max_order_value) if max_order_value is not None else None
            ),
            "applied_constraints": list(sizing_result.applied_constraints),
            "skip_reason": sizing_result.skip_reason,
            "sizing_result_max_order_value": (
                str(sizing_result.max_order_value)
                if sizing_result.max_order_value is not None
                else None
            ),
        }
        try:
            await self._repos.trade_decisions.sync_execution_sizing(
                trade_decision_id,
                quantity=effective_qty,
                max_order_value=max_order_value,
                target_notional=max_order_value,
                execution_sizing_payload=payload,
            )
        except Exception:
            logger.warning(
                "trade_decision execution sizing sync failed: trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )

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

    async def _has_recent_active_buy_order(
        self,
        *,
        account_id: UUID,
        symbol: str,
        market: str,
        created_after: datetime,
    ) -> tuple[bool, str | None]:
        """Return whether a recent active BUY order already exists.

        This blocks rapid re-entry for the same symbol while broker/account
        snapshots are still converging after a submit.
        """
        instrument = await self._repos.instruments.get_by_symbol(symbol, market)
        if instrument is None:
            return False, None

        active_statuses = (
            OrderStatus.DRAFT,
            OrderStatus.VALIDATED,
            OrderStatus.PENDING_SUBMIT,
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.RECONCILE_REQUIRED,
        )
        recent_orders = await self._repos.orders.list(
            OrderQuery(
                account_id=account_id,
                statuses=active_statuses,
                created_from=created_after,
                limit=100,
            )
        )
        for order in recent_orders:
            if (
                order.instrument_id == instrument.instrument_id
                and order.side == OrderSide.BUY
            ):
                return True, str(order.order_request_id)
        return False, None

    async def _has_active_reconciliation_lock(
        self,
        *,
        order_manager: OrderManager,
        account_id: UUID,
        symbol: str,
        side: OrderSide,
    ) -> bool:
        """Return whether an active reconciliation lock already exists.

        Unknown order state must take precedence over duplicate-entry
        heuristics. When a blocking reconciliation lock exists, the
        authoritative RECONCILE_REQUIRED path in OrderManager must be
        allowed to run instead of being shadowed by the BUY duplicate guard.
        """
        if order_manager.reconciliation_service is None:
            return False
        return await order_manager.reconciliation_service.is_blocked(
            account_id=account_id,
            symbol=symbol,
            side=side.value,
        )

    async def _record_blocking_guardrail_evaluation(
        self,
        *,
        rule_set_version: str,
        blocking_rule_codes: list[str],
        rule_results: dict[str, object],
        decision_context_id: UUID | None,
        trade_decision_id: UUID | None,
        order_request_id: UUID | None = None,
    ) -> None:
        """Persist a blocking guardrail evaluation without interrupting flow."""
        await persist_blocking_guardrail_evaluation(
            self._repos,
            rule_set_version=rule_set_version,
            blocking_rule_codes=blocking_rule_codes,
            rule_results=rule_results,
            decision_context_id=decision_context_id,
            trade_decision_id=trade_decision_id,
            order_request_id=order_request_id,
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
    def _resolve_market_buy_reference_price(
        intent: OrderIntent,
        live_reference_price: Decimal | None,
    ) -> tuple[Decimal | None, str | None]:
        """Resolve a usable reference price for MARKET BUY sizing.

        Priority:
        1. Live broker quote (`live_reference_price`)
        2. Request price band midpoint / upper / lower
        3. Existing position snapshot market_price / average_price

        Returns ``(price, source_label)``.  ``(None, None)`` means no
        deterministic fallback price was available and the BUY should be
        skipped instead of silently using the placeholder quantity.
        """
        if live_reference_price is not None and live_reference_price > 0:
            return live_reference_price, "live_quote"

        req = intent.request
        lower = req.price_band_lower
        upper = req.price_band_upper
        if lower is not None and lower > 0 and upper is not None and upper > 0:
            return (lower + upper) / Decimal("2"), "price_band_midpoint"
        if upper is not None and upper > 0:
            return upper, "price_band_upper"
        if lower is not None and lower > 0:
            return lower, "price_band_lower"

        pos = intent.context.position_snapshot if intent.context is not None else None
        if pos is not None and pos.market_price is not None and pos.market_price > 0:
            return pos.market_price, "position_market_price"
        if pos is not None and pos.average_price is not None and pos.average_price > 0:
            return pos.average_price, "position_average_price"

        return None, None

    @staticmethod
    def _build_sizing_inputs(
        intent: OrderIntent,
        quote: Quote | None = None,
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
        max_single_position_pct = decimal_or_none(risk.get("max_single_position_pct"))
        max_pct_source = "risk.max_single_position_pct"
        if max_single_position_pct is None:
            max_single_position_pct = decimal_or_none(config.get("max_position_size"))
            max_pct_source = "max_position_size (legacy)"
            if (
                max_single_position_pct is not None
                and Decimal("0") < max_single_position_pct <= Decimal("1")
            ):
                max_single_position_pct = max_single_position_pct * Decimal("100")
                max_pct_source = "max_position_size (legacy ratio)"
        min_cash_buffer_pct = decimal_or_none(
            risk.get("min_cash_buffer_pct")
            or config.get("min_cash_buffer_pct")
        )
        max_order_value = decimal_or_none(
            execution.get("max_order_value")
            or config.get("max_order_value")
        )
        max_intraday_volume_participation_pct = decimal_or_none(
            execution.get("max_intraday_volume_participation_pct")
        )
        max_intraday_turnover_participation_pct = decimal_or_none(
            execution.get("max_intraday_turnover_participation_pct")
        )
        max_average_daily_volume_participation_pct = decimal_or_none(
            execution.get("max_average_daily_volume_participation_pct")
        )
        average_daily_volume_20d = (
            ctx.signal_feature_snapshot.average_volume_20d
            if ctx.signal_feature_snapshot is not None
            else None
        )

        # ── Operational visibility logging ──────────────────────────────
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
            source_type=ctx.source_type,
            requested_quantity=req.quantity,
            requested_price=req.price,
            reference_price=reference_price,
            average_daily_volume_20d=average_daily_volume_20d,
            accumulated_intraday_volume=(
                quote.accumulated_volume if quote is not None else None
            ),
            accumulated_intraday_turnover=(
                quote.accumulated_turnover if quote is not None else None
            ),
            max_intraday_volume_participation_pct=max_intraday_volume_participation_pct,
            max_intraday_turnover_participation_pct=max_intraday_turnover_participation_pct,
            max_average_daily_volume_participation_pct=max_average_daily_volume_participation_pct,
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
        request_metadata = getattr(intent.request, "metadata", None) or {}
        intent_source_type = (
            intent.context.source_type
            if intent.context is not None
            else str(request_metadata.get("source_type") or "core")
        )

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
        _is_hp_sell = is_held_position_sell_path(
            source_type=intent_source_type,
            decision_type=intent.ai_backend_inputs.decision_type,
            side=intent.request.side,
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
        sizing_reference_price = reference_price
        if (
            intent.request.side == OrderSide.BUY
            and intent.request.price is None
            and intent.request.order_type == OrderType.MARKET
        ):
            sizing_reference_price, sizing_price_source = (
                self._resolve_market_buy_reference_price(intent, reference_price)
            )
            if sizing_reference_price is None:
                logger.warning(
                    "Phase 1.5 SKIPPED (sizing): missing reference price for MARKET BUY "
                    "symbol=%s trade_decision_id=%s request_qty=%s",
                    intent.request.symbol,
                    trade_decision_id,
                    intent.request.quantity,
                )
                _add_phase(f"sizing/{_symbol}", "skipped_missing_reference_price")
                await self._finalize_attempt(
                    attempt_id, "stopped",
                    stop_phase="sizing",
                    stop_reason=PipelineStopReason.MISSING_REFERENCE_PRICE_FOR_MARKET_BUY.value,
                    phase_trace=_phase_trace,
                )
                return SubmitResult.build(
                    order_intent=intent,
                    trade_decision_id=trade_decision_id,
                    error_message=PipelineStopReason.MISSING_REFERENCE_PRICE_FOR_MARKET_BUY.value,
                    stop_reason=PipelineStopReason.MISSING_REFERENCE_PRICE_FOR_MARKET_BUY.value,
                    phase_trace=tuple(_phase_trace) if _phase_trace else (),
                    is_skipped=True,
                    status="SKIPPED",
                    error_phase="sizing",
                )
            if reference_price is None and sizing_price_source != "live_quote":
                logger.info(
                    "Phase 1.5: MARKET BUY reference_price fallback=%s source=%s symbol=%s",
                    sizing_reference_price,
                    sizing_price_source,
                    intent.request.symbol,
                )

        sizing_inputs = self._build_sizing_inputs(
            intent,
            quote=quote if isinstance(quote, Quote) else None,
            reference_price=sizing_reference_price,
        )
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

        effective_qty = sizing_result.quantity
        if effective_qty <= 0 and intent.request.side == OrderSide.SELL and not _is_hp_sell:
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
            await self._sync_trade_decision_execution_sizing(
                trade_decision_id=trade_decision_id,
                request=intent.request,
                original_request_quantity=intent.request.quantity,
                effective_qty=Decimal("0"),
                sizing_result=sizing_result,
            )
            attempt_status, stop_reason, error_message = (
                self._resolve_zero_quantity_outcome(intent, sizing_result)
            )
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
                attempt_id, attempt_status,
                stop_phase="sizing",
                stop_reason=stop_reason,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                trade_decision_id=trade_decision_id,
                error_message=error_message,
                stop_reason=stop_reason,
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

        # ── Phase 1.6: low-liquidity MARKET BUY policy ──
        _execution_liquidity_t0 = time_module.monotonic()
        _add_phase(f"execution_liquidity/{_symbol}", "start")
        liquidity_policy, liquidity_reason, liquidity_metadata = (
            self._classify_buy_execution_liquidity_policy(
                intent=intent,
                source_type=intent_source_type,
                quote=quote if isinstance(quote, Quote) else None,
                reference_price=sizing_reference_price,
                sizing_result=sizing_result,
            )
        )
        if liquidity_policy == "block":
            logger.info(
                "Phase 1.6 BLOCKED low-liquidity BUY execution: symbol=%s "
                "reason=%s metadata=%s trade_decision_id=%s",
                intent.request.symbol,
                liquidity_reason,
                liquidity_metadata,
                trade_decision_id,
            )
            await self._record_blocking_guardrail_evaluation(
                rule_set_version="buy_execution_liquidity_v1",
                blocking_rule_codes=[
                    PipelineStopReason.LOW_LIQUIDITY_EXECUTION_BLOCKED.value
                ],
                rule_results=liquidity_metadata,
                decision_context_id=intent.decision_context_id,
                trade_decision_id=trade_decision_id,
            )
            _add_phase(f"execution_liquidity/{_symbol}", "skipped")
            await self._finalize_attempt(
                attempt_id,
                "stopped",
                stop_phase="execution_liquidity",
                stop_reason=PipelineStopReason.LOW_LIQUIDITY_EXECUTION_BLOCKED.value,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                trade_decision_id=trade_decision_id,
                error_message=liquidity_reason,
                stop_reason=PipelineStopReason.LOW_LIQUIDITY_EXECUTION_BLOCKED.value,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                is_skipped=True,
                status="SKIPPED",
                error_phase="execution_liquidity",
            )
        if liquidity_policy == "force_limit":
            limit_price = decimal_or_none(liquidity_metadata.get("limit_price"))
            if limit_price is not None:
                updated_metadata = dict(intent.request.metadata or {})
                updated_metadata["execution_liquidity_policy"] = liquidity_metadata
                updated_request = replace(
                    intent.request,
                    order_type=OrderType.LIMIT,
                    price=limit_price,
                    metadata=updated_metadata,
                )
                intent = replace(intent, request=updated_request)
                logger.info(
                    "Phase 1.6 FORCE LIMIT: symbol=%s reason=%s limit_price=%s source=%s",
                    intent.request.symbol,
                    liquidity_reason,
                    limit_price,
                    liquidity_metadata.get("price_source"),
                )

        _add_phase(f"execution_liquidity/{_symbol}", "ok")
        logger.info(
            "PHASE_TRACE symbol=%s phase=execution_liquidity_done elapsed_ms=%d status=ok",
            _symbol,
            int((time_module.monotonic() - _execution_liquidity_t0) * 1000),
        )

        await self._sync_trade_decision_execution_sizing(
            trade_decision_id=trade_decision_id,
            request=intent.request,
            original_request_quantity=sizing_inputs.requested_quantity,
            effective_qty=effective_qty,
            sizing_result=sizing_result,
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
                        if is_held_position_sell_path(
                            source_type=intent_source_type,
                            decision_type=intent.ai_backend_inputs.decision_type,
                            side=intent.request.side,
                        ):
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
                        await self._record_blocking_guardrail_evaluation(
                            rule_set_version="sell_guard_v1",
                            blocking_rule_codes=[PipelineStopReason.SELL_GUARD_BLOCKED.value],
                            rule_results={
                                "account_id": str(account_id),
                                "symbol": intent.request.symbol,
                                "requested_qty": str(effective_qty),
                                "available_sell_qty": str(sell_availability.available_sell_qty),
                                "blocking_reason": sell_availability.blocking_reason,
                            },
                            decision_context_id=intent.decision_context_id,
                            trade_decision_id=trade_decision_id,
                        )
                        _add_phase(f"sell_guard/{_symbol}", "skipped")
                        await self._finalize_attempt(
                            attempt_id, "stopped",
                            stop_phase="sell_guard",
                            stop_reason=PipelineStopReason.SELL_GUARD_BLOCKED.value,
                            phase_trace=_phase_trace,
                        )
                        return SubmitResult.build(
                            order_intent=intent,
                            trade_decision_id=trade_decision_id,
                            error_message=(
                                sell_availability.blocking_reason
                                or "Sell guard blocked duplicate sell"
                            ),
                            stop_reason=PipelineStopReason.SELL_GUARD_BLOCKED.value,
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
            if is_held_position_sell_path(
                source_type=intent_source_type,
                decision_type=_dt,
                side=intent.request.side,
            ):
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
            reason = (
                PipelineStopReason.DECISION_HOLD.value
                if _dt == "HOLD"
                else PipelineStopReason.DECISION_WATCH.value
            )
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
                stop_reason=reason,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                is_skipped=True,
                status="SKIPPED",
            )

        # ── Phase 2.4: single-share BUY probe churn guard ───────────────
        if intent.request.side == OrderSide.BUY:
            probe_policy, probe_reason, probe_metadata = (
                await self._classify_single_share_probe_churn_policy(
                    intent=intent,
                    source_type=intent_source_type,
                    reference_price=sizing_reference_price,
                )
            )
            if probe_policy == "block":
                logger.info(
                    "Phase 2.4 BLOCKED single-share BUY probe churn: symbol=%s "
                    "reason=%s metadata=%s trade_decision_id=%s",
                    intent.request.symbol,
                    probe_reason,
                    probe_metadata,
                    trade_decision_id,
                )
                await self._record_blocking_guardrail_evaluation(
                    rule_set_version="execution_probe_churn_guard_v1",
                    blocking_rule_codes=[probe_reason],
                    rule_results=probe_metadata,
                    decision_context_id=intent.decision_context_id,
                    trade_decision_id=trade_decision_id,
                )
                _add_phase(f"probe_churn_guard/{_symbol}", "skipped")
                await self._finalize_attempt(
                    attempt_id, "stopped",
                    stop_phase="probe_churn_guard",
                    stop_reason=probe_reason,
                    phase_trace=_phase_trace,
                )
                return SubmitResult.build(
                    order_intent=intent,
                    trade_decision_id=trade_decision_id,
                    error_message=probe_reason,
                    stop_reason=probe_reason,
                    phase_trace=tuple(_phase_trace) if _phase_trace else (),
                    is_skipped=True,
                    status="SKIPPED",
                    error_phase="probe_churn_guard",
                )

        _add_phase(f"translation/{_symbol}", "ok")

        # ── Phase 2.5: BUY duplicate re-entry guard ─────────────────────
        if intent.request.side == OrderSide.BUY:
            buy_guard_account_id: UUID | None = (
                intent.context.decision_context.account_id
                if intent.context is not None
                and intent.context.decision_context is not None
                else None
            )
            if buy_guard_account_id is None:
                account = await self._repos.accounts.find_one(
                    AccountLookup(account_alias=intent.request.account_ref)
                )
                buy_guard_account_id = account.account_id if account is not None else None

            if buy_guard_account_id is not None:
                if await self._has_active_reconciliation_lock(
                    order_manager=order_manager,
                    account_id=buy_guard_account_id,
                    symbol=intent.request.symbol,
                    side=intent.request.side,
                ):
                    logger.info(
                        "Phase 2.5 BUY duplicate guard bypassed due to active "
                        "reconciliation lock: symbol=%s account_id=%s "
                        "trade_decision_id=%s",
                        intent.request.symbol,
                        buy_guard_account_id,
                        trade_decision_id,
                    )
                else:
                    created_after = datetime.now(timezone.utc) - timedelta(
                        seconds=_BUY_DUPLICATE_COOLDOWN_SECONDS
                    )
                    has_duplicate, existing_order_id = await self._has_recent_active_buy_order(
                        account_id=buy_guard_account_id,
                        symbol=intent.request.symbol,
                        market=intent.request.market,
                        created_after=created_after,
                    )
                    if has_duplicate:
                        logger.warning(
                            "Phase 2.5 BUY duplicate guard blocked: symbol=%s "
                            "account_id=%s existing_order_id=%s cooldown_seconds=%s "
                            "trade_decision_id=%s",
                            intent.request.symbol,
                            buy_guard_account_id,
                            existing_order_id,
                            _BUY_DUPLICATE_COOLDOWN_SECONDS,
                            trade_decision_id,
                        )
                        await self._record_blocking_guardrail_evaluation(
                            rule_set_version="buy_duplicate_guard_v1",
                            blocking_rule_codes=[PipelineStopReason.RECENT_ACTIVE_BUY_ORDER.value],
                            rule_results={
                                "account_id": str(buy_guard_account_id),
                                "symbol": intent.request.symbol,
                                "market": intent.request.market,
                                "existing_order_id": existing_order_id,
                                "cooldown_seconds": _BUY_DUPLICATE_COOLDOWN_SECONDS,
                            },
                            decision_context_id=intent.decision_context_id,
                            trade_decision_id=trade_decision_id,
                        )
                        _add_phase(f"buy_duplicate_guard/{_symbol}", "skipped")
                        await self._finalize_attempt(
                            attempt_id, "stopped",
                            stop_phase="buy_duplicate_guard",
                            stop_reason=PipelineStopReason.RECENT_ACTIVE_BUY_ORDER.value,
                            phase_trace=_phase_trace,
                        )
                        return SubmitResult.build(
                            order_intent=intent,
                            trade_decision_id=trade_decision_id,
                            error_message=PipelineStopReason.RECENT_ACTIVE_BUY_ORDER.value,
                            stop_reason=PipelineStopReason.RECENT_ACTIVE_BUY_ORDER.value,
                            phase_trace=tuple(_phase_trace) if _phase_trace else (),
                            is_skipped=True,
                            status="SKIPPED",
                            error_phase="buy_duplicate_guard",
                        )

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
                stop_reason=PipelineStopReason.ORDER_CREATE_FAILED.value,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"create_order() failed: {exc}",
                stop_reason=PipelineStopReason.ORDER_CREATE_FAILED.value,
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
                stop_reason=PipelineStopReason.TRANSITION_FAILED.value,
                order_request_id=order.order_request_id,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"transition_to(VALIDATED) failed: {exc}",
                stop_reason=PipelineStopReason.TRANSITION_FAILED.value,
                trade_decision_id=trade_decision_id,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                status="ERROR",
                error_phase="transition",
            )
        try:
            await self._sync_symbol_trade_state_order_link(
                intent=intent,
                order_request_id=validated_order.order_request_id,
                trade_decision_id=trade_decision_id,
            )
        except Exception:
            logger.warning(
                "symbol trade state order link sync failed: order_id=%s trade_decision_id=%s",
                validated_order.order_request_id,
                trade_decision_id,
                exc_info=True,
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
        _is_held_position_sell = is_held_position_sell_path(
            source_type=intent_source_type,
            decision_type=intent.ai_backend_inputs.decision_type,
            side=intent.request.side,
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
                    await self._record_blocking_guardrail_evaluation(
                        rule_set_version="stale_snapshot_guard_v1",
                        blocking_rule_codes=[
                            PipelineStopReason.STALE_SNAPSHOT_ACCOUNT.value
                        ],
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
                        decision_context_id=intent.decision_context_id,
                        trade_decision_id=trade_decision_id,
                        order_request_id=validated_order.order_request_id,
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
                        stop_reason=PipelineStopReason.STALE_SNAPSHOT.value,
                        order_request_id=validated_order.order_request_id,
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
                        stop_reason=PipelineStopReason.STALE_SNAPSHOT.value,
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
                    await self._record_blocking_guardrail_evaluation(
                        rule_set_version="stale_snapshot_guard_v1",
                        blocking_rule_codes=[PipelineStopReason.STALE_SNAPSHOT_RUN.value],
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
                        decision_context_id=intent.decision_context_id,
                        trade_decision_id=trade_decision_id,
                        order_request_id=validated_order.order_request_id,
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
                        stop_reason=PipelineStopReason.STALE_SNAPSHOT.value,
                        order_request_id=validated_order.order_request_id,
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
                        stop_reason=PipelineStopReason.STALE_SNAPSHOT.value,
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
                stop_reason=PipelineStopReason.TRANSITION_FAILED.value,
                order_request_id=validated_order.order_request_id,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"transition_to(PENDING_SUBMIT) failed: {exc}",
                stop_reason=PipelineStopReason.TRANSITION_FAILED.value,
                trade_decision_id=trade_decision_id,
                phase_trace=tuple(_phase_trace) if _phase_trace else (),
                status="ERROR",
                error_phase="transition",
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
                stop_reason=PipelineStopReason.BROKER_SUBMIT_FAILED.value,
                order_request_id=pending_order.order_request_id,
                phase_trace=_phase_trace,
            )
            return SubmitResult.build(
                order_intent=intent,
                error_message=f"submit_order_to_broker() failed: {exc}",
                stop_reason=PipelineStopReason.BROKER_SUBMIT_FAILED.value,
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

        result_stop_reason = (
            PipelineStopReason.ORDER_SUBMITTED.value
            if result_status == "SUBMITTED"
            else PipelineStopReason.ORDER_RECONCILE_REQUIRED.value
            if result_status == "RECONCILE_REQUIRED"
            else PipelineStopReason.ORDER_REJECTED.value
            if result_status == "REJECTED"
            else None
        )

        if result_status in ("RECONCILE_REQUIRED", "REJECTED") and result_stop_reason is not None:
            await self._record_blocking_guardrail_evaluation(
                rule_set_version="broker_submit_outcome_v1",
                blocking_rule_codes=[result_stop_reason],
                rule_results={
                    "account_id": (
                        str(account_id)
                        if account_id is not None
                        else None
                    ),
                    "symbol": submit_request.symbol,
                    "market": submit_request.market,
                    "source_type": (
                        intent.context.source_type
                        if intent.context is not None
                        else None
                    ),
                    "decision_type": _decision_type,
                    "order_status": final_status.value,
                    "status_reason_code": submitted_order.status_reason_code,
                },
                decision_context_id=intent.decision_context_id,
                trade_decision_id=trade_decision_id,
                order_request_id=submitted_order.order_request_id,
            )

        await self._finalize_attempt(
            attempt_id,
            "submitted" if result_status == "SUBMITTED"
            else "reconcile_required" if result_status == "RECONCILE_REQUIRED"
            else "failed" if result_status == "REJECTED"
            else "submitted",
            stop_phase="completed",
            stop_reason=result_stop_reason or "",
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
            stop_reason=result_stop_reason,
            status=result_status,
            submit_response=submitted_order,
        )
