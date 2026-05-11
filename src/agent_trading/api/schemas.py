"""Pydantic response models for the FastAPI inspection API (Phase 1).

These are minimal **read models** — not 1:1 mirrors of domain entities.
``pydantic`` v2 handles common type coercions automatically
(``UUID`` → ``str``, ``Decimal`` → ``float``, ``Enum`` → ``str``).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Enum Metadata schemas (Phase 2b — reusable enum field metadata)
# ---------------------------------------------------------------------------


class EnumValueMetadataSchema(BaseModel):
    """A single enum value with its display label and optional broker code."""

    value: str
    """Canonical enum value (matches ``enums.py``)."""

    label: str
    """Human-readable display label (e.g. ``"지정가"``)."""

    description: str | None = None
    """Optional explanation, especially for unsupported values."""

    broker_code: str | None = None
    """Broker-specific code for display reference only.

    .. note::

       This is **not** the authoritative submit mapping.  The actual
       ``ORD_DVSN`` code sent to KIS is determined by
       ``KISRestClient._map_order_type()``.
    """

    supported: bool = True
    """``True`` when the value is actively supported by the broker adapter."""


class EnumFieldMetadataSchema(BaseModel):
    """Metadata for an entire enum field."""

    field: str
    """API field name (e.g. ``"order_type"``)."""

    type: str = "enum"
    """Metadata type discriminator (reserved for future use)."""

    values: list[EnumValueMetadataSchema]
    """All possible values for this field."""


class EnumMetadataListResponse(BaseModel):
    """``GET /metadata/enums`` — all registered enum field metadata."""

    fields: list[EnumFieldMetadataSchema]
    """List of enum field metadata entries."""


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """``GET /health`` — minimal server status + optional snapshot sync freshness."""

    status: str = "ok"
    version: str
    timestamp: datetime
    database: str
    runtime_mode: str

    # ── Snapshot Sync Freshness (optional — added when repos are accessible) ──
    snapshot_sync_detail: str | None = None
    """One of ``"ok"``, ``"stale"``, ``"no_history"``, or ``None`` (unavailable)."""

    snapshot_sync_stale: bool | None = None
    """``True`` when the most recent successful sync exceeds the stale threshold."""

    snapshot_sync_last_successful_run_at: datetime | None = None
    """``started_at`` of the most recent successful (``completed``) sync run."""

    snapshot_sync_consecutive_failures: int | None = None
    """Number of consecutive ``status == 'failed'`` runs (reverse chronological)."""


class OrderSummary(BaseModel):
    """``GET /orders`` list item — inspection-purpose subset."""

    model_config = ConfigDict(from_attributes=True)

    order_request_id: str
    client_order_id: str
    account_id: str
    side: str
    order_type: str
    status: str
    requested_quantity: float
    requested_price: float | None = None
    symbol: str | None = None
    correlation_id: str
    trade_decision_id: str | None = None
    decision_context_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int


class OrderDetail(OrderSummary):
    """``GET /orders/{id}`` — summary + decision tracing fields."""

    instrument_id: str | None = None
    status_reason_code: str | None = None
    status_reason_message: str | None = None
    submitted_at: datetime | None = None
    time_in_force: str | None = None


class OrderEvent(BaseModel):
    """``GET /orders/{id}/events`` — order state transition event."""

    order_state_event_id: str
    previous_status: str | None = None
    new_status: str
    event_source: str
    event_timestamp: datetime
    reason_code: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None


class AuditLogEntry(BaseModel):
    """``GET /audit-logs`` — minimal audit log entry."""

    audit_log_id: str
    actor_type: str
    actor_id: str
    action: str
    target_entity_type: str
    target_entity_id: str
    created_at: datetime
    correlation_id: str | None = None
    before_json: dict[str, object] | None = None
    after_json: dict[str, object] | None = None


class ReconciliationRunSummary(BaseModel):
    """``GET /reconciliation/runs`` — reconciliation run summary."""

    reconciliation_run_id: str
    account_id: str
    trigger_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    mismatch_count: int = 0


class SnapshotSyncRunSummary(BaseModel):
    """``GET /snapshot-sync-runs`` — KIS snapshot sync run summary."""

    snapshot_sync_run_id: str
    trigger_type: str
    scope: str
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
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    env_filter: str | None = None
    status_filter: str | None = None
    summary_json: dict[str, object] | None = None


class SnapshotSyncRunHealthSummary(BaseModel):
    """``GET /snapshot-sync-runs/summary`` — KIS snapshot sync freshness/health summary."""

    last_run_started_at: datetime | None = None
    """``started_at`` of the most recent run, or ``None`` if no runs exist."""

    last_run_completed_at: datetime | None = None
    """``completed_at`` of the most recent run, or ``None`` if no runs exist."""

    last_status: str | None = None
    """``status`` of the most recent run (e.g. ``"completed"``, ``"failed"``)."""

    last_successful_run_at: datetime | None = None
    """``started_at`` of the most recent ``status == 'completed'`` run."""

    consecutive_failures: int = 0
    """Number of consecutive ``status == 'failed'`` runs (reverse chronological)."""

    is_stale: bool = True
    """``True`` when the most recent successful run exceeds the stale threshold."""

    stale_threshold_seconds: int = 900
    """The threshold used for staleness computation."""


class BlockingLockStatus(BaseModel):
    """``GET /reconciliation/locks`` — blocking lock status."""

    lock_id: str
    account_id: str
    strategy_id: str | None = None
    symbol: str | None = None
    side: str | None = None
    reason: str
    locked_by_run_id: str
    locked_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool = True


class ReconciliationSummary(BaseModel):
    """``GET /reconciliation/summary`` — aggregate reconciliation summary."""

    active_locks_count: int
    incomplete_recon_count: int
    recent_active_locks: list[BlockingLockStatus]
    recent_incomplete_runs: list[ReconciliationRunSummary]
    generated_at: datetime


class DecisionContextDetail(BaseModel):
    """``GET /decision-contexts/{id}`` — decision context detail."""

    decision_context_id: str
    account_id: str
    strategy_id: str
    config_version_id: str
    market_timestamp: datetime
    correlation_id: str
    trading_session_id: str | None = None
    created_at: datetime | None = None


class TradeDecisionDetail(BaseModel):
    """``GET /trade-decisions`` — trade decision detail."""

    trade_decision_id: str
    decision_context_id: str
    decision_type: str
    side: str
    strategy_id: str
    symbol: str
    market: str
    entry_style: str
    created_at: datetime
    entry_price: float | None = None
    quantity: float | None = None
    max_order_value: float | None = None
    confidence: float | None = None
    rationale_summary: str | None = None


# ── Phase 2: Account, Client, Instrument, Position, Cash-balance, Broker-order ──


class AccountSummary(BaseModel):
    """``GET /accounts`` / ``GET /accounts/{id}`` — account info."""

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    client_id: UUID
    broker_account_id: UUID
    account_alias: str | None = None
    account_masked: str | None = None
    broker_account_ref: str | None = None
    broker_account_code: str | None = None
    account_code: str | None = None
    environment: str
    status: str
    risk_profile: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ClientDetail(BaseModel):
    """``GET /clients/{id}`` — client info."""

    model_config = ConfigDict(from_attributes=True)

    client_id: UUID
    client_code: str
    name: str
    status: str
    base_currency: str
    created_at: datetime
    updated_at: datetime | None = None


class InstrumentDetail(BaseModel):
    """``GET /instruments/{id}`` — instrument info."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID
    symbol: str
    market_code: str
    asset_class: str
    currency: str
    name: str
    tick_size: float | None = None
    lot_size: float | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None


