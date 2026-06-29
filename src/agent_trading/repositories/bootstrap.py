from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.memory import (
    InMemoryAccountRepository,
    InMemoryAgentRunRepository,
    InMemoryAuditLogRepository,
    InMemoryBrokerAccountRepository,
    InMemoryBrokerFillSnapshotRepository,
    InMemoryBrokerOrderRepository,
    InMemoryCashBalanceSnapshotRepository,
    InMemoryClientRepository,
    InMemoryConfigVersionRepository,
    InMemoryDecisionContextRepository,
    InMemoryExecutionAttemptRepository,
    InMemoryExternalEventRepository,
    InMemoryFillEventRepository,
    InMemoryFillSyncRunRepository,
    InMemoryGuardrailEvaluationRepository,
    InMemoryInstrumentIndexMembershipRepository,
    InMemoryInstrumentStatusSnapshotRepository,
    InMemoryInstrumentRepository,
    InMemoryMarketSessionRepository,
    InMemoryOrderRepository,
    InMemoryOrderStateEventRepository,
    InMemoryOrderSubmissionAttemptRepository,
    InMemoryPositionSnapshotRepository,
    InMemoryReconciliationRepository,
    InMemoryRiskLimitSnapshotRepository,
    InMemorySignalFeatureSnapshotRepository,
    InMemorySignalFeatureBatchRunRepository,
    InMemorySignalFeatureBatchRunItemRepository,
    InMemorySnapshotSyncRunRepository,
    InMemoryStrategyRepository,
    InMemorySymbolTradeStateRepository,
    InMemoryTradeDecisionRepository,
    InMemoryUniverseFreezeRunItemRepository,
    InMemoryUniverseFreezeRunRepository,
    InMemoryUnitOfWork,
)
from agent_trading.domain.entities import SnapshotSyncRunEntity


def _seed_fresh_sync_run(
    repo: InMemorySnapshotSyncRunRepository,
) -> None:
    """Seed a completed snapshot sync run so ``is_stale=False`` by default.

    Without this seed every ``DecisionOrchestratorService`` instance
    created with ``build_in_memory_repositories()`` would immediately
    block at Phase 4c (stale snapshot guard) because the run history
    is empty — ``get_sync_health_summary()`` returns ``is_stale=True``.

    Tests that exercise the stale path (e.g. Scenario 4) must explicitly
    clear ``repos.snapshot_sync_runs._items`` before creating the service.
    """
    now = datetime.now(timezone.utc)
    run = SnapshotSyncRunEntity(
        snapshot_sync_run_id=uuid4(),
        trigger_type="scheduler",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        positions_synced_total=10,
        positions_skipped_total=0,
        cash_synced_count=1,
        error_count=0,
        status="completed",
        started_at=now,
        completed_at=now,
    )
    repo._items[run.snapshot_sync_run_id] = run  # type: ignore[attr-defined]


def build_in_memory_repositories() -> RepositoryContainer:
    repos = RepositoryContainer(
        unit_of_work=InMemoryUnitOfWork(),
        agent_runs=InMemoryAgentRunRepository(),
        execution_attempts=InMemoryExecutionAttemptRepository(),
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
        broker_fill_snapshots=InMemoryBrokerFillSnapshotRepository(),
        external_events=InMemoryExternalEventRepository(),
        reconciliations=InMemoryReconciliationRepository(),
        audit_logs=InMemoryAuditLogRepository(),
        broker_accounts=InMemoryBrokerAccountRepository(),
        snapshot_sync_runs=InMemorySnapshotSyncRunRepository(),
        fill_sync_runs=InMemoryFillSyncRunRepository(),
        order_state_events=InMemoryOrderStateEventRepository(),
        guardrail_evaluations=InMemoryGuardrailEvaluationRepository(),
        risk_limit_snapshots=InMemoryRiskLimitSnapshotRepository(),
        signal_feature_snapshots=InMemorySignalFeatureSnapshotRepository(),
        signal_feature_batch_runs=InMemorySignalFeatureBatchRunRepository(),
        signal_feature_batch_run_items=InMemorySignalFeatureBatchRunItemRepository(),
        instrument_index_memberships=InMemoryInstrumentIndexMembershipRepository(),
        instrument_status_snapshots=InMemoryInstrumentStatusSnapshotRepository(),
        symbol_trade_states=InMemorySymbolTradeStateRepository(),
        universe_freeze_runs=InMemoryUniverseFreezeRunRepository(),
        universe_freeze_run_items=InMemoryUniverseFreezeRunItemRepository(),
        market_session_repo=InMemoryMarketSessionRepository(),
        order_submission_attempts=InMemoryOrderSubmissionAttemptRepository(),
    )
    # Seed a fresh sync run so pipelines work out of the box.
    _seed_fresh_sync_run(repos.snapshot_sync_runs)
    return repos
