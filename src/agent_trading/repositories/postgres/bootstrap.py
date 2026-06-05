"""Assemble a ``RepositoryContainer`` backed by PostgreSQL."""

from __future__ import annotations

from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.postgres.accounts import PostgresAccountRepository
from agent_trading.repositories.postgres.agent_runs import PostgresAgentRunRepository
from agent_trading.repositories.postgres.audit_logs import PostgresAuditLogRepository
from agent_trading.repositories.postgres.broker_accounts import (
    PostgresBrokerAccountRepository,
)
from agent_trading.repositories.postgres.broker_fill_snapshots import (
    PostgresBrokerFillSnapshotRepository,
)
from agent_trading.repositories.postgres.broker_orders import (
    PostgresBrokerOrderRepository,
)
from agent_trading.repositories.postgres.cash_balance_snapshots import (
    PostgresCashBalanceSnapshotRepository,
)
from agent_trading.repositories.postgres.clients import PostgresClientRepository
from agent_trading.repositories.postgres.config_versions import (
    PostgresConfigVersionRepository,
)
from agent_trading.repositories.postgres.decision_contexts import (
    PostgresDecisionContextRepository,
)
from agent_trading.repositories.postgres.execution_attempts import (
    PostgresExecutionAttemptRepository,
)
from agent_trading.repositories.postgres.external_events import (
    PostgresExternalEventRepository,
)
from agent_trading.repositories.postgres.fill_events import (
    PostgresFillEventRepository,
)
from agent_trading.repositories.postgres.fill_sync_runs import (
    PostgresFillSyncRunRepository,
)
from agent_trading.repositories.postgres.guardrail_evaluations import (
    PostgresGuardrailEvaluationRepository,
)
from agent_trading.repositories.postgres.instruments import (
    PostgresInstrumentRepository,
)
from agent_trading.repositories.postgres.market_sessions import (
    PostgresMarketSessionRepository,
)
from agent_trading.repositories.postgres.order_state_events import (
    PostgresOrderStateEventRepository,
)
from agent_trading.repositories.postgres.order_submission_attempts import (
    PostgresOrderSubmissionAttemptRepository,
)
from agent_trading.repositories.postgres.orders import PostgresOrderRepository
from agent_trading.repositories.postgres.position_snapshots import (
    PostgresPositionSnapshotRepository,
)
from agent_trading.repositories.postgres.reconciliation import (
    PostgresReconciliationRepository,
)
from agent_trading.repositories.postgres.risk_limit_snapshots import (
    PostgresRiskLimitSnapshotRepository,
)
from agent_trading.repositories.postgres.snapshot_sync_runs import (
    PostgresSnapshotSyncRunRepository,
)
from agent_trading.repositories.postgres.strategies import (
    PostgresStrategyRepository,
)
from agent_trading.repositories.postgres.trade_decisions import (
    PostgresTradeDecisionRepository,
)
from agent_trading.repositories.postgres_uow import PostgresUnitOfWork


def build_postgres_repositories(
    tx: TransactionManager,
) -> RepositoryContainer:
    """Assemble a ``RepositoryContainer`` backed by PostgreSQL.

    Milestone 6 expands the Postgres-backed set to include
    ``reconciliations`` in addition to the Milestone 5 set.

    Parameters
    ----------
    tx : TransactionManager
        An active transaction obtained from ``db.transaction()``.

    Returns
    -------
    RepositoryContainer
        A container whose ``unit_of_work``, ``clients``, ``accounts``,
        ``strategies``, ``config_versions``, ``decision_contexts``,
        ``instruments``, ``orders``, ``audit_logs``, ``broker_orders``,
        ``fill_events``, ``order_state_events``, ``guardrail_evaluations``,
        ``risk_limit_snapshots``, ``position_snapshots``,
        ``cash_balance_snapshots``, and ``reconciliations`` are backed by
        PostgreSQL.
    """
    return RepositoryContainer(
        unit_of_work=PostgresUnitOfWork(tx),
        agent_runs=PostgresAgentRunRepository(tx),
        execution_attempts=PostgresExecutionAttemptRepository(tx),
        clients=PostgresClientRepository(tx),
        accounts=PostgresAccountRepository(tx),
        strategies=PostgresStrategyRepository(tx),
        config_versions=PostgresConfigVersionRepository(tx),
        instruments=PostgresInstrumentRepository(tx),
        decision_contexts=PostgresDecisionContextRepository(tx),
        position_snapshots=PostgresPositionSnapshotRepository(tx),
        cash_balance_snapshots=PostgresCashBalanceSnapshotRepository(tx),
        trade_decisions=PostgresTradeDecisionRepository(tx),
        orders=PostgresOrderRepository(tx),
        broker_orders=PostgresBrokerOrderRepository(tx),
        fill_events=PostgresFillEventRepository(tx),
        broker_fill_snapshots=PostgresBrokerFillSnapshotRepository(tx),
        external_events=PostgresExternalEventRepository(tx),
        reconciliations=PostgresReconciliationRepository(tx),
        audit_logs=PostgresAuditLogRepository(tx),
        broker_accounts=PostgresBrokerAccountRepository(tx),
        snapshot_sync_runs=PostgresSnapshotSyncRunRepository(tx),
        fill_sync_runs=PostgresFillSyncRunRepository(tx),
        order_state_events=PostgresOrderStateEventRepository(tx),
        guardrail_evaluations=PostgresGuardrailEvaluationRepository(tx),
        risk_limit_snapshots=PostgresRiskLimitSnapshotRepository(tx),
        market_session_repo=PostgresMarketSessionRepository(tx),
        order_submission_attempts=PostgresOrderSubmissionAttemptRepository(tx),
    )