class PositionSnapshotView(BaseModel):
    """``GET /positions`` — point-in-time position snapshot.

    .. note::

       This is a **snapshot** — not the current live position.  The
       repository returns all position snapshots for the account ordered
       by ``snapshot_at`` descending.  Use ``snapshot_at`` to identify
       the most recent observation.
    """

    model_config = ConfigDict(from_attributes=True)

    position_snapshot_id: UUID
    account_id: UUID
    instrument_id: UUID
    quantity: float
    average_price: float
    market_price: float
    unrealized_pnl: float | None = None
    source_of_truth: str
    snapshot_at: datetime
    created_at: datetime


class CashBalanceSnapshotView(BaseModel):
    """``GET /cash-balances`` — latest cash balance snapshot.

    .. note::

       Returns ``null`` when no snapshot exists for the given account.
       This is **not** an error — the account may not have been funded
       or no snapshot has been recorded yet.
    """

    model_config = ConfigDict(from_attributes=True)

    cash_balance_snapshot_id: UUID
    account_id: UUID
    currency: str
    available_cash: float
    settled_cash: float | None
    unsettled_cash: float | None
    source_of_truth: str
    snapshot_at: datetime
    created_at: datetime


class BrokerOrderView(BaseModel):
    """``GET /orders/{id}/broker-orders`` — broker-side order reference.

    Inspection‑friendly subset of ``BrokerOrderEntity`` fields.
    """

    model_config = ConfigDict(from_attributes=True)

    broker_order_id: UUID
    order_request_id: UUID
    broker_name: str
    broker_status: str
    broker_native_order_id: str | None = None
    request_payload_uri: str | None = None
    response_payload_uri: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class AgentRunResponse(BaseModel):
    """``GET /agent-runs`` — AI Agent execution run record.

    Inspection‑friendly subset of ``AgentRunEntity`` fields.
    """

    model_config = ConfigDict(from_attributes=True)

    agent_run_id: UUID
    decision_context_id: UUID
    agent_type: str
    started_at: datetime
    model_id: UUID | None = None
    prompt_id: UUID | None = None
    temperature: float | None = None
    seed: int | None = None
    raw_output_uri: str | None = None
    structured_output_json: dict[str, object] | None = None
    status: str = "completed"
    completed_at: datetime | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Broker Capacity Inspection (Phase 2)
