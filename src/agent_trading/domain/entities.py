from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from agent_trading.domain.enums import (
    DecisionType,
    EntryStyle,
    Environment,
    EventSource,
    GuardrailAction,
    OrderSide,
    OrderStatus,
    OrderType,
    ReconciliationStatus,
    TimeInForce,
)


@dataclass(slots=True, frozen=True)
class ClientEntity:
    client_id: UUID
    client_code: str
    name: str
    status: str
    base_currency: str = "KRW"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class BrokerAccountEntity:
    broker_account_id: UUID
    broker_name: str
    account_ref: str
    environment: Environment
    credential_ref: str
    base_url: str | None = None
    status: str = "active"
    broker_account_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AccountEntity:
    account_id: UUID
    client_id: UUID
    broker_account_id: UUID
    environment: Environment
    account_alias: str
    account_masked: str
    status: str
    risk_profile: dict[str, object] = field(default_factory=dict)
    account_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class StrategyEntity:
    strategy_id: UUID
    client_id: UUID
    strategy_code: str
    name: str
    asset_class: str
    status: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class ConfigVersionEntity:
    config_version_id: UUID
    client_id: UUID
    environment: Environment
    version_tag: str
    config_json: dict[str, object]
    checksum: str
    created_at: datetime | None = None
    activated_at: datetime | None = None
    activated_by: str | None = None


@dataclass(slots=True, frozen=True)
class TradingSessionEntity:
    trading_session_id: UUID
    account_id: UUID
    session_date: date
    market_code: str
    status: str
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class InstrumentEntity:
    instrument_id: UUID
    symbol: str
    market_code: str
    asset_class: str
    currency: str
    name: str
    tick_size: Decimal | None = None
    lot_size: Decimal | None = None
    is_active: bool = True
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class PositionSnapshotEntity:
    position_snapshot_id: UUID
    account_id: UUID
    instrument_id: UUID
    quantity: Decimal
    average_price: Decimal
    market_price: Decimal | None
    unrealized_pnl: Decimal | None
    source_of_truth: str
    snapshot_at: datetime
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class CashBalanceSnapshotEntity:
    cash_balance_snapshot_id: UUID
    account_id: UUID
    currency: str
    available_cash: Decimal
    settled_cash: Decimal | None
    unsettled_cash: Decimal | None
    source_of_truth: str
    snapshot_at: datetime
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class DecisionContextEntity:
    decision_context_id: UUID
    account_id: UUID
    strategy_id: UUID
    config_version_id: UUID
    market_timestamp: datetime
    correlation_id: str
    strategy_version_id: UUID | None = None
    trading_session_id: UUID | None = None
    feature_snapshot_id: UUID | None = None
    position_snapshot_id: UUID | None = None
    cash_balance_snapshot_id: UUID | None = None
    input_bundle_uri: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AgentRunEntity:
    agent_run_id: UUID
    decision_context_id: UUID
    agent_type: str
    started_at: datetime
    model_id: UUID | None = None
    prompt_id: UUID | None = None
    temperature: Decimal | None = None
    seed: int | None = None
    raw_output_uri: str | None = None
    structured_output_json: dict[str, object] | None = None
    status: str = "completed"
    completed_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class TradeDecisionEntity:
    """Trade decision entity representing an AI-driven trading decision.

    P0 fields are required for core decision persistence.
    P1 fields are extended metadata for analysis and audit.
    Total: 29 fields (11 P0 + 18 P1).
    """
    # -- P0: Core decision fields (required for persistence) --
    trade_decision_id: UUID
    decision_context_id: UUID
    decision_type: DecisionType
    side: OrderSide
    strategy_id: UUID
    symbol: str
    market: str
    entry_style: EntryStyle
    created_at: datetime

    # -- P0: Optional core fields --
    entry_price: Decimal | None = None
    quantity: Decimal | None = None
    max_order_value: Decimal | None = None
    price_band_lower: Decimal | None = None
    price_band_upper: Decimal | None = None

    # -- P1: Extended analysis fields (nullable, for future use) --
    expected_return_bps: Decimal | None = None
    expected_downside_bps: Decimal | None = None
    net_expected_value_bps: Decimal | None = None
    final_trade_score: Decimal | None = None
    minimum_required_edge_bps: Decimal | None = None
    regime_label: str | None = None
    strategy_fit_score: Decimal | None = None
    risk_check_passed: bool | None = None
    compliance_check_passed: bool | None = None
    execution_check_passed: bool | None = None
    failed_rule_codes: list[str] | None = None
    reason_codes: list[str] | None = None
    opposing_evidence: dict[str, object] = field(default_factory=dict)
    exit_plan_json: dict[str, object] = field(default_factory=dict)
    calculation_version: str | None = None
    agent_version_json: dict[str, object] = field(default_factory=dict)
    model_version_json: dict[str, object] = field(default_factory=dict)
    prompt_version_json: dict[str, object] = field(default_factory=dict)

    # -- Legacy fields (kept for backward compatibility) --
    agent_run_id: UUID | None = None
    instrument_id: UUID | None = None
    target_quantity: Decimal | None = None
    target_notional: Decimal | None = None
    limit_price: Decimal | None = None
    confidence: Decimal | None = None
    rationale_summary: str | None = None
    decision_json: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OrderRequestEntity:
    order_request_id: UUID
    account_id: UUID
    instrument_id: UUID
    client_order_id: str
    idempotency_key: str
    correlation_id: str
    side: OrderSide
    order_type: OrderType
    requested_quantity: Decimal
    status: OrderStatus
    trade_decision_id: UUID | None = None
    # -- P0: Decision tracing (Milestone 6) --
    decision_context_id: UUID | None = None
    requested_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    status_reason_code: str | None = None
    status_reason_message: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1
    # -- P1: Optional tracing (Milestone 6) --
    order_intent_id: UUID | None = None


