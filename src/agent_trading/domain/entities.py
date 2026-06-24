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
    exchange_code: str | None = None
    market_segment: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class InstrumentIndexMembershipEntity:
    instrument_index_membership_id: UUID
    instrument_id: UUID
    membership_code: str
    effective_from: date
    effective_to: date | None = None
    source_tag: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class SymbolTradeStateEntity:
    symbol_trade_state_id: UUID
    account_id: UUID
    instrument_id: UUID
    symbol: str
    market: str
    state: str
    holding_profile: str | None = None
    position_quantity: Decimal = Decimal("0")
    last_entry_order_request_id: UUID | None = None
    last_exit_order_request_id: UUID | None = None
    last_entry_source_type: str | None = None
    last_entry_at: datetime | None = None
    last_reduce_at: datetime | None = None
    last_exit_at: datetime | None = None
    minimum_hold_until: datetime | None = None
    reentry_cooldown_until: datetime | None = None
    sell_cooldown_until: datetime | None = None
    last_signal_feature_snapshot_id: UUID | None = None
    last_decision_context_id: UUID | None = None
    last_reason_codes: list[str] = field(default_factory=list)
    thesis_state_hash: str | None = None
    metadata_json: dict[str, object] = field(default_factory=dict)
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
    purchase_amount: Decimal | None = None
    evaluation_amount: Decimal | None = None
    created_at: datetime | None = None
    fetch_status: str = "success"
    """Status of this snapshot fetch: 'success' | 'partial' | 'stale' | 'fetch_failed' | 'zeroed_out'"""
    snapshot_sync_run_id: UUID | None = None
    """FK to ``snapshot_sync_runs.snapshot_sync_run_id``.
    Allows exact same-run alignment with cash balance snapshots."""


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
    # ── KIS output2 account-level summary fields ──
    # total_asset: KIS tot_evlu_amt (총평가금액 = 유가증권 평가금액 합계 + D+2 예수금)
    # settlement_amount: KIS prvs_rcdl_excc_amt (가수도정산금액, D+2 예수금 기준)
    # total_unrealized_pnl: KIS evlu_pfls_smtl_amt (평가손익합계금액, 계좌 총괄)
    # orderable_amount: KIS ord_psbl_amt (주문가능금액, 실제 주문 가능 현금)
    total_asset: Decimal | None = None
    settlement_amount: Decimal | None = None
    total_unrealized_pnl: Decimal | None = None
    orderable_amount: Decimal | None = None
    created_at: datetime | None = None
    fetch_status: str = "success"
    """Status of this snapshot fetch: 'success' | 'stale' | 'fetch_failed'"""
    snapshot_sync_run_id: UUID | None = None
    """FK to ``snapshot_sync_runs.snapshot_sync_run_id``.
    Allows exact same-run alignment with position snapshots."""


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
    signal_feature_snapshot_id: UUID | None = None
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

    # -- Axis 2: Source type for no-event policy differentiation --
    source_type: str | None = None
    """Origin of this symbol's inclusion: ``"core"`` | ``"held_position"`` | ``"event_overlay"`` | ``"market_overlay"`` | ``"manual"``."""

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
class FillSyncRunEntity:
    fill_sync_run_id: UUID
    trigger_type: str
    scope: str
    dry_run: bool
    total_accounts: int
    succeeded_accounts: int
    partial_accounts: int
    failed_accounts: int
    skipped_accounts: int
    fills_synced_total: int
    fills_skipped_total: int
    error_count: int
    status: str
    started_at: datetime
    env_filter: str | None = None
    summary_json: dict[str, object] | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class BrokerFillSnapshotEntity:
    broker_fill_snapshot_id: UUID
    account_id: UUID
    broker_name: str
    broker_native_order_id: str
    symbol: str
    side: str
    order_date: date
    filled_quantity: Decimal
    fill_price: Decimal
    dedupe_key: str
    order_request_id: UUID | None = None
    fill_sync_run_id: UUID | None = None
    broker_fill_id: str | None = None
    order_status_code: str | None = None
    cancel_yn: str | None = None
    ordered_quantity: Decimal | None = None
    order_time: str | None = None
    fill_time: str | None = None
    fill_timestamp: datetime | None = None
    raw_payload_json: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
