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
    HELD_POSITION_RECENT_BUY_SELL_COOLDOWN = "held_position_recent_buy_sell_cooldown"
    HELD_POSITION_RECENT_RISK_SELL_COOLDOWN = "held_position_recent_risk_sell_cooldown"
    SAME_SYMBOL_REENTRY_COOLDOWN = "same_symbol_reentry_cooldown"
    REVERSE_TRADE_SAME_SIGNAL_FEATURE_SNAPSHOT = "reverse_trade_same_signal_feature_snapshot"
    HOLDING_PROFILE_EARLIEST_REDUCE_GUARD = "holding_profile_earliest_reduce_guard"
    HOLDING_PROFILE_EARLIEST_REENTRY_GUARD = "holding_profile_earliest_reentry_guard"
    CLI_DRY_RUN = "cli_dry_run"
    HELD_POSITION_SELL_CYCLE_CAP = "held_position_sell_cycle_cap"
    HELD_POSITION_SELL_SYMBOL_DUPLICATE = "held_position_sell_symbol_duplicate"

    # Execution pipeline stops / skips
    MISSING_REFERENCE_PRICE_FOR_MARKET_BUY = "missing_reference_price_for_market_buy"
    SIZING_REJECTED = "sizing_rejected"
    LOW_LIQUIDITY_EXECUTION_BLOCKED = "low_liquidity_execution_blocked"
    SELL_GUARD_BLOCKED = "sell_guard_blocked"
    PROBE_CHURN_SINGLE_SHARE_BLOCKED = "probe_churn_single_share_blocked"
    OVERLAY_SINGLE_SHARE_BUY_BLOCKED = "overlay_single_share_buy_blocked"
    REVERSE_TRADE_SINGLE_SHARE_BLOCKED = "reverse_trade_single_share_blocked"
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


class RealizedPnlComputationRunType(str, Enum):
    """이동평균 실현 손익 ledger 계산 실행의 종류.

    ``trading.realized_pnl_computation_runs.run_type`` CHECK 제약과 동일한
    2개 값으로 닫혀 있다(db/migrations/0053_add_realized_pnl_ledger_tables.sql).
    계산 엔진이 이 값을 기준으로 "단일 fill 증분 반영"과 "계좌×종목 전체
    히스토리 replay"를 분기하므로(설계 문서 6절 — 이동평균은 중간 지점
    재계산이 불가능해 replay는 항상 처음부터 다시 돎) enum으로 승격한다.
    """

    REALTIME_INCREMENTAL = "realtime_incremental"
    BACKFILL_REPLAY = "backfill_replay"


class RealizedPnlFeeTaxSource(str, Enum):
    """실현 손익 이벤트의 수수료/세금 출처 구분.

    ``trading.realized_pnl_events.fee_tax_source`` CHECK 제약과 동일한 4개
    값으로 닫혀 있다(설계 문서 12번 13절). 계산 엔진이 매 이벤트 생성 시
    항상 채워야 하는 계산 provenance 필드다. 4값은 서로 배타적이며,
    판정 순서는 항상 "자산군/시장군이 정책 지원 대상인가 → (지원 대상이면)
    활성 정책이 있는가"다 — 지원 대상이 아니면 ``POLICY_NOT_APPLICABLE``,
    지원 대상인데 정책이 없으면 ``ASSUMED_ZERO``다.

    - ``REPORTED``: 브로커가 fee/tax를 직접 보고한 값.
    - ``CALCULATED_FROM_POLICY``: 지원 대상 자산군·시장군이고 활성 정책값이
      있어 우리가 계산한 값.
    - ``ASSUMED_ZERO``: 지원 대상 자산군인데 정책이 아직 없거나 비활성이라
      0으로 간주한 값.
    - ``POLICY_NOT_APPLICABLE``: 이 정책의 지원 대상 자산군/시장군이 애초에
      아니라서 계산을 시도조차 하지 않은 경우.

    ``REPORTED``의 0과 ``ASSUMED_ZERO``의 0은 의미가 다르다 — 전자는
    브로커가 확정해 준 0, 후자는 우리가 모른다는 뜻으로 채운 0이다.
    """

    REPORTED = "reported"
    ASSUMED_ZERO = "assumed_zero"
    CALCULATED_FROM_POLICY = "calculated_from_policy"
    POLICY_NOT_APPLICABLE = "policy_not_applicable"


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
