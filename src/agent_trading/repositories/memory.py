from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

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
from agent_trading.domain.enums import Environment, OrderStatus
from agent_trading.repositories.contracts import (
    FillSyncHealthSummary,
    SnapshotSyncHealthSummary,
    TradeDecisionRow,
)
from agent_trading.repositories.filters import AccountLookup, DecisionContextQuery, OrderQuery

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

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

    async def list_all(self) -> Sequence[ClientEntity]:
        return tuple(self._items.values())


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
            if lookup.broker_account_id is not None and item.broker_account_id != lookup.broker_account_id:
                continue
            return item
        return None

    async def list_by_client(self, client_id: UUID) -> Sequence[AccountEntity]:
        return tuple(
            item for item in self._items.values()
            if item.client_id == client_id
        )

    async def update_metadata(
        self,
        account_id: UUID,
        *,
        account_masked: str | None = None,
    ) -> AccountEntity | None:
        existing = self._items.get(account_id)
        if existing is None:
            return None
        updated = AccountEntity(
            account_id=existing.account_id,
            client_id=existing.client_id,
            broker_account_id=existing.broker_account_id,
            environment=existing.environment,
            account_alias=existing.account_alias,
            account_masked=account_masked if account_masked is not None else existing.account_masked,
            status=existing.status,
            risk_profile=existing.risk_profile,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._items[account_id] = updated
        return updated


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

    async def get_by_symbol_any_market(self, symbol: str) -> InstrumentEntity | None:
        matches = [item for item in self._items.values() if item.symbol == symbol]
        if not matches:
            return None
        matches.sort(
            key=lambda item: (
                0
                if item.exchange_code == "KRX" and item.market_code == "KRX"
                else (
                    1
                    if item.exchange_code == "KRX" and item.is_active
                    else (
                        2
                        if item.exchange_code == "KRX"
                        else (3 if item.is_active else 4)
                    )
                ),
                0 if item.market_segment in {"KOSPI", "KOSDAQ"} else 1,
                -(
                    item.updated_at.timestamp()
                    if item.updated_at is not None
                    else (
                        item.created_at.timestamp()
                        if item.created_at is not None
                        else 0.0
                    )
                ),
            ),
        )
        return matches[0]

    async def upsert_by_symbol(self, instrument: InstrumentEntity) -> InstrumentEntity:
        existing = await self.get_by_symbol(instrument.symbol, instrument.market_code)
        if existing is not None:
            import datetime
            updated = InstrumentEntity(
                instrument_id=existing.instrument_id,
                symbol=instrument.symbol,
                market_code=instrument.market_code,
                asset_class=instrument.asset_class,
                currency=instrument.currency,
                name=instrument.name,
                tick_size=instrument.tick_size,
                lot_size=instrument.lot_size,
                is_active=instrument.is_active,
                exchange_code=instrument.exchange_code,
                market_segment=instrument.market_segment,
                metadata=instrument.metadata,
                created_at=existing.created_at,
                updated_at=datetime.datetime.now(datetime.timezone.utc),
            )
            self._items[existing.instrument_id] = updated
            return updated
        return await self.add(instrument)

    async def list_active_by_market(
        self, market_code: str
    ) -> Sequence[InstrumentEntity]:
        """List all active instruments for a given market code."""
        return [
            item
            for item in self._items.values()
            if item.market_code == market_code and item.is_active and item.symbol != 'E2ESUM'
        ]


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

    async def attach_signal_feature_snapshot(
        self,
        decision_context_id: UUID,
        signal_feature_snapshot_id: UUID,
    ) -> DecisionContextEntity | None:
        existing = self._items.get(decision_context_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            signal_feature_snapshot_id=signal_feature_snapshot_id,
        )
        self._items[decision_context_id] = updated
        return updated

    async def attach_cash_balance_snapshot(
        self,
        decision_context_id: UUID,
        cash_balance_snapshot_id: UUID,
    ) -> DecisionContextEntity | None:
        existing = self._items.get(decision_context_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            cash_balance_snapshot_id=cash_balance_snapshot_id,
        )
        self._items[decision_context_id] = updated
        return updated


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

    async def get_latest_by_account_and_instrument_before(
        self,
        account_id: UUID,
        instrument_id: UUID,
        before: datetime,
    ) -> PositionSnapshotEntity | None:
        candidates = [
            item
            for item in self._items.values()
            if item.account_id == account_id
            and item.instrument_id == instrument_id
            and item.snapshot_at < before
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.snapshot_at, reverse=True)
        return candidates[0]

    async def get_earliest_by_account_and_instrument_after(
        self,
        account_id: UUID,
        instrument_id: UUID,
        after: datetime,
    ) -> PositionSnapshotEntity | None:
        candidates = [
            item
            for item in self._items.values()
            if item.account_id == account_id
            and item.instrument_id == instrument_id
            and item.snapshot_at > after
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.snapshot_at)
        return candidates[0]

    async def list_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> Sequence[PositionSnapshotEntity]:
        results = [
            item
            for item in self._items.values()
            if item.account_id == account_id
            and item.snapshot_sync_run_id == sync_run_id
        ]
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return tuple(results)

    async def get_latest_sync_run_id(
        self, account_id: UUID,
    ) -> UUID | None:
        candidates = [
            item
            for item in self._items.values()
            if item.account_id == account_id
            and item.snapshot_sync_run_id is not None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.snapshot_at, reverse=True)
        return candidates[0].snapshot_sync_run_id


class InMemoryCashBalanceSnapshotRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, CashBalanceSnapshotEntity] = {}

    async def add(self, snapshot: CashBalanceSnapshotEntity) -> CashBalanceSnapshotEntity:
        self._items[snapshot.cash_balance_snapshot_id] = snapshot
        return snapshot

    async def get(self, cash_balance_snapshot_id: UUID) -> CashBalanceSnapshotEntity | None:
        return self._items.get(cash_balance_snapshot_id)

    async def list_by_account(self, account_id: UUID) -> Sequence[CashBalanceSnapshotEntity]:
        results = [
            item for item in self._items.values() if item.account_id == account_id
        ]
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return tuple(results)

    async def get_latest_by_account(self, account_id: UUID) -> CashBalanceSnapshotEntity | None:
        results = [item for item in self._items.values() if item.account_id == account_id]
        if not results:
            return None
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return results[0]

    async def get_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        results = [
            item
            for item in self._items.values()
            if item.account_id == account_id
            and item.snapshot_sync_run_id == sync_run_id
        ]
        if not results:
            return None
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return results[0]

    async def get_latest_sync_run_id(
        self, account_id: UUID,
    ) -> UUID | None:
        candidates = [
            item
            for item in self._items.values()
            if item.account_id == account_id
            and item.snapshot_sync_run_id is not None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.snapshot_at, reverse=True)
        return candidates[0].snapshot_sync_run_id


class InMemoryTradeDecisionRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, TradeDecisionEntity] = {}

    async def add(self, decision: TradeDecisionEntity) -> TradeDecisionEntity:
        self._items[decision.trade_decision_id] = decision
        return decision

    async def get(self, trade_decision_id: UUID) -> TradeDecisionEntity | None:
        return self._items.get(trade_decision_id)

    async def get_by_context(self, decision_context_id: UUID) -> TradeDecisionEntity | None:
        """최신 TD 반환 (created_at DESC, tie-break: trade_decision_id DESC)."""
        matches = [item for item in self._items.values() if item.decision_context_id == decision_context_id]
        if not matches:
            return None
        return max(matches, key=lambda td: (td.created_at, td.trade_decision_id))

    async def list_by_context(self, decision_context_id: UUID) -> list[TradeDecisionEntity]:
        """주어진 decision_context에 속한 모든 TD를 최신순으로 반환."""
        items = [item for item in self._items.values() if item.decision_context_id == decision_context_id]
        return sorted(items, key=lambda td: (td.created_at, td.trade_decision_id), reverse=True)

    async def list_all(self) -> Sequence[TradeDecisionEntity]:
        return tuple(self._items.values())

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
        """In-memory pagination: (items, total_count) 반환.

        각 item은 ``TradeDecisionRow``.
        In-memory 구현에서는 instrument_name과 order 정보를 resolve할 수 없으므로
        ``entity``만 채워서 반환.
        """
        items = list(self._items.values())
        if decision_context_id is not None:
            items = [i for i in items if i.decision_context_id == decision_context_id]
        if created_date_kst is not None:
            kst = timezone(timedelta(hours=9))
            items = [i for i in items if i.created_at.astimezone(kst).date() == created_date_kst]
        if side is not None:
            side_lower = side.lower()
            items = [i for i in items if str(i.side).lower() == side_lower or str(getattr(i.side, "value", "")).lower() == side_lower]
        if source_type is not None:
            source_type_lower = source_type.lower()
            items = [i for i in items if str(i.source_type or "").lower() == source_type_lower]
        if decision_type is not None:
            decision_type_lower = decision_type.lower()
            items = [
                i
                for i in items
                if str(i.decision_type).lower() == decision_type_lower
                or str(getattr(i.decision_type, "value", "")).lower() == decision_type_lower
            ]
        if execution_status is not None:
            normalized_execution_status = execution_status.lower()
            items = [
                i
                for i in items
                if (
                    (
                        str(getattr(i.decision_type, "value", i.decision_type) or "").upper() in {"HOLD", "WATCH"}
                        and normalized_execution_status == "non_trade"
                    )
                    or (
                        str(getattr(i.decision_type, "value", i.decision_type) or "").upper() not in {"HOLD", "WATCH"}
                        and normalized_execution_status == "trade_decision_only"
                    )
                )
            ]
        # 최신순 정렬
        items.sort(key=lambda td: (td.created_at, td.trade_decision_id), reverse=True)
        total_count = len(items)
        paged = items[offset : offset + limit]
        return [TradeDecisionRow(entity=item) for item in paged], total_count

    async def sync_execution_sizing(
        self,
        trade_decision_id: UUID,
        *,
        quantity: Decimal,
        max_order_value: Decimal | None,
        target_notional: Decimal | None,
        execution_sizing_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        existing = self._items.get(trade_decision_id)
        if existing is None:
            return None
        merged_decision_json = dict(existing.decision_json or {})
        merged_decision_json["execution_sizing"] = dict(execution_sizing_payload)
        updated = replace(
            existing,
            quantity=quantity,
            target_quantity=quantity,
            max_order_value=max_order_value,
            target_notional=target_notional,
            decision_json=merged_decision_json,
        )
        self._items[trade_decision_id] = updated
        return updated

class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, OrderRequestEntity] = {}
        # E2E 계정 제외를 위한 account_code 패턴 목록
        # PostgreSQL의 NOT LIKE 'E2E-%' 필터와 동기화
        # account_code 기반 필터링은 account_id → account_code 매핑이 필요하므로,
        # 실제 필터링은 _excluded_account_ids를 통해 account_id 레벨에서 수행됩니다.
        self._excluded_account_code_patterns: list[str] = ['E2E-%']
        self._excluded_account_ids: set[UUID] = set()

    def exclude_account(self, account_id: UUID) -> None:
        """Register an account UUID whose orders should be excluded from list()."""
        self._excluded_account_ids.add(account_id)

    def exclude_account_code(self, pattern: str) -> None:
        """Register an account_code pattern whose orders should be excluded from list()."""
        if pattern not in self._excluded_account_code_patterns:
            self._excluded_account_code_patterns.append(pattern)

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
            # E2E 계정(account_code가 'E2E-%' 패턴)의 주문 제외 (PostgreSQL NOT LIKE 'E2E-%' 필터와 동기화)
            if item.account_id in self._excluded_account_ids:
                continue
            if query.account_id is not None and item.account_id != query.account_id:
                continue
            if query.client_order_id is not None and item.client_order_id != query.client_order_id:
                continue
            if query.correlation_id is not None and item.correlation_id != query.correlation_id:
                continue
            if query.status is not None and item.status != query.status:
                continue
            if query.statuses is not None and item.status not in query.statuses:
                continue
            if query.trade_decision_id is not None and item.trade_decision_id != query.trade_decision_id:
                continue
            if query.decision_context_id is not None and item.decision_context_id != query.decision_context_id:
                continue
            if query.submitted_from is not None and (
                item.submitted_at is None or item.submitted_at < query.submitted_from
            ):
                continue
            if query.submitted_to is not None and (
                item.submitted_at is None or item.submitted_at > query.submitted_to
            ):
                continue
            if query.created_from is not None and (
                item.created_at is None or item.created_at < query.created_from
            ):
                continue
            if query.created_to is not None and (
                item.created_at is None or item.created_at > query.created_to
            ):
                continue
            results.append(item)
        results.sort(key=lambda item: item.created_at or item.submitted_at, reverse=True)
        return tuple(results[: query.limit])

    async def count(self, query: OrderQuery) -> int:
        return len(await self.list(replace(query, limit=10**9)))

    async def count_by_status(self, query: OrderQuery) -> dict[str, int]:
        counts: dict[str, int] = {}
        items = await self.list(replace(query, limit=10**9))
        for item in items:
            key = item.status.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    async def update_status(
        self,
        order_request_id: UUID,
        status: OrderStatus,
        reason_code: str | None = None,
        reason_message: str | None = None,
        expected_version: int | None = None,
        submitted_at: datetime | None = None,
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
            submitted_at=(
                submitted_at
                or (
                    datetime.now(timezone.utc)
                    if status == OrderStatus.SUBMITTED and current.submitted_at is None
                    else current.submitted_at
                )
            ),
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

    async def get(self, broker_order_id: UUID) -> BrokerOrderEntity | None:
        return self._items.get(broker_order_id)

    async def update(
        self,
        broker_order_id: UUID,
        *,
        broker_status: str | None = None,
        last_synced_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        item = self._items.get(broker_order_id)
        if item is None:
            raise ValueError(f"BrokerOrder not found: {broker_order_id}")
        kwargs: dict[str, object] = {}
        if broker_status is not None:
            kwargs["broker_status"] = broker_status
        if last_synced_at is not None:
            kwargs["last_synced_at"] = last_synced_at
        if updated_at is not None:
            kwargs["updated_at"] = updated_at
        self._items[broker_order_id] = replace(item, **kwargs)


class InMemoryFillEventRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, FillEventEntity] = {}
        self._by_fill_id: dict[str, FillEventEntity] = {}

    async def add(self, fill_event: FillEventEntity) -> FillEventEntity:
        self._items[fill_event.fill_event_id] = fill_event
        if fill_event.broker_fill_id:
            self._by_fill_id[fill_event.broker_fill_id] = fill_event
        return fill_event

    async def list_by_broker_order(self, broker_order_id: UUID) -> Sequence[FillEventEntity]:
        results = [item for item in self._items.values() if item.broker_order_id == broker_order_id]
        results.sort(key=lambda item: item.fill_timestamp)
        return tuple(results)

    async def get_by_broker_fill_id(self, broker_fill_id: str) -> FillEventEntity | None:
        return self._by_fill_id.get(broker_fill_id)


class InMemoryBrokerFillSnapshotRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, BrokerFillSnapshotEntity] = {}
        self._by_dedupe_key: dict[str, UUID] = {}

    async def upsert(self, snapshot: BrokerFillSnapshotEntity) -> BrokerFillSnapshotEntity:
        existing_id = self._by_dedupe_key.get(snapshot.dedupe_key)
        if existing_id is not None:
            existing = self._items[existing_id]
            updated = replace(
                existing,
                order_request_id=snapshot.order_request_id,
                fill_sync_run_id=snapshot.fill_sync_run_id,
                broker_fill_id=snapshot.broker_fill_id,
                order_status_code=snapshot.order_status_code,
                cancel_yn=snapshot.cancel_yn,
                ordered_quantity=snapshot.ordered_quantity,
                filled_quantity=snapshot.filled_quantity,
                fill_price=snapshot.fill_price,
                order_time=snapshot.order_time,
                fill_time=snapshot.fill_time,
                fill_timestamp=snapshot.fill_timestamp,
                raw_payload_json=snapshot.raw_payload_json,
                updated_at=snapshot.updated_at,
            )
            self._items[existing_id] = updated
            return updated
        self._items[snapshot.broker_fill_snapshot_id] = snapshot
        self._by_dedupe_key[snapshot.dedupe_key] = snapshot.broker_fill_snapshot_id
        return snapshot

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
        items = list(self._items.values())
        if account_id is not None:
            items = [item for item in items if item.account_id == account_id]
        if order_date is not None:
            items = [item for item in items if item.order_date == order_date]
        if order_request_id is not None:
            items = [item for item in items if item.order_request_id == order_request_id]
        if symbol is not None:
            items = [item for item in items if item.symbol == symbol]
        if broker_native_order_id is not None:
            items = [item for item in items if item.broker_native_order_id == broker_native_order_id]
        items.sort(
            key=lambda item: (
                item.order_date,
                item.fill_timestamp or datetime.min.replace(tzinfo=timezone.utc),
                item.created_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        return tuple(items[:limit])


class InMemoryFillSyncRunRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, FillSyncRunEntity] = {}

    async def add(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        self._items[run.fill_sync_run_id] = run
        return run

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[FillSyncRunEntity]:
        items = list(self._items.values())
        if trigger_type is not None:
            items = [item for item in items if item.trigger_type == trigger_type]
        if status is not None:
            items = [item for item in items if item.status == status]
        items.sort(key=lambda item: item.started_at, reverse=True)
        return tuple(items[:limit])

    async def get(self, run_id: UUID) -> FillSyncRunEntity | None:
        return self._items.get(run_id)

    async def update_run(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        self._items[run.fill_sync_run_id] = run
        return run

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 1800,
    ) -> FillSyncHealthSummary:
        items = sorted(self._items.values(), key=lambda item: item.started_at, reverse=True)
        if not items:
            return FillSyncHealthSummary(
                last_run_started_at=None,
                last_run_completed_at=None,
                last_status=None,
                last_successful_run_at=None,
                consecutive_failures=0,
                is_stale=True,
                stale_threshold_seconds=stale_threshold_seconds,
                retried_accounts=0,
                retried_days=0,
                total_retries=0,
            )

        last = items[0]
        last_successful = next((item for item in items if item.status == "completed"), None)
        consecutive_failures = 0
        for item in items:
            if item.status == "failed":
                consecutive_failures += 1
            else:
                break
        now = datetime.now(timezone.utc)
        last_successful_at = last_successful.started_at if last_successful else None
        is_stale = True
        if last_successful_at is not None:
            is_stale = (now - last_successful_at).total_seconds() > stale_threshold_seconds
        summary_json = last.summary_json or {}
        return FillSyncHealthSummary(
            last_run_started_at=last.started_at,
            last_run_completed_at=last.completed_at,
            last_status=last.status,
            last_successful_run_at=last_successful_at,
            consecutive_failures=consecutive_failures,
            is_stale=is_stale,
            stale_threshold_seconds=stale_threshold_seconds,
            retried_accounts=int(summary_json.get("retried_accounts", 0) or 0),
            retried_days=int(summary_json.get("retried_days", 0) or 0),
            total_retries=int(summary_json.get("total_retries", 0) or 0),
        )


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
        completed_at: datetime | None = None,
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
            summary_json=summary_json if summary_json is not None else run.summary_json,
            completed_at=completed_at if completed_at is not None else run.completed_at,
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

    # -- Plan 64: Aggregate (all-account) queries for Dashboard --

    async def list_all_runs(
        self, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs across all accounts, newest first."""
        candidates = sorted(
            self._runs.values(), key=lambda x: x.started_at, reverse=True
        )
        return candidates[:limit]

    async def list_all_active_locks(
        self,
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks across all accounts."""
        now = datetime.now(timezone.utc)
        results: list[BlockingLockEntity] = []
        for key, value in self._blocking_locks.items():
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

    # -- Worker read path (Reconciliation Worker) --

    async def list_pending_runs(
        self,
        limit: int = 20,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs with ``status = 'started'``."""
        runs = [
            r for r in self._runs.values()
            if r.status == "started"
        ]
        if account_id is not None:
            runs = [r for r in runs if r.account_id == account_id]
        if run_id is not None:
            runs = [r for r in runs if r.reconciliation_run_id == run_id]
        runs.sort(key=lambda r: r.started_at)
        return runs[:limit]

    # -- Legacy run cleanup --

    async def list_legacy_runs(
        self,
        limit: int = 50,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return legacy runs: ``status = 'started'`` AND no order links."""
        runs = [
            r for r in self._runs.values()
            if r.status == "started"
        ]
        # Filter: runs WITH order links excluded
        runs_with_links = {
            link_info["reconciliation_run_id"]
            for links in self._order_links.values()
            for link_info in links
            if isinstance(link_info, dict) and "reconciliation_run_id" in link_info
        }
        # The _order_links dict is keyed by reconciliation_run_id,
        # so any run with entries has links.
        runs = [
            r for r in runs
            if r.reconciliation_run_id not in self._order_links
            or len(self._order_links[r.reconciliation_run_id]) == 0
        ]
        if account_id is not None:
            runs = [r for r in runs if r.account_id == account_id]
        if run_id is not None:
            runs = [r for r in runs if r.reconciliation_run_id == run_id]
        runs.sort(key=lambda r: r.started_at)
        return runs[:limit]

    async def get_latest_reconciliation_status_by_order(
        self, order_request_id: object
    ) -> str | None:
        """Return the latest reconciliation run status linked to an order,
        or ``None`` if no reconciliation run is linked.

        In-memory implementation: iterate order_links to find matching runs.
        """
        # Find run_ids linked to this order_request_id
        matching_run_ids: set[UUID] = set()
        for run_id, links in self._order_links.items():
            for link in links:
                if isinstance(link, dict) and link.get("order_request_id") == order_request_id:
                    matching_run_ids.add(run_id)

        if not matching_run_ids:
            return None

        # Find the latest run among matching run_ids
        latest_run: ReconciliationRunEntity | None = None
        for run_id in matching_run_ids:
            run = self._runs.get(run_id)
            if run is None:
                continue
            if latest_run is None or run.started_at > latest_run.started_at:
                latest_run = run

        return latest_run.status if latest_run is not None else None

    async def get_run_order_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationOrderLinkEntity]:
        """Return order links attached to a reconciliation run."""
        raw_links = self._order_links.get(reconciliation_run_id, [])
        result: list[ReconciliationOrderLinkEntity] = []
        for link in raw_links:
            result.append(
                ReconciliationOrderLinkEntity(
                    reconciliation_run_id=reconciliation_run_id,
                    order_request_id=link["order_request_id"],
                    mismatch_type=link["mismatch_type"],
                    details_json=link.get("details", {}),
                )
            )
        return result

    async def list_run_position_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationPositionLinkEntity]:
        """Return position links attached to a reconciliation run."""
        raw_links = self._position_links.get(reconciliation_run_id, [])
        result: list[ReconciliationPositionLinkEntity] = []
        for link in raw_links:
            result.append(
                ReconciliationPositionLinkEntity(
                    reconciliation_run_id=reconciliation_run_id,
                    position_snapshot_id=link["position_snapshot_id"],
                    mismatch_type=link["mismatch_type"],
                    details_json=link.get("details", {}),
                )
            )
        return result

    # -- Plan: Active/historical run 판별 --

    async def list_all_runs_with_activity(
        self,
        limit: int = 50,
        active_only: bool = True,
        include_historical: bool = False,
    ) -> list[dict[str, Any]]:
        """In-memory 스텁: reconciliation run 목록을 active 여부와 함께 반환.

        ``active_only=True`` (기본값): ``is_active=true`` 인 run만 반환.
        ``include_historical=True`` 일 때만 ``is_active=false`` 인
        historical failed/partial run 을 결과에 포함한다.
        """
        rows: list[dict[str, Any]] = []
        sorted_runs = sorted(
            self._runs.values(), key=lambda r: r.started_at, reverse=True
        )[:limit]
        for run in sorted_runs:
            is_active = run.status == "started" or (
                run.status in ("failed", "partial") and False
            )
            rows.append({
                "reconciliation_run_id": run.reconciliation_run_id,
                "account_id": run.account_id,
                "trigger_type": run.trigger_type,
                "status": run.status,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "mismatch_count": run.mismatch_count,
                "created_at": run.created_at,
                "is_active": is_active,
                "summary_json": None,
            })
        if active_only:
            rows = [r for r in rows if r["is_active"]]
        elif not include_historical:
            # active + completed/started 만 보여주고 historical failed 는 숨김
            rows = [
                r for r in rows
                if r["is_active"]
                or r["status"] in ("started", "completed")
            ]
        return rows

    async def get_historical_failed_run_count(self) -> int:
        """``is_active=false + status IN ('failed','partial')`` 조건의 run 수 반환."""
        count = 0
        for run in self._runs.values():
            if run.status not in ("failed", "partial"):
                continue
            # is_active=false (order link 없음으로 간주)
            count += 1
        return count

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

    async def list_by_broker_and_env(
        self,
        broker_name: str,
        env: Environment,
    ) -> Sequence[BrokerAccountEntity]:
        return tuple(
            item
            for item in self._items.values()
            if item.broker_name == broker_name and item.environment == env
        )

    async def list_by_account_id(
        self,
        account_id: UUID,
    ) -> Sequence[BrokerAccountEntity]:
        """In-memory: return all broker accounts (cross-repo JOIN not available)."""
        # Note: Proper resolution requires AccountRepository access.
        # Production path uses a SQL JOIN (see PostgresBrokerAccountRepository).
        return tuple(self._items.values())


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

    async def get(
        self, guardrail_evaluation_id: UUID
    ) -> GuardrailEvaluationEntity | None:
        """Get a single guardrail evaluation by its UUID."""
        return self._items.get(guardrail_evaluation_id)

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

    async def list_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[GuardrailEvaluationEntity]:
        """List guardrail evaluations for an account (via decision_context join).

        Note: In-memory implementation iterates all items and matches
        via decision_context_id. For production, use the Postgres implementation
        which performs a proper SQL JOIN.
        """
        # Collect decision_context_ids for this account from decision_contexts
        # Since we don't have a direct reference to the decision_context repo,
        # we filter items that have a non-None decision_context_id.
        # The Postgres implementation uses a proper JOIN.
        results = [
            item for item in self._items.values()
            if item.decision_context_id is not None
        ]
        results.sort(key=lambda item: item.evaluated_at, reverse=True)
        return tuple(results[:limit])


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


class InMemorySignalFeatureSnapshotRepository:
    """In-memory implementation of ``SignalFeatureSnapshotRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, SignalFeatureSnapshotEntity] = {}

    async def add(
        self, snapshot: SignalFeatureSnapshotEntity,
    ) -> SignalFeatureSnapshotEntity:
        self._items[snapshot.signal_feature_snapshot_id] = snapshot
        return snapshot

    async def get_latest_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
    ) -> SignalFeatureSnapshotEntity | None:
        results = [
            item for item in self._items.values()
            if item.instrument_id == instrument_id and item.timeframe == timeframe
        ]
        if not results:
            return None
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return results[0]

    async def list_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
        limit: int = 20,
    ) -> Sequence[SignalFeatureSnapshotEntity]:
        results = [
            item for item in self._items.values()
            if item.instrument_id == instrument_id and item.timeframe == timeframe
        ]
        results.sort(key=lambda item: item.snapshot_at, reverse=True)
        return tuple(results[:limit])


class InMemoryUniverseFreezeRunRepository:
    """In-memory implementation of ``UniverseFreezeRunRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, UniverseFreezeRunEntity] = {}

    async def add(self, run: UniverseFreezeRunEntity) -> UniverseFreezeRunEntity:
        self._items[run.universe_freeze_run_id] = run
        return run

    async def get(self, run_id: UUID) -> UniverseFreezeRunEntity | None:
        return self._items.get(run_id)

    async def get_latest(
        self,
        business_date: date,
        freeze_purpose: str,
    ) -> UniverseFreezeRunEntity | None:
        results = [
            item for item in self._items.values()
            if item.business_date == business_date and item.freeze_purpose == freeze_purpose
        ]
        if not results:
            return None
        results.sort(
            key=lambda item: (item.freeze_sequence, item.frozen_at),
            reverse=True,
        )
        return results[0]


class InMemoryInstrumentIndexMembershipRepository:
    """In-memory implementation of ``InstrumentIndexMembershipRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, InstrumentIndexMembershipEntity] = {}

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
        normalized_codes = {
            str(code).strip().upper()
            for code in membership_codes
            if str(code).strip()
        }
        active_items = [
            item
            for item in self._items.values()
            if item.instrument_id == instrument_id and item.effective_to is None
        ]
        for item in active_items:
            if item.membership_code not in normalized_codes:
                self._items[item.instrument_index_membership_id] = replace(
                    item,
                    effective_to=effective_from,
                    updated_at=datetime.now(timezone.utc),
                )
            elif refresh_existing_metadata:
                self._items[item.instrument_index_membership_id] = replace(
                    item,
                    source_tag=source_tag,
                    metadata=dict(metadata or {}),
                    updated_at=datetime.now(timezone.utc),
                )
        existing_active_codes = {
            item.membership_code
            for item in self._items.values()
            if item.instrument_id == instrument_id and item.effective_to is None
        }
        now = datetime.now(timezone.utc)
        for code in sorted(normalized_codes - existing_active_codes):
            entity = InstrumentIndexMembershipEntity(
                instrument_index_membership_id=uuid4(),
                instrument_id=instrument_id,
                membership_code=code,
                effective_from=effective_from,
                effective_to=None,
                source_tag=source_tag,
                metadata=dict(metadata or {}),
                created_at=now,
                updated_at=now,
            )
            self._items[entity.instrument_index_membership_id] = entity
        return await self.list_active_by_instrument(instrument_id)

    async def list_active_by_instrument(
        self,
        instrument_id: UUID,
    ) -> Sequence[InstrumentIndexMembershipEntity]:
        results = [
            item
            for item in self._items.values()
            if item.instrument_id == instrument_id and item.effective_to is None
        ]
        results.sort(key=lambda item: item.membership_code)
        return tuple(results)

    async def list_active_instrument_ids_by_membership_code(
        self,
        membership_code: str,
    ) -> Sequence[UUID]:
        normalized = str(membership_code).strip().upper()
        instrument_ids = {
            item.instrument_id
            for item in self._items.values()
            if item.effective_to is None and item.membership_code == normalized
        }
        return tuple(sorted(instrument_ids, key=str))


class InMemorySymbolTradeStateRepository:
    """In-memory implementation of ``SymbolTradeStateRepository``."""

    def __init__(self) -> None:
        self._items: dict[tuple[UUID, UUID], SymbolTradeStateEntity] = {}

    async def upsert(
        self,
        state: SymbolTradeStateEntity,
    ) -> SymbolTradeStateEntity:
        self._items[(state.account_id, state.instrument_id)] = state
        return state

    async def get_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
    ) -> SymbolTradeStateEntity | None:
        return self._items.get((account_id, instrument_id))


class InMemoryUniverseFreezeRunItemRepository:
    """In-memory implementation of ``UniverseFreezeRunItemRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, UniverseFreezeRunItemEntity] = {}

    async def add(self, item: UniverseFreezeRunItemEntity) -> UniverseFreezeRunItemEntity:
        self._items[item.universe_freeze_run_item_id] = item
        return item

    async def add_many(
        self,
        items: Sequence[UniverseFreezeRunItemEntity],
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        for item in items:
            self._items[item.universe_freeze_run_item_id] = item
        return tuple(items)

    async def list_by_run(
        self,
        universe_freeze_run_id: UUID,
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        results = [
            item for item in self._items.values()
            if item.universe_freeze_run_id == universe_freeze_run_id
        ]
        results.sort(
            key=lambda item: (
                item.rank is None,
                item.rank if item.rank is not None else 0,
                item.symbol,
            )
        )
        return tuple(results)


class InMemorySignalFeatureBatchRunRepository:
    """In-memory implementation of ``SignalFeatureBatchRunRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, SignalFeatureBatchRunEntity] = {}

    async def add(self, run: SignalFeatureBatchRunEntity) -> SignalFeatureBatchRunEntity:
        self._items[run.signal_feature_batch_run_id] = run
        return run

    async def get(self, run_id: UUID) -> SignalFeatureBatchRunEntity | None:
        return self._items.get(run_id)


class InMemorySignalFeatureBatchRunItemRepository:
    """In-memory implementation of ``SignalFeatureBatchRunItemRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, SignalFeatureBatchRunItemEntity] = {}

    async def add(
        self,
        item: SignalFeatureBatchRunItemEntity,
    ) -> SignalFeatureBatchRunItemEntity:
        self._items[item.signal_feature_batch_run_item_id] = item
        return item

    async def add_many(
        self,
        items: Sequence[SignalFeatureBatchRunItemEntity],
    ) -> Sequence[SignalFeatureBatchRunItemEntity]:
        for item in items:
            self._items[item.signal_feature_batch_run_item_id] = item
        return tuple(items)


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

    @staticmethod
    def _is_listed_event(event: ExternalEventEntity) -> bool:
        """Check if an event is from a listed entity (corp_cls in Y/K/N).

        Uses the ``event_type`` prefix convention: ``Y|``, ``K|``, ``N|``
        indicate listed entities; ``E|`` indicates non-listed.
        ``seeded_news`` is a synthetic event type (not from OpenDART) and
        is NOT considered a listed event — it must be explicitly included
        via ``include_seeded_news=True``.
        Events without a corp_cls prefix are considered listed (conservative).
        """
        # seeded_news is never a listed event
        if event.event_type == "seeded_news":
            return False
        for prefix in ("Y|", "K|", "N|"):
            if event.event_type.startswith(prefix):
                return True
        # E| prefix = non-listed; no prefix = unknown → treat as listed
        if event.event_type.startswith("E|"):
            return False
        return True

    @staticmethod
    def _is_seeded_news(event: ExternalEventEntity) -> bool:
        """Check if an event is a seeded news event (T3 reliability tier)."""
        return event.event_type == "seeded_news"

    async def list_by_symbol(
        self,
        symbol: str,
        since: datetime,
        include_non_listed: bool = False,
        include_seeded_news: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        def _include(item: ExternalEventEntity) -> bool:
            if include_non_listed:
                return True
            if self._is_listed_event(item):
                return True
            if include_seeded_news and self._is_seeded_news(item):
                return True
            return False

        results = [
            item for item in self._items.values()
            if item.symbol == symbol
            and item.published_at >= since
            and _include(item)
        ]
        results.sort(key=lambda item: item.published_at, reverse=True)
        return tuple(results)

    async def list_by_type(
        self,
        event_type: str,
        since: datetime,
        include_non_listed: bool = False,
        include_seeded_news: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        def _include(item: ExternalEventEntity) -> bool:
            if include_non_listed:
                return True
            if self._is_listed_event(item):
                return True
            if include_seeded_news and self._is_seeded_news(item):
                return True
            return False

        results = [
            item for item in self._items.values()
            if item.event_type == event_type
            and item.published_at >= since
            and _include(item)
        ]
        results.sort(key=lambda item: item.published_at, reverse=True)
        return tuple(results)

    async def has_fresh_t3_events(
        self,
        symbol: str,
        freshness_seconds: int = 3600,
    ) -> bool:
        """Check if seeded_news events exist for symbol within freshness window.

        Uses ingested_at (system ingestion time) to determine freshness.
        ingested_at reflects when the event was stored in the database,
        which is the correct semantic for "has fresh data been collected".
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=freshness_seconds)
        for e in self._items.values():
            if e.symbol != symbol:
                continue
            if e.source_reliability_tier != "T3":
                continue
            created_or_ingested = e.ingested_at
            if created_or_ingested is not None and created_or_ingested >= cutoff:
                return True
        return False


class InMemorySnapshotSyncRunRepository:
    """In-memory implementation of ``SnapshotSyncRunRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, SnapshotSyncRunEntity] = {}

    async def add(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
        self._items[run.snapshot_sync_run_id] = run
        return run

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[SnapshotSyncRunEntity]:
        """List sync runs, newest first. Optional filter by trigger_type or status."""
        items = list(self._items.values())
        if trigger_type is not None:
            items = [i for i in items if i.trigger_type == trigger_type]
        if status is not None:
            items = [i for i in items if i.status == status]
        items.sort(key=lambda e: e.started_at, reverse=True)
        return tuple(items[:limit])

    async def get(self, run_id: UUID) -> SnapshotSyncRunEntity | None:
        """Get a single sync run by its UUID."""
        return self._items.get(run_id)

    async def update_run(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
        """Update an existing sync run record in-place."""
        self._items[run.snapshot_sync_run_id] = run
        return run

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 900,
    ) -> SnapshotSyncHealthSummary:
        """Compute a freshness/staleness summary from in-memory items."""
        items = sorted(self._items.values(), key=lambda e: e.started_at, reverse=True)

        if not items:
            return SnapshotSyncHealthSummary(
                last_run_started_at=None,
                last_run_completed_at=None,
                last_status=None,
                last_successful_run_at=None,
                consecutive_failures=0,
                is_stale=True,
                stale_threshold_seconds=stale_threshold_seconds,
            )

        last = items[0]

        # Most recent successful run
        last_successful: SnapshotSyncRunEntity | None = None
        for e in items:
            if e.status == "completed":
                last_successful = e
                break

        # Count consecutive failures
        consecutive_failures = 0
        for e in items:
            if e.status == "failed":
                consecutive_failures += 1
            else:
                break

        now = datetime.now(timezone.utc)
        last_successful_at = last_successful.started_at if last_successful else None
        is_stale = True
        if last_successful_at is not None:
            is_stale = (now - last_successful_at).total_seconds() > stale_threshold_seconds

        return SnapshotSyncHealthSummary(
            last_run_started_at=last.started_at,
            last_run_completed_at=last.completed_at,
            last_status=last.status,
            last_successful_run_at=last_successful_at,
            consecutive_failures=consecutive_failures,
            is_stale=is_stale,
            stale_threshold_seconds=stale_threshold_seconds,
        )


class InMemoryAgentRunRepository:
    """In-memory implementation of ``AgentRunRepository``."""

    def __init__(self) -> None:
        self._runs: list[AgentRunEntity] = []

    async def add(self, run: AgentRunEntity) -> AgentRunEntity:
        self._runs.append(run)
        return run

    async def get(self, agent_run_id: UUID) -> AgentRunEntity | None:
        """Get a single agent run by its UUID."""
        for run in self._runs:
            if run.agent_run_id == agent_run_id:
                return run
        return None

    async def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[AgentRunEntity]:
        results = [
            r for r in self._runs
            if r.decision_context_id == decision_context_id
        ]
        results.sort(key=lambda r: r.started_at, reverse=True)
        return tuple(results)

    async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
        results = sorted(self._runs, key=lambda r: r.started_at, reverse=True)
        return tuple(results[:limit])

    async def clear(self) -> None:
        self._runs.clear()


class InMemoryExecutionAttemptRepository:
    """In-memory implementation of ``ExecutionAttemptRepository``.

    ``ExecutionAttemptEntity``는 frozen dataclass이므로 ``update_status()``에서는
    ``object.__setattr__``로 필드를 직접 설정한다.
    """

    def __init__(self) -> None:
        self._items: dict[UUID, ExecutionAttemptEntity] = {}

    async def add(self, attempt: ExecutionAttemptEntity) -> ExecutionAttemptEntity:
        self._items[attempt.execution_attempt_id] = attempt
        return attempt

    async def get(self, execution_attempt_id: UUID) -> ExecutionAttemptEntity | None:
        return self._items.get(execution_attempt_id)

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
        entity = self._items.get(execution_attempt_id)
        if entity is not None:
            object.__setattr__(entity, "status", status)
            if stop_phase is not None:
                object.__setattr__(entity, "stop_phase", stop_phase)
            if stop_reason is not None:
                object.__setattr__(entity, "stop_reason", stop_reason)
            if phase_trace is not None:
                object.__setattr__(entity, "phase_trace", phase_trace)
            if order_request_id is not None:
                object.__setattr__(entity, "order_request_id", order_request_id)
            if completed_at is not None:
                object.__setattr__(entity, "completed_at", completed_at)

    async def list_by_trade_decision(
        self, trade_decision_id: UUID
    ) -> Sequence[ExecutionAttemptEntity]:
        results = [
            item
            for item in self._items.values()
            if item.trade_decision_id == trade_decision_id
        ]
        results.sort(key=lambda ea: ea.started_at, reverse=True)
        return tuple(results)


class InMemoryOrderSubmissionAttemptRepository:
    """In-memory implementation of ``OrderSubmissionAttemptRepository``."""

    def __init__(self) -> None:
        self._items: dict[UUID, OrderSubmissionAttemptEntity] = {}

    async def add(
        self, attempt: OrderSubmissionAttemptEntity
    ) -> OrderSubmissionAttemptEntity:
        self._items[attempt.attempt_id] = attempt
        return attempt

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[OrderSubmissionAttemptEntity]:
        results = [
            item
            for item in self._items.values()
            if item.order_request_id == order_request_id
        ]
        results.sort(key=lambda a: a.attempt_number)
        return tuple(results)

    async def list_recent_failures(
        self,
        limit: int = 10,
        *,
        submitted_from: datetime | None = None,
        submitted_to: datetime | None = None,
    ) -> Sequence[dict[str, Any]]:
        """In-memory implementation of list_recent_failures.

        Groups attempts by ``order_request_id``, keeps the latest attempt
        per order by ``attempt_number``, then filters to those whose
        latest outcome is ``'rejected'`` or ``'exception'``.

        .. note::

           Since this in-memory store has no access to ``OrderRepository``,
           ``symbol``, ``side``, and ``created_at`` are returned as ``None``.
        """
        # Group by order_request_id, keep latest attempt per order
        latest: dict[UUID, OrderSubmissionAttemptEntity] = {}
        for a in self._items.values():
            prev = latest.get(a.order_request_id)
            if prev is None or a.attempt_number > prev.attempt_number:
                latest[a.order_request_id] = a

        # Filter to rejected/exception
        failures: list[OrderSubmissionAttemptEntity] = []
        for a in latest.values():
            if a.error_type is not None:
                outcome = "exception"
            elif a.accepted is False:
                outcome = "rejected"
            elif a.accepted is True:
                outcome = "accepted"
            else:
                continue  # skip unknown / no-outcome

            if outcome in ("rejected", "exception"):
                failures.append(a)

        if submitted_from is not None:
            failures = [
                a for a in failures
                if a.submitted_at is not None and a.submitted_at >= submitted_from
            ]
        if submitted_to is not None:
            failures = [
                a for a in failures
                if a.submitted_at is not None and a.submitted_at <= submitted_to
            ]

        # Sort by submitted_at DESC, apply limit
        failures.sort(key=lambda a: a.submitted_at or datetime.min, reverse=True)
        failures = failures[:limit]

        return [
            {
                "order_request_id": str(a.order_request_id),
                "latest_outcome": (
                    "exception" if a.error_type is not None else "rejected"
                ),
                "latest_error_type": a.error_type,
                "latest_raw_code": a.raw_code,
                "latest_raw_message": a.raw_message,
                "last_submitted_at": a.submitted_at,
                "symbol": None,  # InMemory has no order join
                "side": None,
                "created_at": None,
            }
            for a in failures
        ]

    async def get_failure_summary(self) -> dict[str, Any]:
        """In-memory implementation of ``get_failure_summary``.

        Counts all attempts (per-attempt, not DISTINCT ON per order request)
        using the same derived-outcome logic as ``list_recent_failures``.
        Note: time-window filtering is approximated because in-memory tests
        use explicit attempt timestamps.
        """
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        twenty_four_hours_ago = now - timedelta(hours=24)
        kst_today_start = now.astimezone(timezone(timedelta(hours=9))).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).astimezone(timezone.utc)

        last_1h_count = 0
        last_24h_count = 0
        rejected_count = 0
        exception_count = 0
        total_submissions_24h = 0
        today_count = 0
        rejected_count_today = 0
        exception_count_today = 0
        total_submissions_today = 0

        for a in self._items.values():
            if a.submitted_at is None:
                continue

            # Derive outcome
            if a.error_type is not None:
                outcome = "exception"
            elif a.accepted is False:
                outcome = "rejected"
            elif a.accepted is True:
                outcome = "accepted"
            else:
                continue

            if a.submitted_at >= twenty_four_hours_ago:
                total_submissions_24h += 1
                if outcome in ("rejected", "exception"):
                    last_24h_count += 1
                    if outcome == "rejected":
                        rejected_count += 1
                    else:
                        exception_count += 1

                    if a.submitted_at >= one_hour_ago:
                        last_1h_count += 1

            if a.submitted_at >= kst_today_start:
                total_submissions_today += 1
                if outcome in ("rejected", "exception"):
                    today_count += 1
                    if outcome == "rejected":
                        rejected_count_today += 1
                    else:
                        exception_count_today += 1

        result: dict[str, Any] = {
            "last_1h_count": last_1h_count,
            "last_24h_count": last_24h_count,
            "rejected_count": rejected_count,
            "exception_count": exception_count,
            "total_submissions_24h": total_submissions_24h,
            "failure_rate_pct_24h": (
                round(last_24h_count / total_submissions_24h * 100, 1)
                if total_submissions_24h > 0
                else None
            ),
            "today_count": today_count,
            "rejected_count_today": rejected_count_today,
            "exception_count_today": exception_count_today,
            "total_submissions_today": total_submissions_today,
            "failure_rate_pct_today": (
                round(today_count / total_submissions_today * 100, 1)
                if total_submissions_today > 0
                else None
            ),
        }
        return result


class InMemoryMarketSessionRepository:
    """In-memory implementation of ``MarketSessionRepository``."""

    def __init__(self) -> None:
        self._sessions: list[MarketSessionEntity] = []
        self._events: list[SessionEventEntity] = []
        self._next_session_id: int = 1
        self._next_event_id: int = 1

    async def upsert(self, session: MarketSessionEntity) -> MarketSessionEntity:
        """Upsert by ``run_date`` — update if exists, else insert."""
        for i, existing in enumerate(self._sessions):
            if existing.run_date == session.run_date:
                updated = MarketSessionEntity(
                    id=existing.id,
                    run_date=session.run_date,
                    is_trading_day=session.is_trading_day,
                    opnd_yn=session.opnd_yn,
                    bzdy_yn=session.bzdy_yn,
                    tr_day_yn=session.tr_day_yn,
                    market_phase=session.market_phase,
                    raw_opnd_yn=session.raw_opnd_yn,
                    raw_mkop_cls_code=session.raw_mkop_cls_code,
                    raw_antc_mkop_cls_code=session.raw_antc_mkop_cls_code,
                    source=session.source,
                    reason_code=session.reason_code,
                    reason=session.reason,
                    reason_metadata=session.reason_metadata,
                    checked_at=session.checked_at or datetime.now(timezone.utc),
                    created_at=existing.created_at or datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                self._sessions[i] = updated
                return updated
        # Insert new
        new = MarketSessionEntity(
            id=self._next_session_id,
            run_date=session.run_date,
            is_trading_day=session.is_trading_day,
            opnd_yn=session.opnd_yn,
            bzdy_yn=session.bzdy_yn,
            tr_day_yn=session.tr_day_yn,
            market_phase=session.market_phase,
            raw_opnd_yn=session.raw_opnd_yn,
            raw_mkop_cls_code=session.raw_mkop_cls_code,
            raw_antc_mkop_cls_code=session.raw_antc_mkop_cls_code,
            source=session.source,
            reason_code=session.reason_code,
            reason=session.reason,
            reason_metadata=session.reason_metadata,
            checked_at=session.checked_at or datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self._next_session_id += 1
        self._sessions.append(new)
        return new

    async def get_by_run_date(self, run_date: date) -> MarketSessionEntity | None:
        for s in self._sessions:
            if s.run_date == run_date:
                return s
        return None

    async def list_recent(
        self, limit: int = 10
    ) -> Sequence[MarketSessionEntity]:
        results = sorted(
            self._sessions,
            key=lambda s: s.run_date if s.run_date else date.min,
            reverse=True,
        )
        return tuple(results[:limit])

    async def add_event(self, event: SessionEventEntity) -> SessionEventEntity:
        new = SessionEventEntity(
            id=self._next_event_id,
            market_session_id=event.market_session_id,
            previous_phase=event.previous_phase,
            new_phase=event.new_phase,
            trigger_source=event.trigger_source,
            metadata=event.metadata,
            occurred_at=event.occurred_at or datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        self._next_event_id += 1
        self._events.append(new)
        return new

    async def get_events(
        self, market_session_id: int, limit: int = 50
    ) -> Sequence[SessionEventEntity]:
        results = [
            e for e in self._events
            if e.market_session_id == market_session_id
        ]
        results.sort(key=lambda e: e.occurred_at or datetime.min, reverse=True)
        return tuple(results[:limit])

    async def clear(self) -> None:
        self._sessions.clear()
        self._events.clear()
        self._next_session_id = 1
        self._next_event_id = 1