class ReconciliationOrderLinkEntity:
    """Order link attached to a reconciliation run.

    Records which order triggered or was identified during reconciliation.
    """
    reconciliation_run_id: UUID
    order_request_id: UUID
    mismatch_type: str
    details_json: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class ReconciliationPositionLinkEntity:
    """Position link attached to a reconciliation run."""
    reconciliation_run_id: UUID
    position_snapshot_id: UUID
    mismatch_type: str
    details_json: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class SnapshotSyncRunEntity:
    """Record of a single KIS snapshot sync execution.

    Stores run-level summary only (not individual position/cash rows).
    Follows the same pattern as ``ReconciliationRunEntity``.
    """
    snapshot_sync_run_id: UUID
    trigger_type: str  # "manual" | "scheduler"
    scope: str  # "single" | "batch" | "all"
    dry_run: bool
    total_accounts: int
    succeeded_accounts: int
    partial_accounts: int
    failed_accounts: int
    skipped_accounts: int
    positions_synced_total: int
    positions_skipped_total: int
    cash_synced_count: int
    error_count: int
    status: str  # "completed" | "partial" | "failed"
    started_at: datetime
    after_hours: bool = False
    """Whether this sync was an after-hours cash-only run."""
    env_filter: str | None = None
    status_filter: str | None = None
    summary_json: dict[str, object] | None = None
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
class SignalFeatureSnapshotEntity:
    """종목 단위 결정론적 signal feature snapshot."""

    signal_feature_snapshot_id: UUID
    instrument_id: UUID
    timeframe: str
    snapshot_at: datetime
    feature_set_version: str
    bar_count: int
    sma_5: Decimal | None = None
    sma_20: Decimal | None = None
    sma_60: Decimal | None = None
    price_vs_sma_20_pct: Decimal | None = None
    price_vs_sma_60_pct: Decimal | None = None
    return_1m_pct: Decimal | None = None
    return_3m_pct: Decimal | None = None
    volatility_20d_pct: Decimal | None = None
    atr_14_pct: Decimal | None = None
    rsi_14: Decimal | None = None
    average_volume_20d: Decimal | None = None
    average_turnover_20d: Decimal | None = None
    volume_surge_ratio: Decimal | None = None
    turnover_surge_ratio: Decimal | None = None
    fast_score: Decimal | None = None
    slow_score: Decimal | None = None
    overall_score: Decimal | None = None
    component_scores_json: dict[str, object] = field(default_factory=dict)
    reason_codes: list[str] | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class UniverseFreezeRunEntity:
    """특정 시점에 고정된 trading universe 집합의 실행 메타데이터."""

    universe_freeze_run_id: UUID
    business_date: date
    freeze_purpose: str
    freeze_sequence: int
    frozen_at: datetime
    selection_version: str
    selection_params_json: dict[str, object] = field(default_factory=dict)
    target_count: int = 0
    status: str = "created"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class UniverseFreezeRunItemEntity:
    """하나의 freeze run에 포함된 종목 row."""

    universe_freeze_run_item_id: UUID
    universe_freeze_run_id: UUID
    instrument_id: UUID
    symbol: str
    market_code: str
    source_type: str
    inclusion_reason: str
    priority_score: Decimal | None = None
    rank: int | None = None
    cap_bucket: str | None = None
    metadata_json: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class SignalFeatureBatchRunEntity:
    """signal feature 배치 1회 실행 메타데이터."""

    signal_feature_batch_run_id: UUID
    business_date: date
    universe_freeze_run_id: UUID | None = None
    trigger_type: str = "scheduler"
    timeframe: str = "1d"
    feature_set_version: str = "signal_backbone_v1"
    input_uri: str | None = None
    dry_run: bool = False
    target_count: int = 0
    fetch_success_count: int = 0
    fetch_error_count: int = 0
    persist_success_count: int = 0
    persist_error_count: int = 0
    skipped_count: int = 0
    final_missing_count: int = 0
    status: str = "running"
    summary_json: dict[str, object] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class SignalFeatureBatchRunItemEntity:
    """signal feature 배치 내 종목별 처리 상태."""

    signal_feature_batch_run_item_id: UUID
    signal_feature_batch_run_id: UUID
    instrument_id: UUID | None
    symbol: str
    market_code: str
    timeframe: str
    feature_set_version: str
    status: str
    signal_feature_snapshot_id: UUID | None = None
    snapshot_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata_json: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class MarketSessionEntity:
    """장운영 세션 상태 엔티티 — run_date 기준 1행, P2 scheduler가 주기적으로 upsert.

    ``id``는 ``BIGSERIAL`` (int)이며, ``run_date``에 unique index가 있어
    동일 일자에 대해 upsert (INSERT … ON CONFLICT) 로 갱신된다.
    """

    id: int | None = None  # BIGSERIAL; None before first insert
    run_date: date | None = None
    is_trading_day: bool = False
    opnd_yn: str | None = None
    bzdy_yn: str | None = None
    tr_day_yn: str | None = None
    market_phase: str | None = None
    raw_opnd_yn: str | None = None
    raw_mkop_cls_code: str | None = None
    raw_antc_mkop_cls_code: str | None = None
    source: str = "unknown"
    reason_code: str | None = None
    reason: str | None = None
    reason_metadata: dict[str, object] | None = None
    checked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class SessionEventEntity:
    """장운영 phase 변경 이벤트 로그 엔티티 (append-only).

    ``id``는 ``BIGSERIAL`` (int), ``market_session_id``는
    ``MarketSessionEntity.id``를 참조하는 FK.
    """

    id: int | None = None  # BIGSERIAL; None before first insert
    market_session_id: int = 0
    previous_phase: str | None = None
    new_phase: str = ""
    trigger_source: str | None = None
    metadata: dict[str, object] | None = None
    occurred_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class ExecutionAttemptEntity:
    """각 trade_decision의 1회 실행 시도를 추적.

    의사결정(trade_decisions)과 실행 흐름(phase progression, order 생성/제출)을
    명시적으로 분리한다. Phase 3 도입.

    상태 모델 (6개 값):
        running → submitted / failed / reconcile_required / non_trade / stopped
    """
    execution_attempt_id: UUID
    trade_decision_id: UUID
    decision_context_id: UUID
    status: str
    started_at: datetime
    stop_phase: str | None = None
    stop_reason: str | None = None
    phase_trace: list[dict[str, object]] | None = None
    order_request_id: UUID | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class OrderSubmissionAttemptEntity:
    """Record of a single broker submission attempt.

    Captures success, rejection, and exception paths so that
    submission history is never lost across retries or fallback
    strategies.  MVP uses ``attempt_number=1``;  the value may
    later be computed via COUNT queries.
    """

    attempt_id: UUID
    order_request_id: UUID
    attempt_number: int
    submitted_at: datetime
    broker_name: str | None = None
    accepted: bool = False
    broker_native_order_id: str | None = None
    broker_status: str | None = None
    raw_code: str | None = None
    raw_message: str | None = None
    error_type: str | None = None
    retryable: bool | None = None
    http_status: int | None = None
    request_payload_uri: str | None = None
    response_payload_uri: str | None = None
    duration_ms: int | None = None
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
