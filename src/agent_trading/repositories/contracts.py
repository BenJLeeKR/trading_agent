from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from agent_trading.domain.entities import (
    AccountEntity,
    AgentRunEntity,
    AuditLogEntity,
    BlockingLockEntity,
    BrokerAccountEntity,
    BrokerFillSnapshotEntity,
    BrokerOrderEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExecutionAttemptEntity,
    ExternalEventEntity,
    FillEventEntity,
    FillSyncRunEntity,
    GuardrailEvaluationEntity,
    InstrumentEntity,
    InstrumentIndexMembershipEntity,
    InstrumentStatusSnapshotEntity,
    MarketSessionEntity,
    OrderRequestEntity,
    OrderSubmissionAttemptEntity,
    OrderStateEventEntity,
    PositionSnapshotEntity,
    ReconciliationOrderLinkEntity,
    ReconciliationPositionLinkEntity,
    ReconciliationRunEntity,
    RiskLimitSnapshotEntity,
    SignalFeatureSnapshotEntity,
    SignalFeatureBatchRunEntity,
    SignalFeatureBatchRunItemEntity,
    SessionEventEntity,
    SnapshotSyncRunEntity,
    StrategyEntity,
    SymbolTradeStateEntity,
    TradeDecisionEntity,
    UniverseFreezeRunEntity,
    UniverseFreezeRunItemEntity,
)
from agent_trading.domain.entities import ExecutionAttemptEntity
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


@dataclass(slots=True, frozen=True)
class FillSyncHealthSummary:
    """Freshness/health summary for the most recent fill sync runs."""

    last_run_started_at: datetime | None
    last_run_completed_at: datetime | None
    last_status: str | None
    last_successful_run_at: datetime | None
    consecutive_failures: int
    is_stale: bool
    stale_threshold_seconds: int
    retried_accounts: int = 0
    retried_days: int = 0
    total_retries: int = 0