@dataclass(slots=True, frozen=True)
class BrokerOrderEntity:
    broker_order_id: UUID
    order_request_id: UUID
    broker_name: str
    broker_status: str
    broker_native_order_id: str | None = None
    request_payload_uri: str | None = None
    response_payload_uri: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class FillEventEntity:
    fill_event_id: UUID
    broker_order_id: UUID
    fill_timestamp: datetime
    fill_price: Decimal
    fill_quantity: Decimal
    source_channel: str
    broker_fill_id: str | None = None
    fill_fee: Decimal | None = None
    fill_tax: Decimal | None = None
    raw_payload_uri: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class ReconciliationRunEntity:
    reconciliation_run_id: UUID
    account_id: UUID
    trigger_type: str
    status: str
    started_at: datetime
    mismatch_count: int = 0
    summary_json: dict[str, object] = field(default_factory=dict)
    completed_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class BlockingLockEntity:
    """Read-only inspection entity for a blocking lock on a strategy/symbol.

    Maps directly to ``trading.order_blocking_locks`` rows.
    Active check: ``expires_at > NOW()`` (or ``resolved_at IS NULL`` if
    soft-delete columns are added in the future).
    """
    lock_id: UUID
    account_id: UUID
    strategy_id: UUID | None = None
    symbol: str | None = None
    side: str | None = None
    reason: str = "reconciliation"
    locked_by_run_id: UUID | None = None
    locked_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AuditLogEntity:
    audit_log_id: UUID
    actor_type: str
    actor_id: str
    action: str
    target_entity_type: str
    target_entity_id: str
    created_at: datetime
    before_json: dict[str, object] | None = None
    after_json: dict[str, object] | None = None
    correlation_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OrderStateEventEntity:
    """Append-only record of every order status transition.

    This is a **supplementary** audit trail, not a replacement for the
    current-state stored in ``order_requests.status``.
    """
    order_state_event_id: UUID
    order_request_id: UUID
    new_status: OrderStatus
    event_source: EventSource
    event_timestamp: datetime
    ingested_at: datetime
    previous_status: OrderStatus | None = None
    reason_code: str | None = None
    raw_event_uri: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class GuardrailEvaluationEntity:
    """Result of a guardrail rule evaluation against a decision or order."""
    guardrail_evaluation_id: UUID
    rule_set_version: str
    overall_passed: bool
    evaluated_at: datetime
    decision_context_id: UUID | None = None
    trade_decision_id: UUID | None = None
    order_request_id: UUID | None = None
    rule_results: dict[str, object] = field(default_factory=dict)
    blocking_rule_codes: list[str] | None = None
    warning_rule_codes: list[str] | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class RiskLimitSnapshotEntity:
    """Point-in-time snapshot of risk limits and exposure for an account."""
    risk_limit_snapshot_id: UUID
    account_id: UUID
    snapshot_at: datetime
    nav: Decimal | None = None
    cash_available: Decimal | None = None
    gross_exposure_pct: Decimal | None = None
    net_exposure_pct: Decimal | None = None
    daily_realized_pnl: Decimal | None = None
    daily_unrealized_pnl: Decimal | None = None
    daily_loss_used_pct: Decimal | None = None
    max_daily_loss_limit_pct: Decimal | None = None
    symbol_exposure_json: dict[str, object] = field(default_factory=dict)
    sector_exposure_json: dict[str, object] = field(default_factory=dict)
    open_order_exposure_json: dict[str, object] = field(default_factory=dict)
    drawdown_state: str | None = None
    kill_switch_active: bool = False
    blocked_reason_codes: list[str] | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class ExternalEventEntity:
    """Normalised external event data (disclosure, news, macro, etc.).

    This is a **foundation** entity for Milestone 7. Actual polling
    workers and source adapters are deferred to a later milestone.
    """

    event_id: UUID
    event_type: str
    source_name: str
    published_at: datetime
    source_reliability_tier: str = "T3"
    source_event_id: str | None = None
    issuer_code: str | None = None
    symbol: str | None = None
    market: str | None = None
    ingested_at: datetime | None = None
    effective_at: datetime | None = None
    severity: str = "medium"
    direction: str = "neutral"
    headline: str | None = None
    body_summary: str | None = None
    raw_payload_uri: str | None = None
    dedup_key_hash: str | None = None
    supersedes_event_id: UUID | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