# ---------------------------------------------------------------------------


class BucketSnapshot(BaseModel):
    """Token-bucket state for a single operation type.

    Returned as a dict entry inside ``BrokerCapacityResponse.rest_budget``.
    """

    remaining: float
    capacity: float
    refill_rate: float
    utilization: float


class WsSubscriptionSnapshot(BaseModel):
    """WebSocket subscription budget state."""

    max_subscriptions: int
    critical_limit: int
    optional_limit: int
    current_critical: int
    current_optional: int
    total_used: int
    remaining: int
    ws_connected: bool = False


class BrokerCapacityResponse(BaseModel):
    """``GET /broker-capacity`` — REST + WebSocket broker capacity overview.

    Read‑only snapshot of the active broker adapter's rate limit budgets
    and WebSocket subscription state.  No enforcement logic is triggered.
    """

    broker_name: str
    environment: str
    rest_budget: dict[str, BucketSnapshot]
    can_accept_new_entries: bool
    websocket: WsSubscriptionSnapshot
    market_data_subscriptions: int
    order_event_accounts: list[str]
    generated_at: datetime


class AccountPerformanceSummaryView(BaseModel):
    """``GET /performance-summary`` — paper 운용 성과 요약 (계좌 수준)."""

    model_config = ConfigDict(from_attributes=True)

    account_id: str
    as_of: datetime
    cash_balance: float
    position_market_value: float
    total_equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    filled_order_count: int
    open_position_count: int
    winning_trade_count: int
    losing_trade_count: int


class StrategyPerformanceSummaryView(BaseModel):
    """``GET /performance-summary?strategy_id=...`` — 전략 수준 성과 요약."""

    model_config = ConfigDict(from_attributes=True)

    account_id: str
    strategy_id: str
    as_of: datetime
    realized_pnl: float
    filled_order_count: int
    winning_trade_count: int
    losing_trade_count: int


class DailyPerformancePointView(BaseModel):
    """``GET /performance-history`` 응답의 단일 일별 성과 포인트."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    realized_pnl: float
    cumulative_realized_pnl: float
    cash_balance: float | None
    position_market_value: float | None
    unrealized_pnl: float | None
    total_equity: float | None


class PerformanceHistoryResponse(BaseModel):
    """``GET /performance-history`` — 기간 필터 기반 일별 성과 히스토리."""

    account_id: str
    start_date: date
    end_date: date
    strategy_id: str | None
    points: list[DailyPerformancePointView]


class PerformanceMetricsView(BaseModel):
    """``GET /performance-metrics`` — 기간 기반 성과 지표.

    cumulative return, drawdown, win-rate, avg win-loss 등
    paper 운용 성과 평가를 위한 핵심 지표를 반환합니다.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    strategy_id: UUID | None
    period_start: date
    period_end: date

    starting_equity: float
    current_equity: float
    cumulative_realized_pnl: float
    cumulative_return_pct: float

    peak_equity: float
    current_drawdown_pct: float
    max_drawdown_pct: float

    total_filled_orders: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float | None
    avg_loss: float | None
    profit_factor: float | None

    # ── 위험 조정 수익률 (Risk-Adjusted Return Metrics) ──
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None

    # ── Explanation / Status Fields (gate-facing, additive only) ──
    sharpe_ratio_status: str
    """``ok`` | ``insufficient_data`` | ``zero_variance``"""
    sharpe_ratio_note: str
    """한국어 설명 메시지."""

    sortino_ratio_status: str
    """``ok`` | ``insufficient_data`` | ``insufficient_downside_samples`` | ``zero_variance``"""
    sortino_ratio_note: str
    """한국어 설명 메시지."""

    calmar_ratio_status: str
    """``ok`` | ``zero_drawdown``"""
    calmar_ratio_note: str
    """한국어 설명 메시지."""


