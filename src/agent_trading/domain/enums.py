from __future__ import annotations

from enum import Enum


class Environment(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    REAL = "real"  # KIS actual naming — normalized to LIVE internally


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
    NETWORK_ERROR = "network_error"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    ORDER_REJECTED = "order_rejected"
    TEMPORARY_BROKER = "temporary_broker"
    DATA_UNAVAILABLE = "data_unavailable"
    API_ERROR = "api_error"
    TIMEOUT = "timeout"


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


class PipelineStopReason(str, Enum):
    """Canonical deterministic stop / guardrail reason codes.

    Values are stable wire-format strings used across:
    - pre-AI skip gates
    - execution attempt stop reasons
    - submit pipeline serialized results
    """

    # Pre-AI deterministic gates
    NO_HELD_POSITION = "no_held_position"
    GENERAL_BUY_BUDGET_EXHAUSTED = "general_buy_budget_exhausted"
    NEGATIVE_ORDERABLE_AMOUNT = "negative_orderable_amount"
    LOW_ORDERABLE_AMOUNT = "low_orderable_amount"
    HELD_POSITION_RECENT_HOLD_NO_CHANGE = "held_position_recent_hold_no_change"
    CLI_DRY_RUN = "cli_dry_run"
    HELD_POSITION_SELL_CYCLE_CAP = "held_position_sell_cycle_cap"
    HELD_POSITION_SELL_SYMBOL_DUPLICATE = "held_position_sell_symbol_duplicate"

    # Execution pipeline stops / skips
    MISSING_REFERENCE_PRICE_FOR_MARKET_BUY = "missing_reference_price_for_market_buy"
    SIZING_REJECTED = "sizing_rejected"
    SELL_GUARD_BLOCKED = "sell_guard_blocked"
    DECISION_HOLD = "decision_hold"
    DECISION_WATCH = "decision_watch"
    RECENT_ACTIVE_BUY_ORDER = "recent_active_buy_order"
    STALE_SNAPSHOT = "stale_snapshot"
    STALE_SNAPSHOT_ACCOUNT = "stale_snapshot_account"
    STALE_SNAPSHOT_RUN = "stale_snapshot_run"

    # Execution pipeline errors / terminals
    ORDER_CREATE_FAILED = "order_create_failed"
    TRANSITION_FAILED = "transition_failed"
    BROKER_SUBMIT_FAILED = "broker_submit_failed"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_RECONCILE_REQUIRED = "order_reconcile_required"
    ORDER_REJECTED = "order_rejected"


def general_submit_disabled_reason(source_type: str) -> str:
    """Return the canonical scheduler gate reason for disabled general submit."""
    normalized = (source_type or "unknown").strip().lower()
    return f"general_submit_disabled_{normalized}"


def submit_budget_consumed_reason(source_type: str) -> str:
    """Return the canonical scheduler gate reason for consumed cycle submit budget."""
    normalized = (source_type or "unknown").strip().lower()
    return f"submit_budget_consumed_{normalized}"


class ReconciliationStatus(str, Enum):
    """Status of a reconciliation run."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    REFLECTION_FAILED = "reflection_failed"


class DecisionType(str, Enum):
    """Type of trade decision made by the AI layer."""
    APPROVE = "approve"
    REJECT = "reject"
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"
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
