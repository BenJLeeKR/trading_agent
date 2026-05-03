from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from agent_trading.domain.entities import (
    AccountEntity,
    AuditLogEntity,
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


class ClientRepository(Protocol):
    async def add(self, client: ClientEntity) -> ClientEntity:
        ...

    async def get(self, client_id: UUID) -> ClientEntity | None:
        ...

    async def get_by_code(self, client_code: str) -> ClientEntity | None:
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


class AccountRepository(Protocol):
    async def add(self, account: AccountEntity) -> AccountEntity:
        ...

    async def get(self, account_id: UUID) -> AccountEntity | None:
        ...

    async def find_one(self, lookup: AccountLookup) -> AccountEntity | None:
        ...

    async def list_by_client(self, client_id: UUID) -> Sequence[AccountEntity]:
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

    async def list_latest_by_account(self, account_id: UUID) -> Sequence[PositionSnapshotEntity]:
        ...


class CashBalanceSnapshotRepository(Protocol):
    async def add(self, snapshot: CashBalanceSnapshotEntity) -> CashBalanceSnapshotEntity:
        ...

    async def get_latest_by_account(self, account_id: UUID) -> CashBalanceSnapshotEntity | None:
        ...


class TradeDecisionRepository(Protocol):
    async def add(self, decision: TradeDecisionEntity) -> TradeDecisionEntity:
        ...

    async def get_by_context(self, decision_context_id: UUID) -> TradeDecisionEntity | None:
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


class FillEventRepository(Protocol):
    async def add(self, fill_event: FillEventEntity) -> FillEventEntity:
        ...

    async def list_by_broker_order(self, broker_order_id: UUID) -> Sequence[FillEventEntity]:
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
        summary_json: dict[str, object] | None = None,
    ) -> None:
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

    async def get_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
        ...

    async def get_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
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
    """

    async def add(self, event: ExternalEventEntity) -> ExternalEventEntity:
        ...

    async def get(self, event_id: UUID) -> ExternalEventEntity | None:
        ...

    async def find_by_dedup_key(self, dedup_key_hash: str) -> ExternalEventEntity | None:
        ...

    async def list_by_symbol(
        self, symbol: str, since: datetime
    ) -> Sequence[ExternalEventEntity]:
        ...

    async def list_by_type(
        self, event_type: str, since: datetime
    ) -> Sequence[ExternalEventEntity]:
        ...