class BenchmarkComparisonView(BaseModel):
    """``GET /performance-benchmark`` — 계좌/전략 성과와 benchmark 지수 간 초과수익 비교.

    portfolio metrics는 ``PerformanceMetricsView``의 cumulative_return_pct와
    max_drawdown_pct를 그대로 사용합니다. benchmark metrics는
    ``_calc_benchmark_metrics()``로 일별 종가 시리즈에서 계산합니다.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: str
    strategy_id: str | None
    benchmark_code: str
    period_start: date
    period_end: date

    # -- Portfolio (from existing PerformanceMetrics) --
    portfolio_return_pct: float
    benchmark_return_pct: float
    excess_return_pct: float

    # -- Drawdown --
    portfolio_max_drawdown_pct: float
    benchmark_max_drawdown_pct: float | None
    relative_drawdown_pct: float | None

    # -- Volatility (reserved, always None in this iteration) --
    portfolio_volatility_pct: float | None = None
    benchmark_volatility_pct: float | None = None


# ---------------------------------------------------------------------------
# Benchmark Daily Relative Trend
# ---------------------------------------------------------------------------


class RelativeBenchmarkPointView(BaseModel):
    """``GET /performance-benchmark-history`` 응답의 단일 일별 상대 성과 포인트.

    All return/drawdown values are in **percentage points** (e.g. 3.5 means
    3.5 %).  ``None`` indicates the value could not be calculated (missing
    data — no interpolation is performed).
    """

    model_config = ConfigDict(from_attributes=True)

    date: date
    portfolio_return_pct: float | None
    benchmark_return_pct: float | None
    excess_return_pct: float | None
    portfolio_drawdown_pct: float | None
    benchmark_drawdown_pct: float | None
    relative_drawdown_pct: float | None
    outperformance_streak: int
    benchmark_data_available: bool


class BenchmarkHistoryResponse(BaseModel):
    """``GET /performance-benchmark-history`` — 기간 필터 기반 일별 상대 성과 히스토리.

    Portfolio와 benchmark 지수 간 일별 누적 수익률, drawdown, outperformance
    streak을 시계열로 반환합니다.

    ``total_days``는 ``points`` 개수와 동일하며, ``start_date~end_date``의
    캘린더 일수가 아닙니다. date coverage는 **Data-date Union** 정책을 따릅니다
    (portfolio/benchmark 데이터가 있는 날짜의 합집합).
    """

    account_id: str
    start_date: date
    end_date: date
    strategy_id: str | None
    benchmark_code: str
    total_days: int
    points: list[RelativeBenchmarkPointView]


class PaperGateCheckView(BaseModel):
    """Individual gate criterion check result.

    Serialises ``measured_value`` and ``threshold`` as ``str`` to support
    both ``Decimal`` and ``int`` threshold types uniformly.
    """

    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    status: str  # PASS / WARN / FAIL
    measured_value: str | None
    threshold: str | None
    message: str
    reason_code: str | None = None


class PaperGoNoGoEvaluationView(BaseModel):
    """``GET /paper-go-no-go`` — Paper Go/No-Go Gate evaluation result.

    Aggregates individual checks across performance, stability and
    operational-health axes into a single ``GO`` / ``HOLD`` / ``NO_GO``
    overall status.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: str
    strategy_id: str | None
    overall_status: str  # GO / HOLD / NO_GO
    checks: list[PaperGateCheckView]
    generated_at: datetime
    summary_reason: str
    # --- 신규: reason_code 요약 집계 (read-only additive) ---
    reason_code_counts: dict[str, int] = {}
    warn_reason_codes: list[str] = []
    fail_reason_codes: list[str] = []
    display_only_count: int = 0


class GuardrailEvaluationView(BaseModel):
    """``GET /guardrail-evaluations`` — guardrail rule evaluation result.

    Represents the result of a single guardrail evaluation against a
    decision, order, or both.  Each evaluation records which rules were
    checked, their results, and whether the overall check passed.
    """

    model_config = ConfigDict(from_attributes=True)

    guardrail_evaluation_id: UUID
    rule_set_version: str
    overall_passed: bool
    evaluated_at: datetime
    decision_context_id: UUID | None = None
    trade_decision_id: UUID | None = None
    order_request_id: UUID | None = None
    rule_results: dict[str, object] = {}
    blocking_rule_codes: list[str] | None = None
    warning_rule_codes: list[str] | None = None
    created_at: datetime | None = None


class RiskLimitSnapshotView(BaseModel):
    """``GET /risk-limit-snapshots`` — point-in-time risk limit snapshot.

    Captures NAV, cash, exposure, P&L, drawdown state, and kill-switch
    status for an account at a given point in time.
    """

    model_config = ConfigDict(from_attributes=True)

    risk_limit_snapshot_id: UUID
    account_id: UUID
    snapshot_at: datetime
    nav: float | None = None
    cash_available: float | None = None
    gross_exposure_pct: float | None = None
    net_exposure_pct: float | None = None
    daily_realized_pnl: float | None = None
    daily_unrealized_pnl: float | None = None
    daily_loss_used_pct: float | None = None
    max_daily_loss_limit_pct: float | None = None
    symbol_exposure_json: dict[str, object] = {}
    sector_exposure_json: dict[str, object] = {}
    open_order_exposure_json: dict[str, object] = {}
    drawdown_state: str | None = None
    kill_switch_active: bool = False
    blocked_reason_codes: list[str] | None = None
    created_at: datetime | None = None