@dataclass(slots=True, frozen=True)
class TradeDecisionRow:
    """TradeDecisionEntity + resolved fields from LEFT JOINs.

    ``entity`` contains the full ``TradeDecisionEntity``.
    ``order_request_id`` / ``order_status`` are resolved via
    ``LEFT JOIN trading.order_requests``.
    ``instrument_name`` is resolved via ``LEFT JOIN trading.instruments``.
    ``phase_trace`` is the raw JSONB column from ``execution_attempts``
    (resolved via ``LEFT JOIN LATERAL`` at the row level).
    """

    entity: TradeDecisionEntity
    order_request_id: str | None = None
    order_status: str | None = None
    instrument_name: str | None = None
    phase_trace: list[dict[str, object]] | None = None
    """Raw phase_trace JSONB from ``execution_attempts``
    (resolved via ``LEFT JOIN LATERAL`` in ``list_all_paginated()``).
    """

    execution_attempt_status: str | None = None
    """Status of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_execution_attempt_id: str | None = None
    """ID of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_stop_phase: str | None = None
    """Stop phase of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_stop_reason: str | None = None
    """Stop reason of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_completed_at: datetime | None = None
    """Completed-at timestamp of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_phase_count: int | None = None
    """Number of phases in the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` (``jsonb_array_length(ea.phase_trace)``).

    ``None`` when no execution attempt exists yet.
    """
    signal_feature_snapshot_id: str | None = None
    """Point-in-time decision_context anchor to ``signal_feature_snapshots``."""


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

    async def get_by_symbols_any_market(
        self, symbols: Sequence[str]
    ) -> dict[str, InstrumentEntity]:
        """Batch variant of ``get_by_symbol_any_market`` — one query for many
        symbols instead of one query per symbol (avoids N+1 when resolving a
        seed-symbol list, e.g. market-overlay seed pool resolution)."""
        ...

    async def get_many(
        self, instrument_ids: Sequence[UUID]
    ) -> dict[UUID, InstrumentEntity]:
        """Batch lookup — avoids N+1 when enriching a list of rows.

        Returns a dict keyed by ``instrument_id``; missing ids are simply
        absent from the result (never raises for unknown ids). Empty input
        returns an empty dict without a query.
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

    async def get_many(
        self, decision_context_ids: Sequence[UUID]
    ) -> dict[UUID, DecisionContextEntity]:
        """Batch lookup — avoids N+1 when enriching a list of trade decisions."""
        ...

    async def get_by_correlation_id(self, correlation_id: str) -> DecisionContextEntity | None:
        ...

    async def list(self, query: DecisionContextQuery) -> Sequence[DecisionContextEntity]:
        ...

    async def attach_signal_feature_snapshot(
        self,
        decision_context_id: UUID,
        signal_feature_snapshot_id: UUID,
    ) -> DecisionContextEntity | None:
        ...

    async def attach_cash_balance_snapshot(
        self,
        decision_context_id: UUID,
        cash_balance_snapshot_id: UUID,
    ) -> DecisionContextEntity | None:
        ...


class PositionSnapshotRepository(Protocol):
    async def add(self, snapshot: PositionSnapshotEntity) -> PositionSnapshotEntity:
        ...

    async def get(self, position_snapshot_id: UUID) -> PositionSnapshotEntity | None:
        ...

    async def list_latest_by_account(self, account_id: UUID) -> Sequence[PositionSnapshotEntity]:
        ...

    async def get_latest_by_account_and_instrument_before(
        self,
        account_id: UUID,
        instrument_id: UUID,
        before: datetime,
    ) -> PositionSnapshotEntity | None:
        """Return the most recent position snapshot for a given account and
        instrument whose ``snapshot_at`` is strictly before ``before``.

        Returns ``None`` if no such snapshot exists.
        """
        ...

    async def get_earliest_by_account_and_instrument_after(
        self,
        account_id: UUID,
        instrument_id: UUID,
        after: datetime,
    ) -> PositionSnapshotEntity | None:
        """Return the earliest position snapshot strictly after ``after``."""
        ...

    async def list_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> Sequence[PositionSnapshotEntity]:
        """Return all position snapshots for an account that were created
        during a specific snapshot sync run.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.
        sync_run_id:
            ``snapshot_sync_run_id`` FK 값.

        Returns
        -------
        Sequence[PositionSnapshotEntity]
            해당 sync run에 속한 position snapshot 목록.
        """
        ...

    async def get_latest_sync_run_id(
        self, account_id: UUID,
    ) -> UUID | None:
        """Return the latest ``snapshot_sync_run_id`` recorded for the
        given account (from any snapshot), or ``None`` if no FK data exists.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        UUID | None
            가장 최신 ``snapshot_sync_run_id``. FK가 전혀 없으면 ``None``.
        """
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

    async def get_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        """Return the cash balance snapshot for an account that was created
        during a specific snapshot sync run.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.
        sync_run_id:
            ``snapshot_sync_run_id`` FK 값.

        Returns
        -------
        CashBalanceSnapshotEntity | None
            해당 sync run에 속한 cash balance snapshot. 없으면 ``None``.
        """
        ...

    async def get_latest_sync_run_id(
        self, account_id: UUID,
    ) -> UUID | None:
        """Return the latest ``snapshot_sync_run_id`` recorded for the
        given account (from any cash snapshot), or ``None`` if no FK data
        exists.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        UUID | None
            가장 최신 ``snapshot_sync_run_id``. FK가 전혀 없으면 ``None``.
        """
        ...


class TradeDecisionRepository(Protocol):
    async def add(self, decision: TradeDecisionEntity) -> TradeDecisionEntity:
        ...

    async def get(self, trade_decision_id: UUID) -> TradeDecisionEntity | None:
        ...

    async def get_by_context(self, decision_context_id: UUID) -> TradeDecisionEntity | None:
        """최신 TD 반환 (ORDER BY created_at DESC, trade_decision_id DESC LIMIT 1).

        동일 decision_context_id에 여러 TD가 존재할 수 있으므로,
        가장 최근에 생성된 TD를 반환합니다.
        Tie-break: created_at DESC, trade_decision_id DESC.
        """
        ...

    async def list_by_context(self, decision_context_id: UUID) -> list[TradeDecisionEntity]:
        """주어진 decision_context에 속한 모든 TD를 최신순으로 반환."""
        ...

    async def list_all(self) -> Sequence[TradeDecisionEntity]:
        ...

    async def list_all_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        decision_context_id: UUID | None = None,
        created_date_kst: date | None = None,
        side: str | None = None,
        source_type: str | None = None,
        decision_type: str | None = None,
        execution_status: str | None = None,
        latest_stop_reason: str | None = None,
        latest_stop_reason_prefix: str | None = None,
        has_order: bool | None = None,
    ) -> tuple[list[TradeDecisionRow], int]:
        """서버사이드 페이지네이션: (items, total_count) 반환.

        각 item은 ``TradeDecisionRow`` (entity + order_request_id + order_status).
        ``instrument_name``은 SQL LEFT JOIN으로 한 번에 resolve (N+1 방지).

        ``decision_context_id``가 주어지면 해당 컨텍스트로 필터링.
        ``limit``: 페이지당 최대 row 수 (기본 50).
        ``offset``: 건너뛸 row 수.
        반환값: (해당 페이지의 TradeDecisionRow 리스트, 조건에 맞는 전체 row 수).
        """
        ...

    async def sync_execution_sizing(
        self,
        trade_decision_id: UUID,
        *,
        quantity: Decimal,
        max_order_value: Decimal | None,
        target_notional: Decimal | None,
        execution_sizing_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        """Execution 단계의 deterministic sizing 결과를 TD에 반영한다."""
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

    async def count(self, query: OrderQuery) -> int:
        ...

    async def count_by_status(self, query: OrderQuery) -> dict[str, int]:
        ...

    async def update_status(
        self,
        order_request_id: UUID,
        status: OrderStatus,
        reason_code: str | None = None,
        reason_message: str | None = None,
        expected_version: int | None = None,
        submitted_at: datetime | None = None,
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


class FillSyncRunRepository(Protocol):
    async def add(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        ...

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[FillSyncRunEntity]:
        ...

    async def get(self, run_id: UUID) -> FillSyncRunEntity | None:
        ...

    async def update_run(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        ...

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 1800,
    ) -> FillSyncHealthSummary:
        ...


class BrokerFillSnapshotRepository(Protocol):
    async def upsert(self, snapshot: BrokerFillSnapshotEntity) -> BrokerFillSnapshotEntity:
        ...

    async def list_recent(
        self,
        *,
        limit: int = 200,
        account_id: UUID | None = None,
        order_date: date | None = None,
        order_request_id: UUID | None = None,
        symbol: str | None = None,
        broker_native_order_id: str | None = None,
    ) -> Sequence[BrokerFillSnapshotEntity]:
        ...

    async def list_recent_by_order_ids(
        self, order_request_ids: Sequence[UUID], *, limit_per_order: int = 20
    ) -> dict[UUID, list[BrokerFillSnapshotEntity]]:
        """Batch fill lookup for multiple orders — avoids N+1 when enriching
        a list of orders with their most recent fills.

        Returns a dict keyed by ``order_request_id``, each value newest-first
        and capped at ``limit_per_order``. Orders with no fills are simply
        absent from the result. Empty input returns an empty dict without a
        query.
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

    # -- EOD orphan cleanup --

    async def get_latest_reconciliation_status_by_order(
        self, order_request_id: object
    ) -> str | None:
        """Return the latest reconciliation run status linked to an order,
        or ``None`` if no reconciliation run is linked.

        Used by EOD orphan cleanup to determine whether a
        ``reconcile_required`` order had a ``failed`` reconciliation run.
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

    # -- Plan: Active/historical run 판별 --

    async def list_all_runs_with_activity(
        self,
        limit: int = 50,
        active_only: bool = True,
        include_historical: bool = False,
    ) -> list[dict[str, Any]]:
        """Reconciliation run 목록을 order activity 정보와 함께 조회.

        각 run에 ``is_active`` 플래그를 포함하여 반환.

        ``active_only=True`` (기본값): ``is_active=true`` 인 run만 반환.
        ``include_historical=True`` 일 때만 ``is_active=false`` 인
        historical failed/partial run 을 결과에 포함한다.

        ``include_historical`` 은 ``active_only`` 보다 우선하지 않는다.
        ``active_only=True`` 이면 ``include_historical`` 과 관계없이 active run 만 반환.
        """
        ...

    async def get_historical_failed_run_count(self) -> int:
        """``is_active=false + status IN ('failed','partial')`` 조건의 run 수 반환."""
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

    async def get_by_decision_contexts(
        self, decision_context_ids: Sequence[UUID]
    ) -> dict[UUID, list[GuardrailEvaluationEntity]]:
        """Batch lookup — avoids N+1 when enriching a list of trade decisions."""
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


class SignalFeatureSnapshotRepository(Protocol):
    """Store for deterministic signal feature snapshots."""

    async def add(
        self, snapshot: SignalFeatureSnapshotEntity,
    ) -> SignalFeatureSnapshotEntity:
        ...

    async def get_latest_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
    ) -> SignalFeatureSnapshotEntity | None:
        ...

    async def list_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
        limit: int = 20,
    ) -> Sequence[SignalFeatureSnapshotEntity]:
        ...


class UniverseFreezeRunRepository(Protocol):
    """Store for frozen trading-universe run metadata."""

    async def add(self, run: UniverseFreezeRunEntity) -> UniverseFreezeRunEntity:
        ...

    async def get(self, run_id: UUID) -> UniverseFreezeRunEntity | None:
        ...

    async def get_latest(
        self,
        business_date: date,
        freeze_purpose: str,
    ) -> UniverseFreezeRunEntity | None:
        ...


class InstrumentIndexMembershipRepository(Protocol):
    """Authoritative time-series store for instrument index memberships."""

    async def sync_current_memberships(
        self,
        instrument_id: UUID,
        membership_codes: Sequence[str],
        *,
        effective_from: date,
        source_tag: str | None = None,
        metadata: dict[str, object] | None = None,
        refresh_existing_metadata: bool = False,
    ) -> Sequence[InstrumentIndexMembershipEntity]:
        ...

    async def list_active_by_instrument(
        self,
        instrument_id: UUID,
    ) -> Sequence[InstrumentIndexMembershipEntity]:
        ...

    async def list_active_by_instruments(
        self,
        instrument_ids: Sequence[UUID],
    ) -> dict[UUID, Sequence[InstrumentIndexMembershipEntity]]:
        """Batch variant of ``list_active_by_instrument`` — one query for many
        instruments instead of one query per instrument (avoids N+1 when
        composing the trading universe over thousands of instruments)."""
        ...

    async def list_active_instrument_ids_by_membership_code(
        self,
        membership_code: str,
    ) -> Sequence[UUID]:
        ...

    async def get_latest_effective_from(self) -> date | None:
        """가장 최근에 반영된 membership 갱신 시각(``effective_from``)을 반환한다.

        UNIV-4: 지수 편입 데이터 staleness 감시용 — 활성(``effective_to IS
        NULL``) row 전체 중 최댓값. 데이터가 전혀 없으면 ``None``."""
        ...


class InstrumentStatusSnapshotRepository(Protocol):
    """종목 상태 snapshot authoritative 저장소."""

    async def add(
        self,
        snapshot: InstrumentStatusSnapshotEntity,
    ) -> InstrumentStatusSnapshotEntity:
        ...

    async def get_latest_by_instrument(
        self,
        instrument_id: UUID,
    ) -> InstrumentStatusSnapshotEntity | None:
        ...

    async def get_latest_by_instrument_before(
        self,
        instrument_id: UUID,
        as_of: datetime,
    ) -> InstrumentStatusSnapshotEntity | None:
        ...

    async def list_latest_by_instrument_ids(
        self,
        instrument_ids: Sequence[UUID],
    ) -> Sequence[InstrumentStatusSnapshotEntity]:
        ...


class SymbolTradeStateRepository(Protocol):
    """Authoritative current state cache for symbol-level trade hysteresis."""

    async def upsert(
        self,
        state: SymbolTradeStateEntity,
    ) -> SymbolTradeStateEntity:
        ...

    async def get_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
    ) -> SymbolTradeStateEntity | None:
        ...

    async def list_by_account(
        self,
        account_id: UUID,
    ) -> Sequence[SymbolTradeStateEntity]:
        ...


class UniverseFreezeRunItemRepository(Protocol):
    """Store for item rows materialised under one freeze run."""

    async def add(self, item: UniverseFreezeRunItemEntity) -> UniverseFreezeRunItemEntity:
        ...

    async def add_many(
        self,
        items: Sequence[UniverseFreezeRunItemEntity],
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        ...

    async def list_by_run(
        self,
        universe_freeze_run_id: UUID,
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        ...


class SignalFeatureBatchRunRepository(Protocol):
    """signal feature 배치 실행 메타데이터 저장소."""

    async def add(self, run: SignalFeatureBatchRunEntity) -> SignalFeatureBatchRunEntity:
        ...

    async def get(self, run_id: UUID) -> SignalFeatureBatchRunEntity | None:
        ...


class SignalFeatureBatchRunItemRepository(Protocol):
    """signal feature 배치 종목별 상태 저장소."""

    async def add(
        self,
        item: SignalFeatureBatchRunItemEntity,
    ) -> SignalFeatureBatchRunItemEntity:
        ...

    async def add_many(
        self,
        items: Sequence[SignalFeatureBatchRunItemEntity],
    ) -> Sequence[SignalFeatureBatchRunItemEntity]:
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

    Seeded-news filtering (P1):
    ``event_type='seeded_news'`` events (T3 reliability tier) are
    excluded from the default listed-event filter because they do not
    carry the ``Y|``/``K|``/``N|`` prefix.  Pass
    ``include_seeded_news=True`` to include them alongside listed
    events — this is the intended mode for EI decision context
    assembly.
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
        include_seeded_news: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        ...

    async def has_fresh_t3_events(
        self,
        symbol: str,
        freshness_seconds: int = 3600,
    ) -> bool:
        """Check if T3 events exist for symbol within freshness window.

        Uses created_at (DB insert time) rather than published_at to determine
        whether a recent T3 fetch already populated events for this symbol.
        This prevents redundant T3 pipeline execution within the freshness window.
        """
        ...

    async def list_by_type(
        self,
        event_type: str,
        since: datetime,
        include_non_listed: bool = False,
        include_seeded_news: bool = False,
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

    async def update_run(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
        """Update an existing sync run record (e.g. from ``running`` → ``completed``).

        Parameters
        ----------
        run:
            The sync run entity with updated fields.  The ``snapshot_sync_run_id``
            is used to identify the row to update.

        Returns
        -------
        SnapshotSyncRunEntity
            The updated record as returned by the database.
        """
        ...

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

    async def list_by_decision_contexts(
        self, decision_context_ids: Sequence[UUID], *, agent_type: str | None = None
    ) -> dict[UUID, list[AgentRunEntity]]:
        """Batch lookup — avoids N+1 when enriching a list of trade decisions.

        Each value is ordered by ``started_at`` DESC, same as the single-id method.
        ``agent_type``: optional server-side filter — callers that only need
        one agent type (e.g. compliance inspection only cares about
        ``"ai_compliance"`` runs) should pass it so rows/columns for
        irrelevant types (and their potentially large ``structured_output_json``)
        aren't fetched at all.
        """
        ...

    async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
        """Return recent runs ordered by started_at DESC."""
        ...


class ExecutionAttemptRepository(Protocol):
    async def add(
        self, attempt: ExecutionAttemptEntity
    ) -> ExecutionAttemptEntity:
        ...

    async def get(
        self, execution_attempt_id: UUID
    ) -> ExecutionAttemptEntity | None:
        ...

    async def update_status(
        self,
        execution_attempt_id: UUID,
        status: str,
        *,
        stop_phase: str | None = None,
        stop_reason: str | None = None,
        phase_trace: list[dict[str, object]] | None = None,
        order_request_id: UUID | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        ...

    async def list_by_trade_decision(
        self, trade_decision_id: UUID
    ) -> Sequence[ExecutionAttemptEntity]:
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


class OrderSubmissionAttemptRepository(Protocol):
    """Repository for ``trading.order_submission_attempts``.

    Records every broker submission attempt (success/rejection/exception)
    so that the submission history is never lost.
    """

    async def add(
        self, attempt: OrderSubmissionAttemptEntity
    ) -> OrderSubmissionAttemptEntity:
        """Insert a new submission attempt.

        Returns the entity with server-generated defaults (attempt_id,
        created_at, etc.).
        """
        ...

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[OrderSubmissionAttemptEntity]:
        """Return all attempts for a given order, ordered by attempt_number ASC."""
        ...

    async def get_failure_summary(self) -> dict[str, Any]:
        """Return aggregated failure counts for the last 1h, 24h, and KST today.

        Returns a dict with keys:
        - last_1h_count, last_24h_count, rejected_count, exception_count,
          total_submissions_24h, failure_rate_pct_24h,
          today_count, rejected_count_today, exception_count_today,
          total_submissions_today, failure_rate_pct_today
        """
        ...

    async def list_recent_failures(
        self,
        limit: int = 10,
        *,
        submitted_from: datetime | None = None,
        submitted_to: datetime | None = None,
    ) -> Sequence[dict[str, Any]]:
        """Return the most recent submission failures (rejected or exception).

        Returns a list of dicts with keys:
        - order_request_id, symbol, side, latest_outcome,
          latest_error_type, latest_raw_code, latest_raw_message,
          last_submitted_at, created_at
        """
        ...
