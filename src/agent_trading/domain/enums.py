from __future__ import annotations

from enum import Enum


class Environment(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class BrokerName(str, Enum):
    KOREA_INVESTMENT = "koreainvestment"
    KIWOOM = "kiwoom"


class AssetClass(str, Enum):
    KR_STOCK = "kr_stock"
    KR_ETF = "kr_etf"
    KR_FUTURES = "kr_futures"
    KR_OPTIONS = "kr_options"
    US_STOCK = "us_stock"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    DAY = "day"
    IOC = "ioc"
    FOK = "fok"


class OrderStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PENDING_SUBMIT = "pending_submit"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    RECONCILE_REQUIRED = "reconcile_required"


class BrokerErrorType(str, Enum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    ORDER_REJECTED = "order_rejected"
    TEMPORARY_BROKER = "temporary_broker"
    DATA_UNAVAILABLE = "data_unavailable"


class MarketDataChannel(str, Enum):
    QUOTE = "quote"
    ORDERBOOK = "orderbook"
    TRADE_TICK = "trade_tick"
    ORDER_EVENT = "order_event"


class EventSource(str, Enum):
    """Origin of a state-change event."""
    INTERNAL = "internal"
    BROKER_REST = "broker_rest"
    BROKER_WS = "broker_ws"
    RECONCILIATION = "reconciliation"
    OPERATOR = "operator"


class GuardrailAction(str, Enum):
    """Result of a guardrail rule evaluation."""
    BLOCK = "block"
    WARN = "warn"
    ALLOW = "allow"
    ESCALATE = "escalate"


class ReconciliationStatus(str, Enum):
    """Status of a reconciliation run."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class DecisionType(str, Enum):
    """Type of trade decision made by the AI layer."""
    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"
    WATCH = "watch"
    EXIT = "exit"
    REDUCE = "reduce"


class EntryStyle(str, Enum):
    """Execution style for entering a trade."""
    LIMIT = "limit"
    MARKET = "market"
    VWAP = "vwap"
    TWAP = "twap"
    NO_ORDER = "no_order"


class BucketType(str, Enum):
    """Operation bucket types for rate limit budgeting.

    Each bucket is independent — reconciliation budget is never consumed
    by order or inquiry calls.
    """

    AUTH = "auth"
    ORDER = "order"
    INQUIRY = "inquiry"
    RECONCILIATION = "reconciliation"
    MARKET_DATA = "market_data"


class SourceReliabilityTier(str, Enum):
    """Reliability tier for external event data sources.

    T1 — Regulatory / official (OpenDART, KRX KIND, government).
    T2 — Institutional / research (broker reports, exchange data).
    T3 — Media / aggregator (news, media, screener).
    T4 — Low-confidence / experimental (unverified sources).
    """

    T1_REGULATORY = "T1"
    T2_INSTITUTIONAL = "T2"
    T3_MEDIA = "T3"
    T4_LOW_CONFIDENCE = "T4"

