from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.domain.entities import (
    AccountEntity,
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
    OrderRequestEntity,
    OrderStateEventEntity,
    PositionSnapshotEntity,
    ReconciliationRunEntity,
    RiskLimitSnapshotEntity,
    StrategyEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import Environment, OrderStatus
from agent_trading.repositories.filters import AccountLookup, DecisionContextQuery, OrderQuery
from agent_trading.repositories.postgres.orders import VersionConflictError


class InMemoryUnitOfWork:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class InMemoryClientRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, ClientEntity] = {}

    async def add(self, client: ClientEntity) -> ClientEntity:
        self._items[client.client_id] = client
        return client

    async def get(self, client_id: UUID) -> ClientEntity | None:
        return self._items.get(client_id)

    async def get_by_code(self, client_code: str) -> ClientEntity | None:
        return next((item for item in self._items.values() if item.client_code == client_code), None)


class InMemoryAccountRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, AccountEntity] = {}

    async def add(self, account: AccountEntity) -> AccountEntity:
        self._items[account.account_id] = account
        return account

    async def get(self, account_id: UUID) -> AccountEntity | None:
        return self._items.get(account_id)

    async def find_one(self, lookup: AccountLookup) -> AccountEntity | None:
        for item in self._items.values():
            if lookup.account_id is not None and item.account_id != lookup.account_id:
                continue
            if lookup.client_id is not None and item.client_id != lookup.client_id:
                continue
            if lookup.account_alias is not None and item.account_alias != lookup.account_alias:
                continue
            if lookup.environment is not None and item.environment != lookup.environment:
                continue
            return item
        return None

    async def list_by_client(self, client_id: UUID) -> Sequence[AccountEntity]:
        return tuple(item for item in self._items.values() if item.client_id == client_id)


class InMemoryStrategyRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, StrategyEntity] = {}

    async def add(self, strategy: StrategyEntity) -> StrategyEntity:
        self._items[strategy.strategy_id] = strategy
        return strategy

    async def get(self, strategy_id: UUID) -> StrategyEntity | None:
        return self._items.get(strategy_id)

    async def get_by_code(self, client_id: UUID, strategy_code: str) -> StrategyEntity | None:
        return next(
            (
                item
                for item in self._items.values()
                if item.client_id == client_id and item.strategy_code == strategy_code
            ),
            None,
        )


class InMemoryConfigVersionRepository:
    """In-memory implementation of ``ConfigVersionRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.
    """

    def __init__(self) -> None:
        self._items: dict[UUID, ConfigVersionEntity] = {}

    async def add(self, config_version: ConfigVersionEntity) -> ConfigVersionEntity:
        self._items[config_version.config_version_id] = config_version
        return config_version

    async def get(self, config_version_id: UUID) -> ConfigVersionEntity | None:
        return self._items.get(config_version_id)

    async def get_active(
        self, client_id: UUID, environment: Environment
    ) -> ConfigVersionEntity | None:
        candidates = [
            item
            for item in self._items.values()
            if item.client_id == client_id and item.environment == environment
        ]
        if not candidates:
            return None
        # Sort by activated_at DESC NULLS LAST (versions without activation last)
        candidates.sort(
            key=lambda x: (x.activated_at is None, x.activated_at or ""),
            reverse=True,
        )
        return candidates[0] if candidates else None

    async def get_active_at(
        self, client_id: UUID, environment: Environment, at: datetime
    ) -> ConfigVersionEntity | None:
        """Return the config version active at the given timestamp."""
        candidates = [
            item
            for item in self._items.values()
            if item.client_id == client_id
            and item.environment == environment
            and item.activated_at is not None
            and item.activated_at <= at
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.activated_at, reverse=True)  # type: ignore[arg-type]
        return candidates[0]


class InMemoryInstrumentRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, InstrumentEntity] = {}

    async def add(self, instrument: InstrumentEntity) -> InstrumentEntity:
        self._items[instrument.instrument_id] = instrument
        return instrument

    async def get(self, instrument_id: UUID) -> InstrumentEntity | None:
        return self._items.get(instrument_id)

    async def get_by_symbol(self, symbol: str, market_code: str) -> InstrumentEntity | None:
        return next(
            (
                item
                for item in self._items.values()
                if item.symbol == symbol and item.market_code == market_code
            ),
            None,
        )


class InMemoryDecisionContextRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, DecisionContextEntity] = {}

    async def add(self, context: DecisionContextEntity) -> DecisionContextEntity:
        self._items[context.decision_context_id] = context
        return context

    async def get(self, decision_context_id: UUID) -> DecisionContextEntity | None:
        return self._items.get(decision_context_id)

    async def get_by_correlation_id(self, correlation_id: str) -> DecisionContextEntity | None:
        return next((item for item in self._items.values() if item.correlation_id == correlation_id), None)

    async def list(self, query: DecisionContextQuery) -> Sequence[DecisionContextEntity]:
        results: list[DecisionContextEntity] = []
        for item in self._items.values():
            if query.account_id is not None and item.account_id != query.account_id:
                continue
            if query.strategy_id is not None and item.strategy_id != query.strategy_id:
                continue
            if query.correlation_id is not None and item.correlation_id != query.correlation_id:
                continue
            if query.market_timestamp_from is not None and item.market_timestamp < query.market_timestamp_from:
                continue
            if query.market_timestamp_to is not None and item.market_timestamp > query.market_timestamp_to:
                continue
            results.append(item)
        results.sort(key=lambda item: item.market_timestamp, reverse=True)
        return tuple(results[: query.limit])


class InMemoryPositionSnapshotRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, PositionSnapshotEntity] = {}

    async def add(self, snapshot: PositionSnapshotEntity) -> PositionSnapshotEntity:
        self._items[snapshot.position_snapshot_id] = snapshot
        return snapshot

    async def get(self, position_snapshot_id: UUID) -> PositionSnapshotEntity | None:
        return self._items.get(position_snapshot_id)

    async def list_latest_by_account(self, account_id: UUID) -> Sequence[PositionSnapshotEntity]:
        results = [item for item in self._items.values() if item.account_id == account_id]
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return tuple(results)


class InMemoryCashBalanceSnapshotRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, CashBalanceSnapshotEntity] = {}

    async def add(self, snapshot: CashBalanceSnapshotEntity) -> CashBalanceSnapshotEntity:
        self._items[snapshot.cash_balance_snapshot_id] = snapshot
        return snapshot

    async def get(self, cash_balance_snapshot_id: UUID) -> CashBalanceSnapshotEntity | None:
        return self._items.get(cash_balance_snapshot_id)

    async def get_latest_by_account(self, account_id: UUID) -> CashBalanceSnapshotEntity | None:
        results = [item for item in self._items.values() if item.account_id == account_id]
        if not results:
            return None
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return results[0]


class InMemoryTradeDecisionRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, TradeDecisionEntity] = {}

    async def add(self, decision: TradeDecisionEntity) -> TradeDecisionEntity:
        self._items[decision.trade_decision_id] = decision
        return decision

    async def get_by_context(self, decision_context_id: UUID) -> TradeDecisionEntity | None:
        return next(
            (item for item in self._items.values() if item.decision_context_id == decision_context_id),
            None,
        )

    async def list_all(self) -> Sequence[TradeDecisionEntity]:
        return tuple(self._items.values())

class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, OrderRequestEntity] = {}

    async def add(self, order: OrderRequestEntity) -> OrderRequestEntity:
        self._items[order.order_request_id] = order
        return order

    async def get(self, order_request_id: UUID) -> OrderRequestEntity | None:
        return self._items.get(order_request_id)

    async def get_by_client_order_id(self, client_order_id: str) -> OrderRequestEntity | None:
        return next((item for item in self._items.values() if item.client_order_id == client_order_id), None)

    async def list(self, query: OrderQuery) -> Sequence[OrderRequestEntity]:
        results: list[OrderRequestEntity] = []
        for item in self._items.values():
            if query.account_id is not None and item.account_id != query.account_id:
                continue
            if query.client_order_id is not None and item.client_order_id != query.client_order_id:
                continue
            if query.correlation_id is not None and item.correlation_id != query.correlation_id:
                continue
            if query.status is not None and item.status != query.status:
                continue
            if query.submitted_from is not None and (
                item.submitted_at is None or item.submitted_at < query.submitted_from
            ):
                continue
            if query.submitted_to is not None and (
                item.submitted_at is None or item.submitted_at > query.submitted_to
            ):
                continue
            results.append(item)
        results.sort(key=lambda item: item.created_at or item.submitted_at, reverse=True)
        return tuple(results[: query.limit])

    async def update_status(
        self,
        order_request_id: UUID,
        status: OrderStatus,
        reason_code: str | None = None,
        reason_message: str | None = None,
        expected_version: int | None = None,
    ) -> None:
        current = self._items[order_request_id]
        if expected_version is not None and current.version != expected_version:
            raise VersionConflictError(
                order_request_id=order_request_id,
                expected_version=expected_version,
                actual_version=current.version,
            )
        self._items[order_request_id] = replace(
            current,
            status=status,
            status_reason_code=reason_code,
            status_reason_message=reason_message,
            version=current.version + 1 if expected_version is not None else current.version,
        )


class InMemoryBrokerOrderRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, BrokerOrderEntity] = {}

    async def add(self, broker_order: BrokerOrderEntity) -> BrokerOrderEntity:
        self._items[broker_order.broker_order_id] = broker_order
        return broker_order

    async def get_by_native_order_id(
        self,
        broker_name: str,
        broker_native_order_id: str,
    ) -> BrokerOrderEntity | None:
        return next(
            (
                item
                for item in self._items.values()
                if item.broker_name == broker_name and item.broker_native_order_id == broker_native_order_id
            ),
            None,
        )

    async def list_by_order_request(self, order_request_id: UUID) -> Sequence[BrokerOrderEntity]:
        return tuple(item for item in self._items.values() if item.order_request_id == order_request_id)


class InMemoryFillEventRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, FillEventEntity] = {}

    async def add(self, fill_event: FillEventEntity) -> FillEventEntity:
        self._items[fill_event.fill_event_id] = fill_event
        return fill_event

    async def list_by_broker_order(self, broker_order_id: UUID) -> Sequence[FillEventEntity]:
        results = [item for item in self._items.values() if item.broker_order_id == broker_order_id]
        results.sort(key=lambda item: item.fill_timestamp)
        return tuple(results)


class InMemoryReconciliationRepository:
    def __init__(self) -> None:
        self._runs: dict[UUID, ReconciliationRunEntity] = {}
        self._order_links: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        self._position_links: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        # In-memory blocking lock store for test support.
        # Key: (account_id, strategy_id, symbol, side)
        # Value: dict with lock metadata
        self._blocking_locks: dict[tuple, dict[str, object]] = {}

    async def add_run(self, run: ReconciliationRunEntity) -> ReconciliationRunEntity:
        self._runs[run.reconciliation_run_id] = run
        return run

    async def get_run(self, reconciliation_run_id: UUID) -> ReconciliationRunEntity | None:
        return self._runs.get(reconciliation_run_id)

    async def attach_order_mismatch(
        self,
        reconciliation_run_id: UUID,
        order_request_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        self._order_links[reconciliation_run_id].append(
            {
                "order_request_id": order_request_id,
                "mismatch_type": mismatch_type,
                "details": details,
            }
        )

    async def attach_position_mismatch(
        self,
        reconciliation_run_id: UUID,
        position_snapshot_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        self._position_links[reconciliation_run_id].append(
            {
                "position_snapshot_id": position_snapshot_id,
                "mismatch_type": mismatch_type,
                "details": details,
            }
        )

    # -- Milestone 6 extensions --

    async def list_runs_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        candidates = [
            run for run in self._runs.values() if run.account_id == account_id
        ]
        candidates.sort(key=lambda x: x.started_at, reverse=True)
        return candidates[:limit]

    async def get_active_run(
        self, account_id: UUID
    ) -> ReconciliationRunEntity | None:
        candidates = [
            run
            for run in self._runs.values()
            if run.account_id == account_id and run.status == "started"
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.started_at, reverse=True)
        return candidates[0]

    async def update_run_status(
        self,
        reconciliation_run_id: UUID,
        status: str,
        summary_json: dict[str, object] | None = None,
    ) -> None:
        run = self._runs.get(reconciliation_run_id)
        if run is None:
            return
        # Reconstruct with updated fields (frozen dataclass)
        self._runs[reconciliation_run_id] = ReconciliationRunEntity(
            reconciliation_run_id=run.reconciliation_run_id,
            account_id=run.account_id,
            trigger_type=run.trigger_type,
            status=status,
            started_at=run.started_at,
            mismatch_count=run.mismatch_count,
            summary_json=summary_json or run.summary_json,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )

    # -- Plan 44: Lock inspection (contract method) --

    async def list_locks(
        self, account_id: UUID
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks for an account."""
        now = datetime.now(timezone.utc)
        results: list[BlockingLockEntity] = []
        for key, value in self._blocking_locks.items():
            if key[0] != account_id:
                continue
            expires_at = value.get("expires_at")
            # Skip expired locks (matching Postgres WHERE expires_at > NOW())
            if expires_at and expires_at <= now:
                continue
            results.append(
                BlockingLockEntity(
                    lock_id=value.get("lock_id", UUID(int=0)),
                    account_id=key[0],
                    strategy_id=key[1],
                    symbol=key[2],
                    side=key[3],
                    reason=value.get("reason", "reconciliation"),
                    locked_by_run_id=value.get("locked_by_run_id"),
                    locked_at=value.get("locked_at"),
                    expires_at=expires_at,
                )
            )
        results.sort(key=lambda x: x.locked_at or now, reverse=True)
        return results

    # -- In-memory blocking lock support (for tests) --

    def _lock_key(
        self,
        account_id: UUID,
        strategy_id: UUID | None,
        symbol: str | None,
        side: str | None,
    ) -> tuple:
        return (account_id, strategy_id, symbol, side)

    def acquire_lock(
        self,
        account_id: UUID,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
        reason: str = "reconciliation",
        locked_by_run_id: UUID,
        expires_at: datetime,
    ) -> bool:
        """Insert a blocking lock. Returns True if acquired, False if already exists."""
        key = self._lock_key(account_id, strategy_id, symbol, side)
        if key in self._blocking_locks:
            existing = self._blocking_locks[key]
            # If the existing lock is expired, replace it.
            if existing["expires_at"] <= datetime.now(timezone.utc):
                self._blocking_locks[key] = {
                    "reason": reason,
                    "locked_by_run_id": locked_by_run_id,
                    "expires_at": expires_at,
                }
                return True
            return False
        self._blocking_locks[key] = {
            "reason": reason,
            "locked_by_run_id": locked_by_run_id,
            "expires_at": expires_at,
        }
        return True

    def release_lock(
        self,
        account_id: UUID,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
        locked_by_run_id: UUID | None = None,
    ) -> None:
        """Remove a blocking lock.

        If ``locked_by_run_id`` is provided, only locks created by that
        reconciliation run are released. If all optional scope params are
        omitted (and no ``locked_by_run_id``), release all locks for the
        account.
        """
        if locked_by_run_id is not None:
            # Release only locks created by this specific run.
            keys_to_delete = [
                k
                for k, v in self._blocking_locks.items()
                if k[0] == account_id
                and v.get("locked_by_run_id") == locked_by_run_id
            ]
            for k in keys_to_delete:
                del self._blocking_locks[k]
            return

        if strategy_id is None and symbol is None and side is None:
            # Release all locks for the account.
            keys_to_delete = [
                k for k in self._blocking_locks if k[0] == account_id
            ]
            for k in keys_to_delete:
                del self._blocking_locks[k]
            return

        key = self._lock_key(account_id, strategy_id, symbol, side)
        self._blocking_locks.pop(key, None)

    def is_locked(
        self,
        account_id: UUID,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
    ) -> bool:
        """Check whether a non-expired blocking lock exists."""
        key = self._lock_key(account_id, strategy_id, symbol, side)
        lock = self._blocking_locks.get(key)
        if lock is None:
            return False
        if lock["expires_at"] <= datetime.now(timezone.utc):
            # Expired — clean up and return False.
            del self._blocking_locks[key]
            return False
        return True


class InMemoryBrokerAccountRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, BrokerAccountEntity] = {}

    async def add(self, account: BrokerAccountEntity) -> BrokerAccountEntity:
        self._items[account.broker_account_id] = account
        return account

    async def get(self, broker_account_id: UUID) -> BrokerAccountEntity | None:
        return self._items.get(broker_account_id)

    async def get_by_ref(
        self,
        broker_name: str,
        account_ref: str,
        environment: Environment,
    ) -> BrokerAccountEntity | None:
        for item in self._items.values():
            if item.broker_name == broker_name and item.account_ref == account_ref and item.environment == environment:
                return item
        return None

    async def list_by_broker(self, broker_name: str) -> Sequence[BrokerAccountEntity]:
        return tuple(item for item in self._items.values() if item.broker_name == broker_name)


class InMemoryAuditLogRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, AuditLogEntity] = {}

    async def add(self, audit_log: AuditLogEntity) -> AuditLogEntity:
        self._items[audit_log.audit_log_id] = audit_log
        return audit_log

    async def list_by_correlation_id(self, correlation_id: str) -> Sequence[AuditLogEntity]:
        results = [item for item in self._items.values() if item.correlation_id == correlation_id]
        results.sort(key=lambda item: item.created_at)
        return tuple(results)


class InMemoryOrderStateEventRepository:
    """In-memory implementation of ``OrderStateEventRepository``.

    This is an **append-only** store: only ``add()`` is supported.
    No update or delete operations are exposed.
    """

    def __init__(self) -> None:
        self._items: dict[UUID, OrderStateEventEntity] = {}

    async def add(self, event: OrderStateEventEntity) -> OrderStateEventEntity:
        self._items[event.order_state_event_id] = event
        return event

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[OrderStateEventEntity]:
        results = [
            item for item in self._items.values()
            if item.order_request_id == order_request_id
        ]
        results.sort(key=lambda item: item.event_timestamp)
        return tuple(results)

    async def list_recent(self, limit: int = 100) -> Sequence[OrderStateEventEntity]:
        results = sorted(
            self._items.values(),
            key=lambda item: item.event_timestamp,
            reverse=True,
        )
        return tuple(results[:limit])


class InMemoryGuardrailEvaluationRepository:
    """In-memory implementation of ``GuardrailEvaluationRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, GuardrailEvaluationEntity] = {}

    async def add(self, evaluation: GuardrailEvaluationEntity) -> GuardrailEvaluationEntity:
        self._items[evaluation.guardrail_evaluation_id] = evaluation
        return evaluation

    async def get_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
        return tuple(
            item for item in self._items.values()
            if item.decision_context_id == decision_context_id
        )

    async def get_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
        return tuple(
            item for item in self._items.values()
            if item.order_request_id == order_request_id
        )


class InMemoryRiskLimitSnapshotRepository:
    """In-memory implementation of ``RiskLimitSnapshotRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, RiskLimitSnapshotEntity] = {}

    async def add(self, snapshot: RiskLimitSnapshotEntity) -> RiskLimitSnapshotEntity:
        self._items[snapshot.risk_limit_snapshot_id] = snapshot
        return snapshot

    async def get_latest_by_account(
        self, account_id: UUID
    ) -> RiskLimitSnapshotEntity | None:
        results = [
            item for item in self._items.values()
            if item.account_id == account_id
        ]
        if not results:
            return None
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return results[0]

    async def list_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[RiskLimitSnapshotEntity]:
        results = [
            item for item in self._items.values()
            if item.account_id == account_id
        ]
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return tuple(results[:limit])


class InMemoryExternalEventRepository:
    """In-memory implementation of ``ExternalEventRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, ExternalEventEntity] = {}

    async def add(self, event: ExternalEventEntity) -> ExternalEventEntity:
        self._items[event.event_id] = event
        return event

    async def get(self, event_id: UUID) -> ExternalEventEntity | None:
        return self._items.get(event_id)

    async def find_by_dedup_key(self, dedup_key_hash: str) -> ExternalEventEntity | None:
        for item in self._items.values():
            if item.dedup_key_hash == dedup_key_hash:
                return item
        return None

    async def list_by_symbol(
        self, symbol: str, since: datetime
    ) -> Sequence[ExternalEventEntity]:
        results = [
            item for item in self._items.values()
            if item.symbol == symbol and item.published_at >= since
        ]
        results.sort(key=lambda item: item.published_at, reverse=True)
        return tuple(results)

    async def list_by_type(
        self, event_type: str, since: datetime
    ) -> Sequence[ExternalEventEntity]:
        results = [
            item for item in self._items.values()
            if item.event_type == event_type and item.published_at >= since
        ]
        results.sort(key=lambda item: item.published_at, reverse=True)
        return tuple(results)
