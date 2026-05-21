from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from agent_trading.domain.enums import Environment, OrderStatus


@dataclass(slots=True, frozen=True)
class AccountLookup:
    account_id: UUID | None = None
    client_id: UUID | None = None
    account_alias: str | None = None
    environment: Environment | None = None
    broker_account_id: UUID | None = None


@dataclass(slots=True, frozen=True)
class OrderQuery:
    account_id: UUID | None = None
    client_order_id: str | None = None
    correlation_id: str | None = None
    status: OrderStatus | None = None
    statuses: Sequence[OrderStatus] | None = None
    trade_decision_id: UUID | None = None
    decision_context_id: UUID | None = None
    submitted_from: datetime | None = None
    submitted_to: datetime | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = 100


@dataclass(slots=True, frozen=True)
class DecisionContextQuery:
    account_id: UUID | None = None
    strategy_id: UUID | None = None
    correlation_id: str | None = None
    market_timestamp_from: datetime | None = None
    market_timestamp_to: datetime | None = None
    limit: int = 100
