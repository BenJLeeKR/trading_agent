from __future__ import annotations

from dataclasses import dataclass

from agent_trading.repositories.base import UnitOfWork
from agent_trading.repositories.contracts import (
    AccountRepository,
    AgentRunRepository,
    AuditLogRepository,
    BrokerAccountRepository,
    BrokerFillSnapshotRepository,
    BrokerOrderRepository,
    CashBalanceSnapshotRepository,
    ClientRepository,
    ConfigVersionRepository,
    DecisionContextRepository,
    ExecutionAttemptRepository,
    ExternalEventRepository,
    FillEventRepository,
    FillSyncRunRepository,
    GuardrailEvaluationRepository,
    HistoricalBuyFeeOverlayRepository,
    InstrumentIndexMembershipRepository,
    InstrumentStatusSnapshotRepository,
    InstrumentRepository,
    KisFillCumulativeStateRepository,
    MarketSessionRepository,
    OrderRepository,
    OrderStateEventRepository,
    PositionCostBasisStateRepository,
    PositionSnapshotRepository,
    ReconciliationRepository,
    RealizedPnlComputationRunRepository,
    RealizedPnlDailyAggregateRepository,
    RealizedPnlEventRepository,
    RealizedPnlRecomputeQueueRepository,
    RiskLimitSnapshotRepository,
    SignalFeatureSnapshotRepository,
    SignalFeatureBatchRunRepository,
    SignalFeatureBatchRunItemRepository,
    SnapshotSyncRunRepository,
    OrderSubmissionAttemptRepository,
    StrategyRepository,
    SymbolTradeStateRepository,
    TradeDecisionRepository,
    UniverseFreezeRunItemRepository,
    UniverseFreezeRunRepository,
)


@dataclass(slots=True, frozen=True)
class RepositoryContainer:
    unit_of_work: UnitOfWork
    agent_runs: AgentRunRepository
    execution_attempts: ExecutionAttemptRepository
    clients: ClientRepository
    accounts: AccountRepository
    strategies: StrategyRepository
    config_versions: ConfigVersionRepository
    instruments: InstrumentRepository
    decision_contexts: DecisionContextRepository
    position_snapshots: PositionSnapshotRepository
    cash_balance_snapshots: CashBalanceSnapshotRepository
    trade_decisions: TradeDecisionRepository
    orders: OrderRepository
    broker_orders: BrokerOrderRepository
    fill_events: FillEventRepository
    broker_fill_snapshots: BrokerFillSnapshotRepository
    kis_fill_cumulative_state: KisFillCumulativeStateRepository
    reconciliations: ReconciliationRepository
    audit_logs: AuditLogRepository
    broker_accounts: BrokerAccountRepository
    snapshot_sync_runs: SnapshotSyncRunRepository
    fill_sync_runs: FillSyncRunRepository
    order_state_events: OrderStateEventRepository
    guardrail_evaluations: GuardrailEvaluationRepository
    risk_limit_snapshots: RiskLimitSnapshotRepository
    signal_feature_snapshots: SignalFeatureSnapshotRepository
    signal_feature_batch_runs: SignalFeatureBatchRunRepository
    signal_feature_batch_run_items: SignalFeatureBatchRunItemRepository
    instrument_index_memberships: InstrumentIndexMembershipRepository
    instrument_status_snapshots: InstrumentStatusSnapshotRepository
    symbol_trade_states: SymbolTradeStateRepository
    universe_freeze_runs: UniverseFreezeRunRepository
    universe_freeze_run_items: UniverseFreezeRunItemRepository
    external_events: ExternalEventRepository
    market_session_repo: MarketSessionRepository
    order_submission_attempts: OrderSubmissionAttemptRepository
    position_cost_basis_states: PositionCostBasisStateRepository
    realized_pnl_events: RealizedPnlEventRepository
    realized_pnl_daily_aggregates: RealizedPnlDailyAggregateRepository
    realized_pnl_computation_runs: RealizedPnlComputationRunRepository
    realized_pnl_recompute_queue: RealizedPnlRecomputeQueueRepository
    historical_buy_fee_overlays: HistoricalBuyFeeOverlayRepository
