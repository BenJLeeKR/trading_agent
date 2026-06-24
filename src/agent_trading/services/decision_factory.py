"""Decision pipeline factory — TradeDecisionEntity and DecisionContextService.

Extracted from DecisionOrchestratorService to separate persistence/factory
responsibilities from decision orchestration logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg

from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup
from agent_trading.services.ai_agents.korean_normalizer import (
    validate_or_normalize_korean,
)
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AIDecisionInputs,
    AssembledContext,
    ScoreResult,
)
from agent_trading.services.common_types import (
    dataclass_to_dict,  # noqa: F401  (moved from decision_orchestrator in Phase 4 Subtask 3/5)
)
from agent_trading.services.common_types import AgentExecutionBundle
from agent_trading.services.translation import (
    calculate_max_order_value,
    decimal_or_none,
    resolve_decision_type,
    resolve_entry_style,
    resolve_order_side,
)

logger = logging.getLogger(__name__)

_ACTIONABLE_DECISION_TYPES = {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE"}


# ---------------------------------------------------------------------------
# Factory: TradeDecisionEntity
# ---------------------------------------------------------------------------


def build_trade_decision_entity(
    *,
    decision_context_id: UUID | None,
    request: SubmitOrderRequest,
    assembled_context: AssembledContext,
    agent_bundle: AgentExecutionBundle,
    instrument_id: UUID | None = None,
    fdc_run_id: UUID | None = None,
) -> TradeDecisionEntity | None:
    """순수 factory: TradeDecisionEntity 생성만 담당.

    Repository 호출은 포함하지 않음 (orchestrator 또는 호출자에서 처리).

    Returns
    -------
    TradeDecisionEntity | None
        ``None`` when ``decision_context_id`` is ``None``,
        ``assembled_context.decision_context`` is ``None``, or
        ``agent_bundle.composer_output`` is ``None``.
    """
    if decision_context_id is None:
        return None

    decision_context = assembled_context.decision_context
    if decision_context is None:
        return None

    composer_output = agent_bundle.composer_output
    if composer_output is None:
        return None

    ai_inputs = agent_bundle.ai_inputs
    candidate_vs_final = _build_candidate_vs_final_summary(
        assembled_context=assembled_context,
        composer_output=composer_output,
    )

    now = datetime.now(timezone.utc)

    decision = TradeDecisionEntity(
        trade_decision_id=uuid4(),
        decision_context_id=decision_context_id,
        decision_type=resolve_decision_type(composer_output.decision_type),
        side=resolve_order_side(composer_output.side, request.side),
        strategy_id=decision_context.strategy_id,
        symbol=request.symbol,
        market=request.market,
        entry_style=resolve_entry_style(
            composer_output.entry_style,
            request.order_type,
        ),
        created_at=now,
        # --- Axis 2: Source type ---
        source_type=assembled_context.source_type,
        agent_run_id=fdc_run_id,
        instrument_id=instrument_id,
        entry_price=decimal_or_none(request.price),
        quantity=decimal_or_none(request.quantity),
        max_order_value=calculate_max_order_value(
            request.price,
            request.quantity,
        ),
        expected_return_bps=ai_inputs.expected_return_bps,
        expected_downside_bps=ai_inputs.expected_downside_bps,
        net_expected_value_bps=ai_inputs.net_expected_value_bps,
        final_trade_score=ai_inputs.final_trade_score,
        minimum_required_edge_bps=ai_inputs.minimum_required_edge_bps,
        confidence=Decimal(str(composer_output.confidence)),
        risk_check_passed=ai_inputs.risk_opinion in {"allow", "reduce"},
        failed_rule_codes=(
            list(ai_inputs.expected_value_gate_reason_codes)
            if (
                not ai_inputs.expected_value_gate_passed
                and ai_inputs.expected_value_gate_reason_codes
            )
            else None
        ),
        regime_label=(
            assembled_context.market_regime.regime_label
            if assembled_context.market_regime is not None
            else None
        ),
        strategy_fit_score=(
            Decimal(str(assembled_context.strategy_selection.confidence))
            if assembled_context.strategy_selection is not None
            else None
        ),
        reason_codes=list(composer_output.reason_codes) or None,
        opposing_evidence={
            "items": [
                validate_or_normalize_korean(item)
                for item in composer_output.opposing_evidence
            ],
        }
        if composer_output.opposing_evidence
        else {},
        exit_plan_json=dataclass_to_dict(composer_output.exit_plan_hint),
        calculation_version="decision_orchestrator.v1",
        agent_version_json=dict(ai_inputs.schema_versions),
        rationale_summary=validate_or_normalize_korean(
            composer_output.summary or None
        ),
        decision_json={
            "decision_type": composer_output.decision_type,
            "side": composer_output.side,
            "entry_style": composer_output.entry_style,
            "time_horizon": composer_output.time_horizon,
            "event_bias": ai_inputs.event_bias,
            "event_conflict": ai_inputs.event_conflict,
            "event_reason_codes": list(ai_inputs.event_reason_codes),
            "evidence_strength": ai_inputs.evidence_strength,
            "no_material_events": ai_inputs.no_material_events,
            "detected_event_count": ai_inputs.detected_event_count,
            "interpreted_event_count": ai_inputs.interpreted_event_count,
            "risk_reason_codes": list(ai_inputs.risk_reason_codes),
            "reason_codes": list(ai_inputs.reason_codes),
            "opposing_evidence": list(ai_inputs.opposing_evidence),
            "confidence": ai_inputs.confidence,
            "conviction": ai_inputs.conviction,
            "risk_opinion": ai_inputs.risk_opinion,
            "risk_flags": list(ai_inputs.risk_flags),
            "ai_call_path": {
                "ei_skipped": ai_inputs.ei_skipped,
                "ar_skipped": ai_inputs.ar_skipped,
                "fdc_skipped": ai_inputs.fdc_skipped,
                "skip_reason_codes": list(ai_inputs.skip_reason_codes),
            },
            "strategy_selection": (
                {
                    "preferred_strategy": (
                        assembled_context.strategy_selection.preferred_strategy
                    ),
                    "allowed_strategies": list(
                        assembled_context.strategy_selection.allowed_strategies
                    ),
                    "preferred_entry_style": (
                        assembled_context.strategy_selection.preferred_entry_style
                    ),
                    "preferred_time_horizon": (
                        assembled_context.strategy_selection.preferred_time_horizon
                    ),
                    "confidence": assembled_context.strategy_selection.confidence,
                    "reason_codes": list(
                        assembled_context.strategy_selection.reason_codes
                    ),
                    "metadata": dict(
                        assembled_context.strategy_selection.metadata
                    ),
                }
                if assembled_context.strategy_selection is not None
                else None
            ),
            "instrument_profile": {
                "market_segment": assembled_context.instrument_market_segment,
                "index_memberships": list(
                    assembled_context.instrument_index_memberships
                ),
            },
            "portfolio_allocation": (
                {
                    "target_weight_pct": (
                        assembled_context.portfolio_allocation.target_weight_pct
                    ),
                    "current_weight_pct": (
                        assembled_context.portfolio_allocation.current_weight_pct
                    ),
                    "max_single_position_pct": (
                        assembled_context.portfolio_allocation.max_single_position_pct
                    ),
                    "remaining_concentration_pct": (
                        assembled_context.portfolio_allocation.remaining_concentration_pct
                    ),
                    "remaining_gross_budget_pct": (
                        assembled_context.portfolio_allocation.remaining_gross_budget_pct
                    ),
                    "max_new_capital_pct": (
                        assembled_context.portfolio_allocation.max_new_capital_pct
                    ),
                    "orderable_cash": (
                        str(assembled_context.portfolio_allocation.orderable_cash)
                        if assembled_context.portfolio_allocation.orderable_cash is not None
                        else None
                    ),
                    "available_allocation_cash": (
                        str(
                            assembled_context.portfolio_allocation.available_allocation_cash
                        )
                        if assembled_context.portfolio_allocation.available_allocation_cash
                        is not None
                        else None
                    ),
                    "recommended_max_order_value": (
                        str(
                            assembled_context.portfolio_allocation.recommended_max_order_value
                        )
                        if assembled_context.portfolio_allocation.recommended_max_order_value
                        is not None
                        else None
                    ),
                    "allocation_bias": (
                        assembled_context.portfolio_allocation.allocation_bias
                    ),
                    "confidence": (
                        assembled_context.portfolio_allocation.confidence
                    ),
                    "reason_codes": list(
                        assembled_context.portfolio_allocation.reason_codes
                    ),
                    "metadata": dict(
                        assembled_context.portfolio_allocation.metadata
                    ),
                }
                if assembled_context.portfolio_allocation is not None
                else None
            ),
            "deterministic_trigger": (
                {
                    "trigger_version": (
                        assembled_context.deterministic_trigger.trigger_version
                    ),
                    "primary_candidate": (
                        assembled_context.deterministic_trigger.primary_candidate
                    ),
                    "candidate_set": list(
                        assembled_context.deterministic_trigger.candidate_set
                    ),
                    "watch_candidate": (
                        assembled_context.deterministic_trigger.watch_candidate
                    ),
                    "buy_candidate": (
                        assembled_context.deterministic_trigger.buy_candidate
                    ),
                    "sell_candidate": (
                        assembled_context.deterministic_trigger.sell_candidate
                    ),
                    "reduce_candidate": (
                        assembled_context.deterministic_trigger.reduce_candidate
                    ),
                    "candidate_confidence": (
                        assembled_context.deterministic_trigger.candidate_confidence
                    ),
                    "entry_score": (
                        assembled_context.deterministic_trigger.entry_score
                    ),
                    "exit_score": (
                        assembled_context.deterministic_trigger.exit_score
                    ),
                    "watch_score": (
                        assembled_context.deterministic_trigger.watch_score
                    ),
                    "eligibility_passed": (
                        assembled_context.deterministic_trigger.eligibility_passed
                    ),
                    "eligibility_reasons": list(
                        assembled_context.deterministic_trigger.eligibility_reasons
                    ),
                    "coverage_score": (
                        assembled_context.deterministic_trigger.coverage_score
                    ),
                    "ranking_score": (
                        assembled_context.deterministic_trigger.ranking_score
                    ),
                    "ranking_percentile": (
                        assembled_context.deterministic_trigger.ranking_percentile
                    ),
                    "ranking_bucket": (
                        assembled_context.deterministic_trigger.ranking_bucket
                    ),
                    "candidate_mode": (
                        assembled_context.deterministic_trigger.candidate_mode
                    ),
                    "reason_codes": list(
                        assembled_context.deterministic_trigger.reason_codes
                    ),
                    "thresholds": dict(
                        assembled_context.deterministic_trigger.thresholds
                    ),
                    "metadata": dict(
                        assembled_context.deterministic_trigger.metadata
                    ),
                }
                if assembled_context.deterministic_trigger is not None
                else None
            ),
            "candidate_vs_final": candidate_vs_final,
            "expected_value_gate": {
                "passed": ai_inputs.expected_value_gate_passed,
                "reason_codes": list(ai_inputs.expected_value_gate_reason_codes),
                "expected_return_bps": (
                    str(ai_inputs.expected_return_bps)
                    if ai_inputs.expected_return_bps is not None
                    else None
                ),
                "expected_downside_bps": (
                    str(ai_inputs.expected_downside_bps)
                    if ai_inputs.expected_downside_bps is not None
                    else None
                ),
                "net_expected_value_bps": (
                    str(ai_inputs.net_expected_value_bps)
                    if ai_inputs.net_expected_value_bps is not None
                    else None
                ),
                "final_trade_score": (
                    str(ai_inputs.final_trade_score)
                    if ai_inputs.final_trade_score is not None
                    else None
                ),
                "minimum_required_edge_bps": (
                    str(ai_inputs.minimum_required_edge_bps)
                    if ai_inputs.minimum_required_edge_bps is not None
                    else None
                ),
                "edge_after_cost_bps": (
                    str(ai_inputs.edge_after_cost_bps)
                    if ai_inputs.edge_after_cost_bps is not None
                    else None
                ),
                "estimated_round_trip_cost_bps": (
                    str(ai_inputs.estimated_round_trip_cost_bps)
                    if ai_inputs.estimated_round_trip_cost_bps is not None
                    else None
                ),
                "slippage_buffer_bps": (
                    str(ai_inputs.slippage_buffer_bps)
                    if ai_inputs.slippage_buffer_bps is not None
                    else None
                ),
            },
            "execution_preferences": dataclass_to_dict(
                composer_output.execution_preferences
            ),
            "sizing_hint": dataclass_to_dict(composer_output.sizing_hint),
        },
    )
    return decision


def _build_candidate_vs_final_summary(
    *,
    assembled_context: AssembledContext,
    composer_output: FinalDecisionComposerOutput,
) -> dict[str, object] | None:
    trigger = assembled_context.deterministic_trigger
    if trigger is None:
        return None

    candidate_intent = _map_candidate_to_intent(trigger.primary_candidate)
    final_intent = _map_decision_type_to_intent(composer_output.decision_type)
    alignment_status = _classify_alignment_status(
        candidate_intent=candidate_intent,
        final_intent=final_intent,
    )
    return {
        "primary_candidate": trigger.primary_candidate,
        "candidate_set": list(trigger.candidate_set),
        "candidate_intent": candidate_intent,
        "candidate_confidence": trigger.candidate_confidence,
        "final_decision_type": composer_output.decision_type,
        "final_intent": final_intent,
        "final_actionable": composer_output.decision_type in _ACTIONABLE_DECISION_TYPES,
        "override_applied": candidate_intent != final_intent,
        "alignment_status": alignment_status,
    }


def _map_candidate_to_intent(candidate: str) -> str:
    normalized = (candidate or "NO_ACTION").strip().upper()
    if normalized == "BUY_CANDIDATE":
        return "buy"
    if normalized in {"SELL_CANDIDATE", "REDUCE_CANDIDATE"}:
        return "sell"
    if normalized == "WATCH":
        return "watch"
    return "no_action"


def _map_decision_type_to_intent(decision_type: str) -> str:
    normalized = (decision_type or "HOLD").strip().upper()
    if normalized in {"APPROVE", "BUY"}:
        return "buy"
    if normalized in {"SELL", "EXIT", "REDUCE"}:
        return "sell"
    if normalized == "WATCH":
        return "watch"
    return "no_action"


def _classify_alignment_status(
    *,
    candidate_intent: str,
    final_intent: str,
) -> str:
    if candidate_intent == final_intent:
        return "matched"
    if candidate_intent == "watch" and final_intent in {"buy", "sell"}:
        return "upgraded"
    if candidate_intent in {"buy", "sell"} and final_intent in {"watch", "no_action"}:
        return "downgraded"
    if candidate_intent == "no_action" and final_intent != "no_action":
        return "promoted_from_no_action"
    if candidate_intent != "no_action" and final_intent == "no_action":
        return "suppressed"
    return "diverged"


# ---------------------------------------------------------------------------
# DecisionContextService
# ---------------------------------------------------------------------------


class DecisionContextService:
    """DecisionContext lifecycle management — persistence/factory 책임.

    Extracted from DecisionOrchestratorService to separate
    context resolution from decision orchestration.
    """

    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos
        self._logger = logging.getLogger(self.__class__.__name__)

    async def _select_usable_cash_snapshot(
        self,
        account_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        try:
            snapshots = await self._repos.cash_balance_snapshots.list_by_account(
                account_id,
            )
        except Exception:
            self._logger.debug(
                "Unable to list cash balance snapshots for account=%s",
                account_id,
                exc_info=True,
            )
            return None

        latest_any = snapshots[0] if snapshots else None
        for snapshot in snapshots:
            if snapshot.fetch_status == "success":
                return snapshot
        return latest_any

    async def ensure_or_create(
        self,
        request: SubmitOrderRequest,
        existing_context_id: UUID | None,
    ) -> UUID | None:
        """기존 DecisionContext를 찾거나 새로 생성.

        Extracted from _ensure_or_create_decision_context().

        Strategy
        --------
        1. ``existing_context_id``가 제공되면 → DB 존재 여부와 관계없이 그 ID를 반환.
           (caller가 명시적으로 ID를 제공했으므로 책임을 가짐)
        2. ``existing_context_id``가 ``None``이면 → request fields에서 FK chain을
           resolve하여 새 context 생성:
           - ``request.account_ref`` → ``repos.accounts.find_one()`` → ``account_id``
           - ``request.strategy_id`` → ``UUID`` 파싱 → ``strategy_id``
           - ``account.client_id + account.environment`` → ``repos.config_versions.get_active()``
        3. **3개 조건이 모두 충족될 때만** 생성하고, 하나라도 실패하면 ``None`` 반환 (fail-open).

        Returns
        -------
        UUID | None
            유효한 ``decision_context_id`` 또는 ``None`` (생성 불가).
        """
        # Case 1: existing_context_id가 제공됨 → caller가 책임지고 사용
        if existing_context_id is not None:
            return existing_context_id

        # Case 2: request fields에서 FK chain resolution
        try:
            # 조건 1: account_ref → account
            account = await self._repos.accounts.find_one(
                AccountLookup(account_alias=request.account_ref)
            )
            if account is None:
                self._logger.warning(
                    "Cannot create decision context: account not found for ref=%s",
                    request.account_ref,
                )
                return None

            # 조건 2: strategy_id UUID 파싱
            try:
                strategy_id = UUID(request.strategy_id)
            except (ValueError, AttributeError):
                self._logger.warning(
                    "Cannot create decision context: invalid strategy_id=%s",
                    request.strategy_id,
                )
                return None

            # 조건 3: client_id + environment → active config version
            config_version = await self._repos.config_versions.get_active(
                client_id=account.client_id,
                environment=account.environment,
            )
            if config_version is None:
                self._logger.warning(
                    "Cannot create decision context: no active config version "
                    "for client=%s env=%s",
                    account.client_id,
                    account.environment,
                )
                return None

            # Best-effort snapshot anchoring for replayability and agent context.
            position_snapshot_id: UUID | None = None
            cash_balance_snapshot_id: UUID | None = None
            try:
                instrument = await self._repos.instruments.get_by_symbol(
                    symbol=request.symbol,
                    market_code=request.market,
                )
                if instrument is not None:
                    positions = (
                        await self._repos.position_snapshots.list_latest_by_account(
                            account.account_id,
                        )
                    )
                    for snapshot in positions:
                        if snapshot.instrument_id == instrument.instrument_id:
                            position_snapshot_id = snapshot.position_snapshot_id
                            break
            except Exception:
                self._logger.debug(
                    "Unable to anchor latest position snapshot for symbol=%s market=%s",
                    request.symbol,
                    request.market,
                    exc_info=True,
                )

            cash = await self._select_usable_cash_snapshot(account.account_id)
            if cash is not None:
                cash_balance_snapshot_id = cash.cash_balance_snapshot_id

            # --- 모든 조건 충족 → DecisionContextEntity 생성 ---
            now = datetime.now(timezone.utc)
            context_id = existing_context_id or uuid4()
            correlation_id = request.correlation_id or str(uuid4())

            context = DecisionContextEntity(
                decision_context_id=context_id,
                account_id=account.account_id,
                strategy_id=strategy_id,
                config_version_id=config_version.config_version_id,
                position_snapshot_id=position_snapshot_id,
                cash_balance_snapshot_id=cash_balance_snapshot_id,
                market_timestamp=now,
                correlation_id=correlation_id,
                created_at=now,
            )

            # Savepoint-protected insert: UniqueViolationError 격리
            # PostgreSQL nested connection.transaction() creates a savepoint,
            # so a UniqueViolationError only rolls back the savepoint, not
            # the outer transaction. In-memory UoW has no connection attr.
            try:
                conn = getattr(self._repos.unit_of_work, "connection", None)
                if conn is not None:
                    async with conn.transaction():
                        saved = await self._repos.decision_contexts.add(context)
                else:
                    saved = await self._repos.decision_contexts.add(context)
            except asyncpg.exceptions.UniqueViolationError:
                self._logger.warning(
                    "correlation_id=%s already exists — savepoint rollback, "
                    "continuing with decision_context_id=None",
                    correlation_id,
                )
                return None

            self._logger.info(
                "Created decision context: id=%s account_id=%s strategy_id=%s "
                "correlation_id=%s",
                saved.decision_context_id,
                saved.account_id,
                saved.strategy_id,
                saved.correlation_id,
            )
            return saved.decision_context_id

        except Exception:
            self._logger.warning(
                "Failed to create decision context — agent runs will proceed "
                "without persistence. account_ref=%s",
                request.account_ref,
                exc_info=True,
            )
            return None

    async def resolve(self, decision_context_id: UUID) -> DecisionContextEntity | None:
        """ID로 DecisionContext 조회.

        Extracted from _resolve_decision_context().

        Returns ``None`` if the context is not found or on error.
        """
        try:
            return await self._repos.decision_contexts.get(decision_context_id)
        except Exception:
            pass
        return None

    async def resolve_active(self) -> UUID | None:
        """Future hook: active context 조회 (현재는 항상 None).

        Extracted from _resolve_active_context().

        .. note::
           This is a future hook. The current implementation always returns
           ``None`` because ``DecisionContextQuery`` does not yet support a
           ``status`` filter. Once the query model is extended, this method
           should query for active contexts and return the most recent one.

        Returns ``None`` (future hook).
        """
        # Future: query decision_contexts with status="active" filter
        # once DecisionContextQuery supports it.
        return None
