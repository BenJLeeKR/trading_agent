from __future__ import annotations

from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.memory import (
    InMemoryAccountRepository,
    InMemoryAgentRunRepository,
    InMemoryAuditLogRepository,
    InMemoryBrokerAccountRepository,
    InMemoryBrokerOrderRepository,
    InMemoryCashBalanceSnapshotRepository,
    InMemoryClientRepository,
    InMemoryConfigVersionRepository,
    InMemoryDecisionContextRepository,
    InMemoryExternalEventRepository,
    InMemoryFillEventRepository,
    InMemoryGuardrailEvaluationRepository,
    InMemoryInstrumentRepository,
    InMemoryOrderRepository,
    InMemoryOrderStateEventRepository,
    InMemoryPositionSnapshotRepository,
    InMemoryReconciliationRepository,
    InMemoryRiskLimitSnapshotRepository,
    InMemorySnapshotSyncRunRepository,
    InMemoryStrategyRepository,
    InMemoryTradeDecisionRepository,
    InMemoryUnitOfWork,
)


def build_in_memory_repositories() -> RepositoryContainer:
    return RepositoryContainer(
        unit_of_work=InMemoryUnitOfWork(),
        agent_runs=InMemoryAgentRunRepository(),
        clients=InMemoryClientRepository(),
        accounts=InMemoryAccountRepository(),
        strategies=InMemoryStrategyRepository(),
        config_versions=InMemoryConfigVersionRepository(),
        instruments=InMemoryInstrumentRepository(),
        decision_contexts=InMemoryDecisionContextRepository(),
        position_snapshots=InMemoryPositionSnapshotRepository(),
        cash_balance_snapshots=InMemoryCashBalanceSnapshotRepository(),
        trade_decisions=InMemoryTradeDecisionRepository(),
        orders=InMemoryOrderRepository(),
        broker_orders=InMemoryBrokerOrderRepository(),
        fill_events=InMemoryFillEventRepository(),
        external_events=InMemoryExternalEventRepository(),
        reconciliations=InMemoryReconciliationRepository(),
        audit_logs=InMemoryAuditLogRepository(),
        broker_accounts=InMemoryBrokerAccountRepository(),
        snapshot_sync_runs=InMemorySnapshotSyncRunRepository(),
        order_state_events=InMemoryOrderStateEventRepository(),
        guardrail_evaluations=InMemoryGuardrailEvaluationRepository(),
        risk_limit_snapshots=InMemoryRiskLimitSnapshotRepository(),
    )
