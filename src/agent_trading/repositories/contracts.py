from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from agent_trading.domain.entities import (
    AccountEntity,
    AgentRunEntity,
    AuditLogEntity,
    BlockingLockEntity,
    BrokerAccountEntity,
    BrokerOrderEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    FillEventEntity,
    GuardrailEvaluationEntity,
    InstrumentEntity,
    MarketSessionEntity,
    OrderRequestEntity,
    OrderStateEventEntity,
    PositionSnapshotEntity,
    ReconciliationOrderLinkEntity,
    ReconciliationPositionLinkEntity,
    ReconciliationRunEntity,
    RiskLimitSnapshotEntity,
    SessionEventEntity,
    SnapshotSyncRunEntity,
    StrategyEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import Environment, OrderStatus
from agent_trading.repositories.filters import AccountLookup, DecisionContextQuery, OrderQuery


@dataclass(slots=True, frozen=True)
class SnapshotSyncHealthSummary:
    """Freshness/health summary for the most recent snapshot sync runs.

    Computed by :meth:`SnapshotSyncRunRepository.get_sync_health_summary`.
    """

    last_run_started_at: datetime | None
    """``started_at`` of the most recent run, or ``None`` if no runs exist."""

    last_run_completed_at: datetime | None
    """``completed_at`` of the most recent run, or ``None`` if no runs exist."""

    last_status: str | None
    """``status`` of the most recent run (e.g. ``"completed"``, ``"failed"``)."""

    last_successful_run_at: datetime | None
    """``started_at`` of the most recent ``status == 'completed'`` run."""

    consecutive_failures: int
    """Number of consecutive ``status == 'failed'`` runs (reverse chronological)."""

    is_stale: bool
    """``True`` when ``now - last_successful_run_at > stale_threshold_seconds``."""

    stale_threshold_seconds: int
    """The threshold used for the staleness computation."""

    after_hours: bool = False
    """``True`` when the most recent run was an after-hours (cash-only) sync."""


class ClientRepository(Protocol):
    async def add(self, client: ClientEntity) -> ClientEntity:
        ...

    async def get(self, client_id: UUID) -> ClientEntity | None:
        ...

    async def get_by_code(self, client_code: str) -> ClientEntity | None:
        ...

    async def list_all(self) -> Sequence[ClientEntity]:
        ...


class BrokerAccountRepository(Protocol):
    async def add(self, broker_account: BrokerAccountEntity) -> BrokerAccountEntity:
        ...

    async def get(self, broker_account_id: UUID) -> BrokerAccountEntity | None:
        ...

    async def get_by_ref(
        self,
        broker_name: str,
        account_ref: str,
        environment: Environment,
    ) -> BrokerAccountEntity | None:
        ...

    async def list_by_broker(self, broker_name: str) -> Sequence[BrokerAccountEntity]:
        ...

    async def list_by_broker_and_env(
        self,
        broker_name: str,
        env: Environment,
    ) -> Sequence[BrokerAccountEntity]:
        """List broker accounts filtered by broker name and environment."""
        ...

    async def list_by_account_id(
        self,
        account_id: UUID,
    ) -> Sequence[BrokerAccountEntity]:
        """List broker accounts linked to the given account ID.

        Uses a JOIN with ``trading.accounts`` to resolve
        ``account_id → broker_account_id``.

        Parameters
        ----------
        account_id : UUID
            The account whose broker accounts to list.

        Returns
        -------
        Sequence[BrokerAccountEntity]
            Matching broker accounts (usually 0 or 1 per account).
        """
        ...


class AccountRepository(Protocol):
    async def add(self, account: AccountEntity) -> AccountEntity:
        ...

    async def get(self, account_id: UUID) -> AccountEntity | None:
        ...

    async def find_one(self, lookup: AccountLookup) -> AccountEntity | None:
        ...

    async def list_by_client(self, client_id: UUID) -> Sequence[AccountEntity]:
        ...

    async def update_metadata(
        self,
        account_id: UUID,
        *,
        account_masked: str | None = None,
    ) -> AccountEntity | None:
        """Update mutable metadata fields on an existing account.

        Currently supports ``account_masked`` only.  Returns the updated
        ``AccountEntity``, or ``None`` if the account does not exist.
        """
        ...


class StrategyRepository(Protocol):
    async def add(self, strategy: StrategyEntity) -> StrategyEntity:
        ...

    async def get(self, strategy_id: UUID) -> StrategyEntity | None:
        ...

    async def get_by_code(self, client_id: UUID, strategy_code: str) -> StrategyEntity | None:
        ...


class ConfigVersionRepository(Protocol):
    """Store for configuration version snapshots.

    ConfigVersion records freeze the configuration state at a point in time.
    This is a replay-critical repository — ``get_active()`` and
    ``get_active_at()`` are used to restore the configuration that was
    active at a given time during replay.
    """

    async def add(self, config_version: ConfigVersionEntity) -> ConfigVersionEntity:
        ...

    async def get(self, config_version_id: UUID) -> ConfigVersionEntity | None:
        ...

    async def get_active(
        self, client_id: UUID, environment: Environment
    ) -> ConfigVersionEntity | None:
        ...

    async def get_active_at(
        self, client_id: UUID, environment: Environment, at: datetime
    ) -> ConfigVersionEntity | None:
        """Return the config version that was active at the given timestamp.

        Selects the most recently activated version where ``activated_at <= at``.
        Returns ``None`` if no version was activated before the given timestamp.

        This is critical for replay: to reconstruct the system state at a
        specific point in time, we need the config that was governing at that time.
        """
        ...


class InstrumentRepository(Protocol):
    async def add(self, instrument: InstrumentEntity) -> InstrumentEntity:
        ...

    async def get(self, instrument_id: UUID) -> InstrumentEntity | None:
        ...

    async def get_by_symbol(self, symbol: str, market_code: str) -> InstrumentEntity | None:
        ...

    async def get_by_symbol_any_market(self, symbol: str) -> InstrumentEntity | None:
        """Lookup instrument by symbol across all markets.

        Returns the first matching instrument regardless of market,
        or ``None`` if not found.  Used when the caller does not know
        the market code (e.g. lock enrichment).
        """
        ...

    async def upsert_by_symbol(self, instrument: InstrumentEntity) -> InstrumentEntity:
        """INSERT … ON CONFLICT (symbol, market_code) DO UPDATE … RETURNING *.

        If a row with the same ``(symbol, market_code)`` already exists,
        update its mutable fields and return the updated row.  Otherwise
        insert a new row.

        The caller is responsible for generating ``instrument_id`` when
        inserting a new instrument.  On conflict, the existing PK is
        preserved.
        """
        ...

    async def list_active_by_market(
        self, market_code: str
    ) -> Sequence[InstrumentEntity]:
        """List all active instruments for a given market code.

        This is the primary method used by ``UniverseSelectionService``
        to build the Core Universe.  Returns only ``is_active=true``
        instruments, ordered by symbol.
        """
        ...


class DecisionContextRepository(Protocol):
    async def add(self, context: DecisionContextEntity) -> DecisionContextEntity:
        ...

    async def get(self, decision_context_id: UUID) -> DecisionContextEntity | None:
        ...

    async def get_by_correlation_id(self, correlation_id: str) -> DecisionContextEntity | None:
        ...

    async def list(self, query: DecisionContextQuery) -> Sequence[DecisionContextEntity]:
        ...


class PositionSnapshotRepository(Protocol):
    async def add(self, snapshot: PositionSnapshotEntity) -> PositionSnapshotEntity:
        ...

    async def get(self, position_snapshot_id: UUID) -> PositionSnapshotEntity | None:
        ...

    async def list_latest_by_account(self, account_id: UUID) -> Sequence[PositionSnapshotEntity]:
        ...


class CashBalanceSnapshotRepository(Protocol):
    async def add(self, snapshot: CashBalanceSnapshotEntity) -> CashBalanceSnapshotEntity:
        ...

    async def get(self, cash_balance_snapshot_id: UUID) -> CashBalanceSnapshotEntity | None:
        ...

    async def get_latest_by_account(self, account_id: UUID) -> CashBalanceSnapshotEntity | None:
        ...

    async def list_by_account(self, account_id: UUID) -> Sequence[CashBalanceSnapshotEntity]:
        """계좌의 모든 현금 snapshot을 snapshot_at DESC 정렬로 반환합니다.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        Sequence[CashBalanceSnapshotEntity]
            snapshot_at 내림차순 정렬된 snapshot 목록.
            데이터가 없으면 빈 시퀀스.
        """
        ...


class TradeDecisionRepository(Protocol):
    async def add(self, decision: TradeDecisionEntity) -> TradeDecisionEntity:
        ...

    async def get(self, trade_decision_id: UUID) -> TradeDecisionEntity | None:
        ...

    async def get_by_context(self, decision_context_id: UUID) -> TradeDecisionEntity | None:
        ...

    async def list_all(self) -> Sequence[TradeDecisionEntity]:
        ...

class OrderRepository(Protocol):
    async def add(self, order: OrderRequestEntity) -> OrderRequestEntity:
        ...

    async def get(self, order_request_id: UUID) -> OrderRequestEntity | None:
        ...

    async def get_by_client_order_id(self, client_order_id: str) -> OrderRequestEntity | None:
        ...

    async def list(self, query: OrderQuery) -> Sequence[OrderRequestEntity]:
        ...

    async def update_status(
        self,
        order_request_id: UUID,
        status: OrderStatus,
        reason_code: str | None = None,
        reason_message: str | None = None,
        expected_version: int | None = None,
    ) -> None:
        ...


class BrokerOrderRepository(Protocol):
    async def add(self, broker_order: BrokerOrderEntity) -> BrokerOrderEntity:
        ...

    async def get_by_native_order_id(
        self,
        broker_name: str,
        broker_native_order_id: str,
    ) -> BrokerOrderEntity | None:
        ...

    async def list_by_order_request(self, order_request_id: UUID) -> Sequence[BrokerOrderEntity]:
        ...

    async def get(self, broker_order_id: UUID) -> BrokerOrderEntity | None:
        """Get a single broker order by its internal UUID.

        Parameters
        ----------
        broker_order_id:
            The internal ``BrokerOrderEntity.broker_order_id``.

        Returns
        -------
        BrokerOrderEntity | None
            The matching entity, or ``None`` if not found.
        """
        ...

    async def update(
        self,
        broker_order_id: UUID,
        *,
        broker_status: str | None = None,
        last_synced_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        """Update mutable fields on a BrokerOrderEntity.

        Parameters
        ----------
        broker_order_id:
            The UUID of the broker order to update.
        broker_status:
            New broker-side order status (e.g. ``"FILLED"``, ``"CANCELLED"``).
        last_synced_at:
            Timestamp of the last successful sync with the broker.
        updated_at:
            Timestamp of this update.  If not provided, the repository
            may set it to the current time.

        The entity is frozen (immutable), so implementations MUST
        use ``dataclasses.replace()`` internally.
        """
        ...


class FillEventRepository(Protocol):
    async def add(self, fill_event: FillEventEntity) -> FillEventEntity:
        ...

    async def list_by_broker_order(self, broker_order_id: UUID) -> Sequence[FillEventEntity]:
        ...

    async def get_by_broker_fill_id(self, broker_fill_id: str) -> FillEventEntity | None:
        """Look up a fill event by its broker-native fill identifier.

        ``broker_fill_id`` is unique per ``(broker_order_id, broker_fill_id)``
        (DB constraint ``uq_fill_events_native``).  Since the same
        ``broker_fill_id`` could theoretically appear under a different
        ``broker_order_id``, callers should verify the ``broker_order_id``
        match after retrieval.
        """
        ...


class ReconciliationRepository(Protocol):
    """Store for reconciliation runs and mismatch tracking."""

    async def add_run(self, run: ReconciliationRunEntity) -> ReconciliationRunEntity:
        ...

    async def get_run(self, reconciliation_run_id: UUID) -> ReconciliationRunEntity | None:
        ...

    async def attach_order_mismatch(
        self,
        reconciliation_run_id: UUID,
        order_request_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        ...

    async def attach_position_mismatch(
        self,
        reconciliation_run_id: UUID,
        position_snapshot_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        ...

    # -- Milestone 6 extensions --
    async def list_runs_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        ...

    async def get_active_run(
        self, account_id: UUID
    ) -> ReconciliationRunEntity | None:
        """Return the most recent reconciliation run that is still in progress."""
        ...

    async def update_run_status(
        self,
        reconciliation_run_id: UUID,
        status: str,
        completed_at: datetime | None = None,
        summary_json: dict[str, object] | None = None,
    ) -> None:
        ...

    # -- Plan 44: Lock inspection --
    async def list_locks(
        self, account_id: UUID
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks for an account.

        Active means ``expires_at > NOW()`` (physical DELETE, no soft-delete
        column exists yet). If ``resolved_at`` / ``deleted_at`` columns are
        added later, they should be included in the filter.
        """
        ...

    # -- Plan 64: Aggregate (all-account) queries for Dashboard --
    async def list_all_runs(
        self, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs across all accounts, newest first."""
        ...

    async def list_all_active_locks(
        self,
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks across all accounts."""
        ...

    # -- Worker read path (Reconciliation Worker) --

    async def list_pending_runs(
        self,
        limit: int = 20,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs with ``status = 'started'``.

        Parameters
        ----------
        limit : int
            Maximum number of runs to return (default ``20``).
        account_id : UUID | None
            Optional filter by account.
        run_id : UUID | None
            Optional filter by specific run ID.

        Returns
        -------
        Sequence[ReconciliationRunEntity]
            Runs ordered by ``started_at`` ASC (FIFO).
        """
        ...

    async def get_run_order_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationOrderLinkEntity]:
        """Return order links attached to a reconciliation run.

        Parameters
        ----------
        reconciliation_run_id : UUID
            The reconciliation run to look up.

        Returns
        -------
        Sequence[ReconciliationOrderLinkEntity]
            Links ordered by ``created_at`` ASC.
        """
        ...

    async def list_run_position_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationPositionLinkEntity]:
        """Return position links attached to a reconciliation run.

        (Interface only — not yet used by the worker.)
        """
        ...

    # -- Legacy run cleanup --

    async def list_legacy_runs(
        self,
        limit: int = 50,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return legacy runs: ``status = 'started'`` AND no order links.

        Parameters
        ----------
        limit : int
            Maximum number of runs to return (default ``50``).
        account_id : UUID | None
            Optional filter by account.
        run_id : UUID | None
            Optional filter by specific run ID.

        Returns
        -------
        Sequence[ReconciliationRunEntity]
            Runs ordered by ``started_at`` ASC (oldest first).
        """
        ...


class AuditLogRepository(Protocol):
    async def add(self, audit_log: AuditLogEntity) -> AuditLogEntity:
        ...

    async def list_by_correlation_id(self, correlation_id: str) -> Sequence[AuditLogEntity]:
        ...


class OrderStateEventRepository(Protocol):
    """Append-only store for order status transition events."""

    async def add(self, event: OrderStateEventEntity) -> OrderStateEventEntity:
        ...

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[OrderStateEventEntity]:
        ...

    async def list_recent(
        self, limit: int = 100
    ) -> Sequence[OrderStateEventEntity]:
        ...


class GuardrailEvaluationRepository(Protocol):
    """Store for guardrail rule evaluation results."""

    async def add(self, evaluation: GuardrailEvaluationEntity) -> GuardrailEvaluationEntity:
        ...

    async def get(
        self, guardrail_evaluation_id: UUID
    ) -> GuardrailEvaluationEntity | None:
        """Get a single guardrail evaluation by its UUID."""
        ...

    async def get_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
        ...

    async def get_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
        ...

    async def list_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[GuardrailEvaluationEntity]:
        """List guardrail evaluations for an account (via decision_context join)."""
        ...


class RiskLimitSnapshotRepository(Protocol):
    """Store for point-in-time risk limit snapshots."""

    async def add(self, snapshot: RiskLimitSnapshotEntity) -> RiskLimitSnapshotEntity:
        ...

    async def get_latest_by_account(
        self, account_id: UUID
    ) -> RiskLimitSnapshotEntity | None:
        ...

    async def list_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[RiskLimitSnapshotEntity]:
        ...


class ExternalEventRepository(Protocol):
    """Store for normalised external event data.

    This is a **foundation** protocol for Milestone 7. Actual polling
    workers and source adapters are deferred to a later milestone.

    Listed-event filtering (P0):
    By default, ``list_by_symbol`` and ``list_by_type`` return only
    **listed-entity events** (OpenDART corp_cls in Y/K/N). Non-listed
    (corp_cls=E) events are excluded from operational read paths.

    Pass ``include_non_listed=True`` to bypass this filter when
    administrative inspection is needed.
    """

    async def add(self, event: ExternalEventEntity) -> ExternalEventEntity:
        ...

    async def get(self, event_id: UUID) -> ExternalEventEntity | None:
        ...

    async def find_by_dedup_key(self, dedup_key_hash: str) -> ExternalEventEntity | None:
        ...

    async def list_by_symbol(
        self,
        symbol: str,
        since: datetime,
        include_non_listed: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        ...

    async def list_by_type(
        self,
        event_type: str,
        since: datetime,
        include_non_listed: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        ...


class SnapshotSyncRunRepository(Protocol):
    """Store for KIS snapshot sync execution history.

    Append-only: each sync run (manual or scheduler) creates one record.
    This is a run-level summary, not individual position/cash rows.
    """

    async def add(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
        """Persist a new sync run record and return it with server defaults."""
        ...

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[SnapshotSyncRunEntity]:
        """List sync runs, newest first.

        Parameters
        ----------
        limit:
            Maximum number of records to return (default ``50``).
        trigger_type:
            Optional filter by ``"manual"`` or ``"scheduler"``.
        status:
            Optional filter by ``"completed"``, ``"partial"``, or ``"failed"``.

        Returns
        -------
        Sequence[SnapshotSyncRunEntity]
            Runs ordered by ``started_at`` descending.
        """
        ...

    async def get(self, run_id: UUID) -> SnapshotSyncRunEntity | None:
        """Get a single sync run by its UUID.

        Parameters
        ----------
        run_id:
            The snapshot sync run's unique identifier.

        Returns
        -------
        SnapshotSyncRunEntity | None
            The matching run, or ``None`` if not found.
        """

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 900,
    ) -> SnapshotSyncHealthSummary:
        """Compute a freshness/staleness summary for snapshot sync runs.

        Parameters
        ----------
        stale_threshold_seconds:
            Seconds after which a sync is considered stale (default ``900``).

        Returns
        -------
        SnapshotSyncHealthSummary
            Aggregate health indicators (never ``None`` — even for empty data).
        """
        ...


class AgentRunRepository(Protocol):
    """Store for AI Agent execution run records."""

    async def add(self, run: AgentRunEntity) -> AgentRunEntity:
        """Persist a new agent run and return it with server defaults."""
        ...

    async def get(self, agent_run_id: UUID) -> AgentRunEntity | None:
        """Get a single agent run by its UUID."""
        ...

    async def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[AgentRunEntity]:
        """Return all runs for a decision context, ordered by started_at DESC."""
        ...

    async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
        """Return recent runs ordered by started_at DESC."""
        ...


class MarketSessionRepository(Protocol):
    """Store for market session state and phase change events.

    ``market_sessions`` 테이블은 ``run_date`` 기준으로 1행이며,
    P2 scheduler가 주기적으로 upsert (INSERT … ON CONFLICT) 한다.
    """

    async def upsert(self, session: MarketSessionEntity) -> MarketSessionEntity:
        """Upsert a market session by ``run_date``.

        ``INSERT … ON CONFLICT (run_date) DO UPDATE`` semantics.
        Returns the entity with server-generated defaults (id, created_at, etc.).
        """
        ...

    async def get_by_run_date(self, run_date: date) -> MarketSessionEntity | None:
        """Get the session state for a specific run date."""
        ...

    async def list_recent(self, limit: int = 10) -> Sequence[MarketSessionEntity]:
        """Return recent sessions ordered by ``run_date DESC``."""
        ...

    async def add_event(self, event: SessionEventEntity) -> SessionEventEntity:
        """Append a phase-change event to the session_events log."""
        ...

    async def get_events(
        self, market_session_id: int, limit: int = 50
    ) -> Sequence[SessionEventEntity]:
        """Return events for a session, ordered by ``occurred_at DESC``."""
        ...

