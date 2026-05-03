from __future__ import annotations

from dataclasses import dataclass

from agent_trading.repositories.base import UnitOfWork
from agent_trading.repositories.contracts import (
    AccountRepository,
    AuditLogRepository,
    BrokerAccountRepository,
    BrokerOrderRepository,
    CashBalanceSnapshotRepository,
    ClientRepository,
    ConfigVersionRepository,
    DecisionContextRepository,
    ExternalEventRepository,
    FillEventRepository,
    GuardrailEvaluationRepository,
    InstrumentRepository,
    OrderRepository,
    OrderStateEventRepository,
    PositionSnapshotRepository,
    ReconciliationRepository,
    RiskLimitSnapshotRepository,
    StrategyRepository,
    TradeDecisionRepository,
)


@dataclass(slots=True, frozen=True)
class RepositoryContainer:
    unit_of_work: UnitOfWork
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
    reconciliations: ReconciliationRepository
    audit_logs: AuditLogRepository
    broker_accounts: BrokerAccountRepository
    order_state_events: OrderStateEventRepository
    guardrail_evaluations: GuardrailEvaluationRepository
    risk_limit_snapshots: RiskLimitSnapshotRepository
    external_events: ExternalEventRepository
