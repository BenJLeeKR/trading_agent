from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from agent_trading.domain.enums import (
    AssetClass,
    BrokerName,
    MarketDataChannel,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)


@dataclass(slots=True, frozen=True)
class RateLimitProfile:
    requests_per_second: int | None = None
    burst_limit: int | None = None
    notes: str | None = None


@dataclass(slots=True, frozen=True)
class BrokerCapability:
    broker_name: BrokerName
    supports_paper_trading: bool
    supports_live_trading: bool
    supports_websocket: bool
    supported_asset_classes: tuple[AssetClass, ...]
    supported_order_types: tuple[OrderType, ...]
    supported_time_in_force: tuple[TimeInForce, ...]
    supports_order_amend: bool = False
    supports_order_cancel: bool = True
    rate_limit_profile: RateLimitProfile | None = None


@dataclass(slots=True, frozen=True)
class BrokerHealth:
    broker_name: BrokerName
    healthy: bool
    checked_at: datetime
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class BrokerSession:
    broker_name: BrokerName
    authenticated_at: datetime
    expires_at: datetime | None = None
    approval_key_expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class Quote:
    symbol: str
    market: str
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    as_of: datetime
    currency: str = "KRW"


@dataclass(slots=True, frozen=True)
class OrderBookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(slots=True, frozen=True)
class OrderBook:
    symbol: str
    market: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    as_of: datetime


@dataclass(slots=True, frozen=True)
class Position:
    account_ref: str
    symbol: str
    quantity: Decimal
    average_price: Decimal
    market_price: Decimal | None
    currency: str = "KRW"


@dataclass(slots=True, frozen=True)
class CashBalance:
    account_ref: str
    available_cash: Decimal
    settled_cash: Decimal | None = None
    currency: str = "KRW"
    as_of: datetime | None = None


@dataclass(slots=True, frozen=True)
class SubmitOrderRequest:
    """Order submission request sent to a broker adapter.

    Extended in Milestone 5 with fields for idempotency, decision tracing,
    price bands, slippage control, and metadata.
    """

    account_ref: str
    client_order_id: str
    correlation_id: str
    strategy_id: str
    symbol: str
    market: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    time_in_force: TimeInForce = TimeInForce.DAY
    price: Decimal | None = None
    # --- Milestone 5 extensions ---
    idempotency_key: str | None = None
    decision_id: str | None = None
    decision_context_id: str | None = None
    order_intent_id: str | None = None
    price_band_lower: Decimal | None = None
    price_band_upper: Decimal | None = None
    max_slippage_bps: int | None = None
    allow_partial_fill: bool = True
    client_timestamp: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SubmitOrderResult:
    """Result returned by a broker adapter after order submission.

    Extended in Milestone 5 with fields for idempotency, normalized status,
    exchange timestamps, uncertainty flags, and reconciliation hints.
    """

    accepted: bool
    broker_name: BrokerName
    client_order_id: str
    broker_order_id: str | None
    broker_status: OrderStatus
    ack_timestamp: datetime | None
    raw_code: str | None = None
    raw_message: str | None = None
    # --- Milestone 5 extensions ---
    idempotency_key: str | None = None
    normalized_status: OrderStatus | None = None
    exchange_timestamp: datetime | None = None
    raw_payload_uri: str | None = None
    uncertain: bool = False
    requires_reconciliation: bool = False


@dataclass(slots=True, frozen=True)
class CancelOrderRequest:
    account_ref: str
    client_order_id: str
    broker_order_id: str | None
    correlation_id: str
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class CancelOrderResult:
    accepted: bool
    broker_name: BrokerName
    client_order_id: str
    broker_order_id: str | None
    broker_status: OrderStatus
    raw_code: str | None = None
    raw_message: str | None = None


@dataclass(slots=True, frozen=True)
class AmendOrderRequest:
    account_ref: str
    client_order_id: str
    broker_order_id: str | None
    correlation_id: str
    new_quantity: Decimal | None = None
    new_price: Decimal | None = None


@dataclass(slots=True, frozen=True)
class AmendOrderResult:
    accepted: bool
    broker_name: BrokerName
    client_order_id: str
    broker_order_id: str | None
    broker_status: OrderStatus
    raw_code: str | None = None
    raw_message: str | None = None


@dataclass(slots=True, frozen=True)
class OrderStatusResult:
    broker_name: BrokerName
    client_order_id: str | None
    broker_order_id: str | None
    status: OrderStatus
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal | None = None
    average_fill_price: Decimal | None = None
    last_updated_at: datetime | None = None
    raw_code: str | None = None
    raw_message: str | None = None


@dataclass(slots=True, frozen=True)
class FillEvent:
    broker_name: BrokerName
    broker_order_id: str
    symbol: str
    side: OrderSide
    fill_quantity: Decimal
    fill_price: Decimal
    fill_timestamp: datetime
    fee: Decimal | None = None
    tax: Decimal | None = None


@dataclass(slots=True, frozen=True)
class MarketDataSubscription:
    channel: MarketDataChannel
    symbol: str
    market: str

