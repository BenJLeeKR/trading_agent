"""Pydantic response models for the FastAPI inspection API (Phase 1).

These are minimal **read models** — not 1:1 mirrors of domain entities.
``pydantic`` v2 handles common type coercions automatically
(``UUID`` → ``str``, ``Decimal`` → ``float``, ``Enum`` → ``str``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_trading.domain.enums import OrderStatus


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


class SchedulerHealth(BaseModel):
    """Scheduler freshness information embedded in ``/health`` response."""

    last_heartbeat_at: datetime | None = None
    """Most recent heartbeat timestamp from the ops-scheduler."""

    is_trading_day: bool | None = None
    """Whether the current market session is a trading day."""

    checked_at: datetime | None = None
    """When the market session was last checked."""

    phase: str | None = None
    """Current market phase (e.g. ``after_hours``, ``idle``, ``intraday``)."""

    healthy: bool | None = None
    """Derived health: True if heartbeat is recent (for trading days) or session
    is fresh (for non-trading days)."""


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

    # ── Scheduler Freshness (optional — queried from market_sessions table) ──
    scheduler: SchedulerHealth | None = None
    """Scheduler heartbeat and trading day information."""


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
    instrument_name: str | None = None
    """Human-readable instrument name (e.g. ``Samsung Electronics``)."""
    filled_quantity: float | None = None
    avg_fill_price: float | None = None
    fill_amount: float | None = None
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

    # 신규: submission attempts 요약 (Phase 7)
    submission_attempt_summary: SubmissionAttemptSummary | None = None
    linked_fill_snapshot_summary: LinkedFillSnapshotSummary | None = None


class OrderDailySummaryResponse(BaseModel):
    """KST 기준 일별 주문 집계 요약."""

    date: date
    timezone: str = "Asia/Seoul"
    total_count: int
    filled_count: int
    pending_submit_count: int
    submitted_count: int


class BuyBlockSummaryResponse(BaseModel):
    """KST 기준 일별 BUY 브로커 제출 실패 요약."""

    date: date
    timezone: str = "Asia/Seoul"
    total_buy_orders_count: int
    buy_submission_attempted_count: int
    blocked_count: int
    rejected_count: int
    exception_count: int


class TruthProbePendingOrderItem(BaseModel):
    """`truth_probe_fill_snapshot_incomplete`가 걸린 주문의 최근 항목."""

    order_request_id: str
    symbol: str | None = None
    side: str
    status: str
    requested_quantity: float
    trade_decision_id: str | None = None
    broker_native_order_id: str | None = None
    status_reason_code: str | None = None
    status_reason_message: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TruthProbePendingSummaryResponse(BaseModel):
    """KST 기준 일별 fill snapshot incomplete 대기 주문 집계."""

    date: date
    timezone: str = "Asia/Seoul"
    reason_code: str = "truth_probe_fill_snapshot_incomplete"
    total_count: int
    status_counts: dict[str, int]
    recent_orders: list[TruthProbePendingOrderItem]


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
    is_active: bool = False
    """``True`` if running, or failed/partial with unresolved (non-terminal) orders."""
    failure_reason: str | None = None
    """분류된 실패 사유 label (historical failed run에만 설정)."""
    summary_error: str | None = None
    """``summary_json.error`` 원문 (historical failed run의 상세 오류 메시지)."""
    order_count: int = 0
    """이 run에 연결된 order link 수."""


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
    after_hours: bool = False
    """Whether this sync was an after-hours cash-only run."""
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

    after_hours: bool = False
    """``True`` when the most recent run was an after-hours (cash-only) sync."""


class FillSyncRunSummary(BaseModel):
    fill_sync_run_id: str
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
    completed_at: datetime | None = None
    env_filter: str | None = None
    summary_json: dict[str, object] | None = None


class FillSyncRunHealthSummary(BaseModel):
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_status: str | None = None
    last_successful_run_at: datetime | None = None
    consecutive_failures: int = 0
    is_stale: bool = True
    stale_threshold_seconds: int = 1800
    retried_accounts: int = 0
    retried_days: int = 0
    total_retries: int = 0


class FillHistoryItem(BaseModel):
    broker_fill_snapshot_id: str
    fill_sync_run_id: str | None = None
    account_id: str
    order_request_id: str | None = None
    trade_decision_id: str | None = None
    account_alias: str | None = None
    account_code: str | None = None
    broker_name: str
    broker_native_order_id: str
    broker_fill_id: str | None = None
    symbol: str
    instrument_name: str | None = None
    side: str
    order_date: date
    order_status_code: str | None = None
    cancel_yn: str | None = None
    ordered_quantity: float | None = None
    filled_quantity: float
    fill_price: float
    order_time: str | None = None
    fill_time: str | None = None
    fill_timestamp: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LinkedFillSnapshotSummary(BaseModel):
    snapshot_count: int
    broker_native_order_id: str
    symbol: str
    side: str
    latest_fill_timestamp: datetime | None = None
    latest_filled_quantity: float
    max_filled_quantity: float
    latest_fill_price: float
    latest_ordered_quantity: float | None = None
    latest_order_status_code: str | None = None


class BlockingLockStatus(BaseModel):
    """``GET /reconciliation/locks`` — blocking lock status."""

    lock_id: str
    account_id: str
    strategy_id: str | None = None
    symbol: str | None = None
    instrument_name: str | None = None
    """Human-readable instrument name (e.g. ``Samsung Electronics``)."""
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
    active_issue_count: int = 0
    """Number of currently active reconciliation issues (running + unresolved failed/partial)."""
    historical_failed_count: int = 0
    """Number of historical failed/partial runs that are no longer active (is_active=false)."""
    recent_active_issues: list[ReconciliationRunSummary] = Field(default_factory=list)
    """Recent active-issue runs (running or unresolved failed/partial)."""


class DecisionContextDetail(BaseModel):
    """``GET /decision-contexts/{id}`` — decision context detail."""

    decision_context_id: str
    account_id: str
    strategy_id: str
    config_version_id: str
    market_timestamp: datetime
    correlation_id: str
    trading_session_id: str | None = None
    signal_feature_snapshot_id: str | None = None
    created_at: datetime | None = None


def _split_phase(phase: str | None) -> tuple[str | None, str | None]:
    """복합 phase 문자열(예: "broker_submit/AAPL")을 (phase, detail)로 분할합니다.

    Returns:
        (phase, detail) 튜플. "/" 구분자가 없으면 detail은 None.
        입력이 None이거나 빈 문자열이면 (None, None) 반환.
    """
    if not phase:
        return (None, None)
    if "/" in phase:
        parts = phase.split("/", 1)
        return (parts[0], parts[1])
    return (phase, None)


def _map_attempt_status_to_execution_status(attempt_status: str) -> str:
    """Map ``ExecutionAttemptEntity.status`` → ``execution_status`` string.

    **Mapping**:

    ====================  ======================
    ``attempt_status``    ``execution_status``
    ====================  ======================
    ``running``           ``pipeline_stopped``
    ``stopped``           ``pipeline_stopped``
    ``submitted``         ``submitted``
    ``failed``            ``rejected``
    ``non_trade``         ``non_trade``
    ``reconcile_required`` ``reconcile_required``
    ====================  ======================
    """
    mapping: dict[str, str] = {
        "running": "pipeline_stopped",
        "stopped": "pipeline_stopped",
        "submitted": "submitted",
        "failed": "rejected",
        "non_trade": "non_trade",
        "reconcile_required": "reconcile_required",
    }
    return mapping.get(attempt_status, "pipeline_stopped")


class TradeDecisionDetail(BaseModel):
    """``GET /trade-decisions`` — trade decision detail."""

    trade_decision_id: str
    decision_context_id: str
    decision_type: str
    side: str
    strategy_id: str
    symbol: str
    instrument_name: str | None = None
    """Human-readable instrument name (e.g. ``Samsung Electronics``)."""
    market: str
    entry_style: str
    created_at: datetime
    entry_price: float | None = None
    quantity: float | None = None
    max_order_value: float | None = None
    confidence: float | None = None
    rationale_summary: str | None = None
    source_type: str | None = None
    """Origin of this symbol: ``"core"`` | ``"held_position"`` | ``"event_overlay"`` | ``"market_overlay"`` | ``"manual"``."""
    signal_feature_snapshot_id: str | None = None
    """Point-in-time anchor of the signal feature snapshot used by this decision."""
    decision_json: dict[str, object] | None = None
    """Raw decision payload from EI/AR agents (``event_bias``, ``risk_opinion``, etc.)."""
    decision_inspection: dict[str, object] | None = None
    """운영용 요약 inspection view.

    `holding_profile`, `expected_value_anchor`,
    `reverse_trade`, `probe_churn`, `guardrail_attribution`
    를 읽기 쉬운 구조로 정규화한 payload.
    """
    compliance_inspection: dict[str, object] | None = None
    """AI Compliance projection과 deterministic compliance validator 결과를 합본한 inspection view."""

    # ── Pipeline stop / order exposure (Phase 1) ──
    order_request_id: str | None = None
    """Order request ID resolved via LEFT JOIN on trade_decision_id."""
    order_status: str | None = None
    """Order status from the order_requests table."""

    # ── Execution Attempt status (P2: LEFT JOIN LATERAL from execution_attempts) ──
    execution_attempt_status: str | None = None
    """Status of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet (Phase 3 backfill / pre-P3 data).
    When present, this is the **primary** source for ``execution_status``.
    """

    # ── Latest execution attempt summary (Phase 5: LEFT JOIN LATERAL 확장) ──
    latest_execution_attempt_id: str | None = None
    """ID of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_stop_phase: str | None = None
    """Stop phase of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_stop_reason: str | None = None
    """Stop reason of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_completed_at: datetime | None = None
    """Completed-at timestamp of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_phase_count: int | None = None
    """Number of phases in the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` (``jsonb_array_length(ea.phase_trace)``).

    ``None`` when no execution attempt exists yet.
    """

    # ── Phase trace (from execution_attempts LEFT JOIN LATERAL, NOT from bridge) ──
    phase_trace: list[dict[str, object]] | None = None
    """Raw phase trace JSON list (from ``execution_attempts.phase_trace``).
    Each entry: ``{"phase": str, "elapsed_ms": int, "status": str}``.
    ``None`` when no execution attempt exists yet.
    """

    # ── Phase trace summary (computed from phase_trace, NOT stored) ──
    phase_count: int | None = None
    """총 phase 수 (phase_trace에서 계산, DB 저장 안 함)."""
    total_elapsed_ms: int | None = None
    """총 소요 시간(ms), non-start entry ``elapsed_ms`` 합계 (phase_trace에서 계산, DB 저장 안 함)."""
    latest_phase: str | None = None
    """마지막 entry의 phase 키 (예: ``"broker_submit"``). phase/detail 분리. (phase_trace에서 계산, DB 저장 안 함)."""
    latest_phase_detail: str | None = None
    """마지막 entry의 리소스 상세 (예: ``"AAPL"``). 없으면 ``None``. (phase_trace에서 계산, DB 저장 안 함)."""
    latest_status: str | None = None
    """마지막 entry의 status (예: ``"ok"``). (phase_trace에서 계산, DB 저장 안 함)."""

    # ── Derived field (computed by model_validator) ──
    execution_status: str | None = None
    """Derived execution status.

    **Priority (P2: execution_attempt_status 가 primary truth가 됨):**

    1. ``execution_attempt_status`` 가 존재하면 → ``_map_attempt_status_to_execution_status()``
    2. 그 외 fallback (P3 이전 데이터):
       - ``order_request_id`` + ``order_status`` → ``submitted`` / ``rejected`` / ``order_created``
       - ``decision_type`` HOLD/WATCH → ``non_trade``
       - 그 외 → ``trade_decision_only``
    """

    @model_validator(mode='after')
    def _compute_execution_status(self) -> 'TradeDecisionDetail':
        # Primary: execution_attempt_status (P2, LEFT JOIN LATERAL)
        if self.execution_attempt_status is not None:
            self.execution_status = _map_attempt_status_to_execution_status(
                self.execution_attempt_status
            )
        # Fallback: P3 이전 데이터 (execution_attempts 테이블이 없던 시기)
        elif self.order_request_id is not None:
            if self.order_status in ('SUBMITTED', 'REJECTED', 'RECONCILE_REQUIRED'):
                self.execution_status = self.order_status.lower()
            else:
                self.execution_status = 'order_created'
        elif (self.decision_type or "").upper() in ('HOLD', 'WATCH'):
            self.execution_status = 'non_trade'
        else:
            self.execution_status = 'trade_decision_only'

        # ── Phase trace summary (Phase 2/6: phase_trace에서 계산, DB 저장 안 함) ──
        if self.phase_trace:
            self.phase_count = len(self.phase_trace)
            # total_elapsed_ms = 모든 non-start entry의 elapsed_ms 합계
            non_start = [e for e in self.phase_trace if e.get("status") != "start"]
            self.total_elapsed_ms = sum(
                e.get("elapsed_ms", 0) or 0 for e in non_start
            ) if non_start else 0
            # 마지막 entry에서 phase/detail 분리
            last_entry = self.phase_trace[-1]
            raw_phase = last_entry.get("phase", "") if isinstance(last_entry, dict) else ""
            if "/" in raw_phase:
                parts = raw_phase.split("/", 1)
                self.latest_phase = parts[0]
                self.latest_phase_detail = parts[1]
            else:
                self.latest_phase = raw_phase or None
                self.latest_phase_detail = None
            self.latest_status = last_entry.get("status") if isinstance(last_entry, dict) else None
        elif self.phase_trace is not None and len(self.phase_trace) == 0:
            # 빈 리스트는 None과 동일하게 처리
            pass  # 모든 derived field는 기본값 None 유지

        return self


class PaginatedTradeDecisionsResponse(BaseModel):
    """``GET /trade-decisions`` — paginated response wrapper."""

    items: list[TradeDecisionDetail]
    """현재 페이지의 trade decision 목록."""
    total: int
    """조건에 맞는 전체 trade decision 수 (페이지네이션 UI용)."""
    limit: int
    """요청된 페이지 크기."""
    offset: int
    """요청된 오프셋."""


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


class InstrumentMappingGapItem(BaseModel):
    """최근 운영 데이터에서 instrument master에 없는 symbol 요약."""

    symbol: str
    occurrence_count: int
    latest_observed_at: datetime


class InstrumentMappingConsistencySummaryResponse(BaseModel):
    """`GET /instruments/mapping-consistency/summary` 응답."""

    lookback_days: int
    timezone: str = "Asia/Seoul"
    active_instrument_count: int
    has_gap: bool
    total_unmapped_external_event_symbols: int
    total_unmapped_broker_fill_symbols: int
    total_unmapped_snapshot_position_symbols: int
    unmapped_external_event_symbols: list[InstrumentMappingGapItem]
    unmapped_broker_fill_symbols: list[InstrumentMappingGapItem]
    unmapped_snapshot_position_symbols: list[InstrumentMappingGapItem]


class TradingUniversePreviewItem(BaseModel):
    """A single selected symbol from the current trading universe preview."""

    symbol: str
    market: str
    source_type: str
    inclusion_reason: str
    priority: int


class TradingUniverseFreezeView(BaseModel):
    """Active intraday freeze view for ops inspection."""

    universe_freeze_run_id: UUID
    freeze_purpose: str
    business_date: date
    frozen_at: datetime
    selection_version: str | None = None
    target_count: int
    source_type_counts: dict[str, int]
    inclusion_reason_counts: dict[str, int]
    items: list[TradingUniversePreviewItem]


class TradingUniverseFreezeComparisonView(BaseModel):
    """Live compose vs active intraday freeze comparison summary."""

    exact_match: bool
    live_total_count: int
    freeze_total_count: int
    common_symbol_count: int
    live_only_symbols: list[str]
    freeze_only_symbols: list[str]


class MarketOverlayDiagnosticsView(BaseModel):
    """Operational diagnostics for the market overlay branch."""

    enabled: bool
    skipped_reason: str | None = None
    seed_pool_source: str | None = None
    seed_pool_count: int
    effective_pre_pool_size: int
    pre_pool_candidate_count: int
    quotes_requested_count: int
    quotes_received_count: int
    filtered_out_count: int
    scored_candidate_count: int
    added_count: int
    quote_success_rate: float | None = None
    filter_pass_rate: float | None = None
    scored_capture_rate: float | None = None
    overlay_capture_rate: float | None = None


class TradingUniversePreviewResponse(BaseModel):
    """`GET /instruments/trading-universe/preview` 응답."""

    account_id: UUID
    lookback_hours: int
    max_cap: int
    core_cap: int | None = None
    exclude_held_from_cap: bool
    market_overlay_cap: int
    pre_pool_size: int
    kis_env: str | None = None
    total_count: int
    source_type_counts: dict[str, int]
    inclusion_reason_counts: dict[str, int]
    market_overlay_diagnostics: MarketOverlayDiagnosticsView
    items: list[TradingUniversePreviewItem]
    active_intraday_freeze: TradingUniverseFreezeView | None = None
    active_intraday_freeze_comparison: TradingUniverseFreezeComparisonView | None = None


class IndexMembershipStalenessResponse(BaseModel):
    """`GET /instruments/index-membership/staleness` 응답 (UNIV-4 read-only 감시)."""

    latest_effective_from: date | None = None
    as_of: date
    age_days: int | None = None
    threshold_days: int
    is_stale: bool


class TradingUniverseCoverageItem(BaseModel):
    """Source-type level operating coverage over a recent lookback window."""

    source_type: str
    decision_count: int
    order_count: int
    order_conversion_rate: float
    first_decision_at: datetime | None = None
    last_decision_at: datetime | None = None
    last_order_at: datetime | None = None


class TradingUniverseCoverageSummaryResponse(BaseModel):
    """`GET /instruments/trading-universe/coverage-summary` 응답."""

    lookback_days: int
    total_decision_count: int
    total_order_count: int
    market_overlay_active: bool
    market_counts: dict[str, int]
    items: list[TradingUniverseCoverageItem]


class MarketOverlayFunnelItem(BaseModel):
    """Recent `market_overlay` decision/order sample for ops inspection."""

    trade_decision_id: UUID
    symbol: str | None = None
    market: str | None = None
    decision_type: str | None = None
    side: str | None = None
    inclusion_reason: str | None = None
    rationale_summary: str | None = None
    created_at: datetime | None = None
    order_request_id: UUID | None = None
    order_status: str | None = None
    order_created_at: datetime | None = None


class MarketOverlayFunnelResponse(BaseModel):
    """`GET /instruments/trading-universe/market-overlay-funnel` 응답."""

    lookback_days: int
    sample_limit: int
    decision_count: int
    order_count: int
    order_conversion_rate: float
    decision_type_counts: dict[str, int]
    order_status_counts: dict[str, int]
    recent_items: list[MarketOverlayFunnelItem]


class WatchDiagnosticsSourceTypeItem(BaseModel):
    """Source-type level WATCH/HOLD distribution summary."""

    source_type: str
    decision_count: int
    watch_count: int
    hold_count: int
    watch_rate: float


class WatchDiagnosticsEvidenceStrengthItem(BaseModel):
    """Evidence-strength level WATCH/HOLD distribution summary."""

    evidence_strength: str
    decision_count: int
    watch_count: int
    hold_count: int
    watch_rate: float


class WatchDiagnosticsReasonCodeItem(BaseModel):
    """Top EI reason code frequency inside recent WATCH decisions."""

    reason_code: str
    decision_count: int


class WatchDiagnosticsSampleItem(BaseModel):
    """Recent WATCH/HOLD sample row for operator inspection."""

    trade_decision_id: UUID
    symbol: str | None = None
    market: str | None = None
    source_type: str | None = None
    decision_type: str | None = None
    evidence_strength: str | None = None
    no_material_events: bool | None = None
    detected_event_count: int | None = None
    interpreted_event_count: int | None = None
    event_bias: str | None = None
    rationale_summary: str | None = None
    created_at: datetime | None = None


class WatchDiagnosticsResponse(BaseModel):
    """`GET /trade-decisions/watch-diagnostics` 응답."""

    lookback_days: int
    sample_limit: int
    total_decision_count: int
    hold_count: int
    watch_count: int
    watch_rate: float
    no_material_events_watch_count: int
    no_material_events_hold_count: int
    source_type_items: list[WatchDiagnosticsSourceTypeItem]
    evidence_strength_items: list[WatchDiagnosticsEvidenceStrengthItem]
    top_watch_event_reason_codes: list[WatchDiagnosticsReasonCodeItem]
    recent_watch_items: list[WatchDiagnosticsSampleItem]


class LossCutShadowCountItem(BaseModel):
    """`source_type`/`decision_type` 등 카테고리별 관측 건수 1행."""

    key: str
    count: int


class LossCutShadowSummaryResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/summary` 응답.

    ``trade_decisions.decision_json.loss_cut_shadow``에 이미 기록된
    관측값을 그대로 집계한 것뿐이다 — 손실률/트리거 여부를 다시
    계산하지 않는다. shadow 관측은 실주문 결정에 개입하지 않으므로
    ``actual_decision_type_counts``는 shadow 판정과 무관하게 실제로
    내려진 결정의 분포다.
    """

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    triggered: bool | None = None
    total_observation_count: int
    triggered_count: int
    soft_trigger_count: int
    hard_trigger_count: int
    shadow_only_count: int
    """``loss_cut_shadow.shadow_only == true``인 건수 — 관측 전용이었음을
    보여주는 카운트(정상적으로는 전체 건수와 항상 같아야 한다)."""
    trigger_rate: float | None = None
    """``triggered_count / total_observation_count``. 표본이 0건이면
    ``None``."""
    source_type_counts: list[LossCutShadowCountItem]
    actual_decision_type_counts: list[LossCutShadowCountItem]


class LossCutShadowSampleView(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/samples`의 개별 관측 행."""

    model_config = ConfigDict(from_attributes=True)

    trade_decision_id: UUID
    decision_context_id: UUID
    account_id: UUID
    created_at: datetime
    symbol: str
    instrument_id: UUID | None = None
    source_type: str
    actual_decision_type: str
    average_price: Decimal | None = None
    market_price: Decimal | None = None
    loss_pct: Decimal | None = None
    triggered: bool | None = None
    tier: str | None = None
    skipped_reason: str | None = None
    shadow_only: bool | None = None


class LossCutShadowSamplesResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/samples` 응답."""

    account_id: UUID
    limit: int
    before: datetime | None = None
    items: list[LossCutShadowSampleView]


class LossCutShadowDailyItem(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/daily`의 날짜 1건 집계.

    ``summary``와 동일한 핵심 카운트만 담는다 — ``source_type_counts``/
    ``actual_decision_type_counts`` 같은 세부 분포는 날짜 수만큼
    응답이 커지는 것을 피하기 위해 이 항목에는 포함하지 않는다(특정
    날짜의 세부 분포가 필요하면 ``summary``를 그 날짜 하루로
    좁혀 호출하면 된다).
    """

    trade_date: date
    total_observation_count: int
    triggered_count: int
    soft_trigger_count: int
    hard_trigger_count: int
    shadow_only_count: int
    trigger_rate: float | None = None


class LossCutShadowDailyResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/daily` 응답.

    관측이 있었던 날짜만 ``days``에 나타난다(활동이 없는 날짜는
    포함하지 않는다 — ``realized-pnl/daily-summary``와 동일한 "빈
    상태" 원칙)."""

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    triggered: bool | None = None
    days: list[LossCutShadowDailyItem]


class LossCutShadowByInstrumentItem(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/by-instrument`의 종목 1건.

    ``shadow_triggered_count``/``latest_shadow_at``은 shadow 관측값을
    그대로 센 것이고, ``realized_pnl_net_sum``/``realized_sell_event_
    count``/``recompute_required``는 기존 realized PnL ledger를 그대로
    읽은 값이다(전체 기간 누계 — shadow 조회 기간에 종속되지 않는다).
    **이 두 값을 인과관계로 해석하지 않는다** — "이 shadow가 실제로
    손실을 막았다" 같은 결론은 이 API가 내리지 않는다. 나란히 놓인
    참고 정보일 뿐이다."""

    instrument_id: UUID
    symbol: str
    shadow_triggered_count: int
    soft_trigger_count: int
    hard_trigger_count: int
    latest_shadow_at: datetime
    realized_pnl_net_sum: Decimal
    realized_sell_event_count: int
    recompute_required: bool | None = None
    """``position_cost_basis_state``가 없으면 ``None``(포지션 이력이
    없거나 아직 한 번도 recompute 대상이 된 적 없는 종목)."""


class LossCutShadowByInstrumentResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/by-instrument` 응답.

    shadow가 **1건이라도 발동(``triggered=true``)**한 종목만
    ``items``에 나타난다 — 발동 이력이 없는 종목은 이 교차 조회의
    대상이 아니다."""

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    items: list[LossCutShadowByInstrumentItem]


class LossCutShadowTimelineSampleView(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/samples/{trade_decision_id}/timeline`

    응답의 shadow sample 부분 — `samples`의 개별 항목과 동일한 필드다."""

    trade_decision_id: UUID
    account_id: UUID
    decision_context_id: UUID
    symbol: str
    instrument_id: UUID | None = None
    created_at: datetime
    source_type: str
    actual_decision_type: str
    triggered: bool | None = None
    tier: str | None = None
    loss_pct: Decimal | None = None
    average_price: Decimal | None = None
    market_price: Decimal | None = None
    shadow_only: bool | None = None


class LossCutShadowTimelineRealizedEventView(BaseModel):
    """shadow sample 이후 같은 종목에서 실제로 발생한 realized PnL event 1건.

    ``realized_pnl_events``를 그대로 읽은 값이다 — 계산 없음.
    ``seconds_after_shadow``만 sample의 ``created_at``과의 단순
    시간차(뺄셈)이고, 그 외 판정/해석은 없다."""

    model_config = ConfigDict(from_attributes=True)

    realized_pnl_event_id: UUID
    fill_event_id: UUID
    fill_timestamp: datetime
    sell_quantity: Decimal
    sell_price: Decimal
    avg_cost_basis_before: Decimal
    realized_pnl_net: Decimal
    position_quantity_after: Decimal
    broker_order_id: UUID
    computation_run_id: UUID
    seconds_after_shadow: float
    """``(fill_timestamp - sample.created_at).total_seconds()``. 항상
    0 이상이다(``since=sample.created_at``으로 조회했으므로)."""


class LossCutShadowTimelineResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/samples/{trade_decision_id}/timeline` 응답.

    **후속 참고 타임라인이지 인과 매칭이 아니다.** ``realized_events``에
    담긴 이벤트가 이 shadow sample "때문에" 발생했다는 뜻이 아니다 —
    같은 계좌×종목에서 이 sample 시점 이후 실제로 기록된 realized
    event를 시간순으로 나열할 뿐이다. "이 shadow가 손실을 막았다/
    적중했다" 같은 판정은 이 응답에 없다.
    """

    sample: LossCutShadowTimelineSampleView
    realized_events: list[LossCutShadowTimelineRealizedEventView]
    realized_event_limit: int


class LossCutShadowFirstEventLatencyResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/first-realized-event-latency` 응답.

    **후속 사건 지연 분포이지 정책 효과 판정기가 아니다.** 각
    ``triggered=true`` shadow sample에 대해 같은 계좌×종목에서 그
    이후 가장 먼저 기록된 realized PnL event까지의 시간차
    (초 단위)를 모아 분포 통계만 낸 것이다. "이 shadow가 유효했다"/
    "손절 정책이 필요하다" 같은 결론을 이 응답이 내리지 않는다 —
    지연 시간이 길든 짧든 그 자체로 shadow의 적중/실패를 의미하지
    않는다(예: 청산 대신 보유를 지속했다가 다른 이유로 매도했을
    수도 있다).

    표본 자체가 인과적으로 매칭된 것도 아니다 — 각 sample 이후
    "가장 먼저 발생한" realized event일 뿐, 그 event가 이 sample
    때문에 발생했다는 보장은 없다(``timeline`` endpoint와 동일한
    한계).
    """

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    tier: str | None = None
    sample_count: int
    """``triggered=true``이고(``tier`` 필터가 있으면 그것도 만족하는)
    shadow sample 총 건수 — 분포 계산의 모집단."""
    matched_first_event_count: int
    missing_first_event_count: int
    missing_first_event_rate: float | None = None
    """``missing_first_event_count / sample_count``. ``sample_count``가
    0이면 ``None``."""
    latency_seconds_min: float | None = None
    latency_seconds_max: float | None = None
    latency_seconds_avg: float | None = None
    latency_seconds_median: float | None = None
    latency_seconds_p90: float | None = None
    """지연 통계는 ``matched_first_event_count`` 표본 위에서만
    계산된다(0건이면 전부 ``None``). 표본이 1~2건뿐이면 ``p90``이
    ``max``와 같거나 근접해 통계적으로 큰 의미가 없을 수 있다 —
    해석은 표본 크기를 함께 확인한 사람이 해야 한다."""
    first_realized_event_pnl_net_avg: Decimal | None = None
    first_realized_event_pnl_net_median: Decimal | None = None
    """첫 realized event의 ``realized_pnl_net`` 평균/중앙값 — 참고
    정보일 뿐이며, "이 손실은 shadow 때문" 같은 해석을 뒷받침하지
    않는다."""


class LossCutShadowMissingCauseBreakdownItem(BaseModel):
    """``missing-first-event-causes``의 원인 bucket 1건.

    ``rate``는 이 bucket count를 **missing 표본 전체**(``missing_
    first_event_count``)로 나눈 값이다 — 전체 sample 대비 비율이
    아니다."""

    cause: str
    count: int
    rate: float


class LossCutShadowMissingGroupBreakdownItem(BaseModel):
    """``by_source_type``/``by_tier``/``by_decision_type`` 공통 1행.

    ``group_value``는 그룹 키(예: ``"held_position"``, ``"hard"``,
    ``"hold"``)다. ``missing_first_event_rate``는 이 그룹 **안에서**
    (``sample_count`` 대비) missing 비율이다 — 특정 그룹에서 missing이
    유독 많은지 비교하기 위한 필드다."""

    group_value: str
    sample_count: int
    missing_first_event_count: int
    missing_first_event_rate: float | None = None


class LossCutShadowMissingFirstEventCausesResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/missing-first-event-causes` 응답.

    **원인 분류 inspection이지 인과 확정 도구가 아니다.** 각 bucket은
    이미 저장된 shadow sample/realized event/position 상태 값만으로
    코드상 재현 가능한 규칙으로 분류한 것이고, 새로운 매매 판단이나
    causality 해석은 하지 않는다. bucket 판정 우선순위(precedence)는
    ``missing_instrument_linkage`` → ``recompute_required`` →
    ``missing_position_state`` → ``still_holding_position`` →
    ``position_closed_but_no_realized_event`` →
    ``other_unclassified`` 순이다(자세한 판정 기준은 route
    docstring/설계 문서 참고).
    """

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    tier: str | None = None
    sample_count: int
    """``triggered=true``이고(필터가 있으면 그것도 만족하는) shadow
    sample 총 건수 — 분류 대상 모집단."""
    missing_first_event_count: int
    missing_first_event_rate: float | None = None
    """``missing_first_event_count / sample_count``. ``sample_count``가
    0이면 ``None``."""
    cause_breakdown: list[LossCutShadowMissingCauseBreakdownItem]
    by_source_type: list[LossCutShadowMissingGroupBreakdownItem]
    by_tier: list[LossCutShadowMissingGroupBreakdownItem]
    by_decision_type: list[LossCutShadowMissingGroupBreakdownItem]


class LossCutShadowMissingSampleView(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/missing-first-event-samples`의

    개별 행 — first realized event가 안 잡힌 shadow sample 1건.
    ``cause``는 ``missing-first-event-causes``와 **완전히 동일한**
    판정 함수(``_classify_missing_first_event_cause()``)로 계산한
    값이라, 두 endpoint 사이에 판정 불일치가 생기지 않는다.
    ``has_first_realized_event``는 이 endpoint 자체가 "missing" 표본만
    다루므로 항상 ``False``다 — 응답을 보는 사람이 별도 설명 없이도
    "이 표본은 first realized event가 없다"는 것을 필드만 보고 알 수
    있게 명시적으로 둔다."""

    trade_decision_id: UUID
    created_at: datetime
    symbol: str
    instrument_id: UUID | None = None
    source_type: str
    actual_decision_type: str
    tier: str | None = None
    triggered: bool | None = None
    loss_pct: Decimal | None = None
    shadow_only: bool | None = None
    cause: str
    recompute_required: bool | None = None
    """``position_cost_basis_state.recompute_required`` — state가
    없으면(``missing_position_state``/``missing_instrument_linkage``
    bucket) ``None``."""
    position_quantity: Decimal | None = None
    """``position_cost_basis_state.quantity`` — state가 없으면 ``None``."""
    has_first_realized_event: bool = False


class LossCutShadowMissingSamplesResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/missing-first-event-samples` 응답.

    **개별 사례 drilldown이지 인과 확정 도구가 아니다** — 각 row는
    ``missing-first-event-causes``가 집계하는 것과 같은 모집단·같은
    판정 규칙을 그대로 원시 행 단위로 보여줄 뿐이다."""

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    tier: str | None = None
    cause: str | None = None
    limit: int
    before: datetime | None = None
    items: list[LossCutShadowMissingSampleView]


class LossCutShadowRecomputeCrossCheckSampleView(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/missing-first-event-

    recompute-cross-check`의 개별 행 — missing sample 1건 + 그
    계좌×종목의 realized PnL recompute queue 상태를 나란히 보여준다.
    ``recompute_required``(``position_cost_basis_state``, sample
    관점)와 ``queue_pending``(``realized_pnl_recompute_queue``,
    큐 관점)는 **서로 다른 축**이다 — 둘이 항상 같이 움직인다고
    가정하지 않는다(이 endpoint의 핵심 존재 이유이기도 하다).
    """

    trade_decision_id: UUID
    created_at: datetime
    symbol: str
    instrument_id: UUID | None = None
    source_type: str
    actual_decision_type: str
    tier: str | None = None
    cause: str
    recompute_required: bool | None = None
    position_quantity: Decimal | None = None
    queue_pending: bool
    """이 계좌×종목에 대해 ``realized_pnl_recompute_queue``에 미해결
    (``resolved_at IS NULL``) 항목이 1건이라도 있으면 ``True``."""
    queue_pending_count: int
    queue_oldest_requested_at: datetime | None = None
    """가장 오래된 pending 항목의 ``requested_at``. 참고 정보일 뿐 —
    ``created_at``과의 선후 관계를 이 응답이 자동으로 해석하지
    않는다."""
    queue_reason_codes: list[str]
    has_first_realized_event: bool = False


class LossCutShadowRecomputeCrossCheckResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/missing-first-event-
    recompute-cross-check` 응답.

    **운영 대사(reconciliation) inspection이지 인과 확정 도구가
    아니다.** ``account_id + instrument_id`` 기준으로 missing
    sample과 recompute queue를 나란히 놓을 뿐이며, ``trade_decision_
    id``와 특정 queue 항목을 1:1로 인과 매칭하지 않는다. 하나의
    종목에 queue pending이 여러 건 걸려 있을 수 있고, sample
    ``created_at``과 queue ``requested_at``의 선후 관계도 참고
    정보로만 제공한다.
    """

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    tier: str | None = None
    sample_count: int
    """모집단 — 기간 내 ``triggered=true``이고 first realized event가
    없는(모든 cause 포함) shadow sample 총 건수."""
    queue_pending_match_count: int
    """``recompute_required=true``이면서 같은 계좌×종목에 queue
    pending도 있는 sample 수(케이스 1)."""
    queue_pending_missing_count: int
    """``recompute_required=true``인데 queue에는 pending이 없는
    sample 수(케이스 2) — queue가 없다고 바로 버그로 단정하지
    않는다, inspection 결과만 보여준다."""
    queue_pending_extra_count: int
    """``recompute_required``가 true가 아닌데도 같은 계좌×종목에
    queue pending이 있는 sample 수(케이스 3) — ``recompute_
    required``와 queue pending이 서로 다른 축임을 보여주는 신호."""
    recompute_required_queue_match_rate: float | None = None
    """``queue_pending_match_count / (queue_pending_match_count +
    queue_pending_missing_count)``. 분모가 0이면 ``None``."""
    limit: int
    before: datetime | None = None
    items: list[LossCutShadowRecomputeCrossCheckSampleView]


class LossCutShadowRecomputeMissingQueueSampleView(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/recompute-missing-queue-causes`

    의 개별 행 — ``missing-first-event-recompute-cross-check``의
    ``queue_pending_missing_count``(케이스 2)에 해당하는 sample
    1건을, 왜 queue pending이 안 보이는지에 대한 운영 분류
    (``cause``)와 함께 보여준다. ``recompute_required``/
    ``queue_pending``은 이 population 정의상 항상 ``True``/``False``
    다(응답에도 그대로 노출 — 값이 항상 같다는 것을 감추지 않는다).
    """

    trade_decision_id: UUID
    created_at: datetime
    symbol: str
    instrument_id: UUID | None = None
    source_type: str
    actual_decision_type: str
    tier: str | None = None
    cause: str
    recompute_required: bool = True
    position_quantity: Decimal | None = None
    queue_pending: bool = False
    has_first_realized_event: bool = False
    queue_scan_limit_reached: bool
    """이 응답을 만들 때 큐 스캔이 ``_LOSS_CUT_SHADOW_RECOMPUTE_
    QUEUE_SCAN_LIMIT``에 도달했는지 — 도달했다면 이 row의 ``queue_
    pending=False`` 판정 자체가 스캔 한계 때문일 수 있다(모든 row
    에 동일하게 적용되는 전역 신호)."""
    recompute_required_since: datetime | None = None
    """``position_cost_basis_state.updated_at`` — ``recompute_
    required``가 정확히 언제 세팅됐는지 기록하는 필드가 없어 이
    값을 근사치로 쓴다(``updated_at``이 없으면 ``null``). ``cause``
    판정의 근거로 참고하되, 이 필드가 곧 "recompute_required 시작
    시각"이라고 단정하지 않는다."""


class LossCutShadowRecomputeMissingQueueGroupBreakdownItem(BaseModel):
    """``by_source_type``/``by_tier`` 공통 1행.

    이 endpoint의 모집단 전체가 이미 "queue missing" 케이스이므로
    (``LossCutShadowMissingGroupBreakdownItem``처럼 더 큰 모집단
    대비 missing 비율을 보는 게 아니다), ``rate``는 이 그룹의
    ``count``를 응답 전체 ``sample_count``로 나눈 값이다 — 이
    endpoint 모집단 안에서 이 그룹이 차지하는 비중."""

    group_value: str
    count: int
    rate: float


class LossCutShadowRecomputeMissingQueueCausesResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/recompute-missing-queue-causes` 응답.

    **`missing-first-event-recompute-cross-check`의 후속 drilldown/
    분류 단계다** — cross-check가 "recompute_required인데 queue
    pending이 없다"는 불일치를 **탐지**한다면, 이 endpoint는 그 중
    queue missing 케이스만 모아 **왜 그런지 운영 관점에서 분류**
    한다. **원인 분류/운영 분류 inspection이지 진단 완료·인과
    확정 도구가 아니다** — "queue write 경로에 버그가 있다" 같은
    확정적 결론을 내리지 않고, `queue_write_path_suspected`처럼
    "의심"까지만 표현한다.
    """

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    tier: str | None = None
    sample_count: int
    """모집단 — ``triggered=true`` + first realized event 없음 +
    ``recompute_required=true`` + 같은 계좌×종목에 queue pending
    없음(``missing-first-event-recompute-cross-check``의 케이스 2와
    동일한 population)."""
    queue_scan_limit: int
    """큐 스캔 깊이(``_LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT``).
    이 값을 응답에 그대로 노출해 스캔 한계를 감추지 않는다."""
    queue_scan_limit_reached: bool
    """전역 신호 — 이번 조회에서 ``list_pending(limit=queue_scan_
    limit)``이 정확히 ``queue_scan_limit``건을 반환했는지(= 실제
    미해결 큐가 이 스캔 창보다 깊을 가능성). ``True``면 이 응답의
    모든 ``queue_pending=False`` 판정을 스캔 한계 관점에서 다시
    봐야 한다."""
    cause_breakdown: list[LossCutShadowMissingCauseBreakdownItem]
    by_source_type: list[LossCutShadowRecomputeMissingQueueGroupBreakdownItem]
    by_tier: list[LossCutShadowRecomputeMissingQueueGroupBreakdownItem]
    limit: int
    before: datetime | None = None
    items: list[LossCutShadowRecomputeMissingQueueSampleView]


class LossCutShadowQueueWritePathSuspectedTimelineItem(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/queue-write-path-suspected-

    timelines`의 개별 행 — `recompute-missing-queue-causes`가
    ``queue_write_path_suspected``로 분류한 sample 1건과, 단일
    ``.../timeline`` endpoint와 **동일한 규칙**으로 조회한 그 이후
    realized event 목록을 함께 담는다. ``cause``는 이 endpoint의
    모집단 정의상 항상 ``"queue_write_path_suspected"``다."""

    trade_decision_id: UUID
    created_at: datetime
    symbol: str
    instrument_id: UUID | None = None
    source_type: str
    actual_decision_type: str
    tier: str | None = None
    cause: str = "queue_write_path_suspected"
    recompute_required: bool = True
    queue_pending: bool = False
    has_first_realized_event: bool = False
    timeline_event_count: int
    first_event_found: bool
    """``events``에 1건 이상 있으면 ``True`` — "이후 realized event를
    찾았는지" 여부만 나타낸다. 이 event가 shadow 때문에 발생했다는
    인과 확정이 아니다."""
    first_event_latency_seconds: float | None = None
    """``events[0].seconds_after_shadow``(찾았으면). 못 찾았으면
    ``None`` — "얼마나 늦게 붙었는지 모른다"를 그대로 표현한다."""
    events: list[LossCutShadowTimelineRealizedEventView]


class LossCutShadowQueueWritePathSuspectedTimelinesResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/queue-write-path-suspected-
    timelines` 응답.

    **`recompute-missing-queue-causes`(cause=``queue_write_path_
    suspected``)의 후속 batch inspection이다** — 그 bucket에 속한
    sample들을 건건이 단일 ``.../timeline``으로 열어보는 수작업을
    줄이기 위한 것이다. **인과 확정 도구가 아니다** — "이 event가
    이 shadow 때문에 발생했다"/"queue write path가 고장났다" 같은
    결론을 내리지 않는다. 각 sample의 이후 realized event를
    나열할 뿐이다.
    """

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    tier: str | None = None
    sample_count: int
    """모집단 — ``triggered=true`` + ``recompute_required=true`` +
    queue pending 없음 + cause 판정이 ``queue_write_path_suspected``
    인 sample 총 건수. **``recompute-missing-queue-causes``와 달리
    "first realized event 없음"을 게이트로 쓰지 않는다** — 이후
    event가 실제로 붙었는지를 보는 것이 이 endpoint의 목적이라
    event 유무로 population을 거르면 목적이 성립하지 않기 때문이다."""
    event_limit: int
    timeline_with_events_count: int
    timeline_without_events_count: int
    """0이 아니면 그 자체가 중요한 운영 신호다 — "queue에도 없고
    이후 realized event도 아직 없다"는 뜻이라, `recompute_required`
    상태가 얼마나 오래 방치되고 있는지 확인해볼 만하다."""
    first_event_found_rate: float | None = None
    """``timeline_with_events_count / sample_count``. ``sample_
    count``가 0이면 ``None``."""
    max_observed_latency_seconds: float | None = None
    avg_first_event_latency_seconds: float | None = None
    """이후 event를 찾은 sample들의 ``first_event_latency_seconds``
    최댓값/평균값. 못 찾은 sample은 이 통계에서 제외한다(값이
    없다는 것과 0이라는 것을 구분하기 위함)."""
    limit: int
    before: datetime | None = None
    items: list[LossCutShadowQueueWritePathSuspectedTimelineItem]


class LossCutShadowQueueWritePathSuspectedByInstrumentItem(BaseModel):
    """``by_instrument`` 1행 — 종목별로 ``queue_write_path_suspected``

    sample이 얼마나 몰리는지, 그중 이후 realized event가 붙은 비율과
    지연 시간을 보여준다. "어느 종목부터 더 봐야 하는지" 판단하는
    용도다."""

    instrument_id: UUID
    symbol: str
    sample_count: int
    timeline_with_events_count: int
    timeline_without_events_count: int
    first_event_found_rate: float | None = None
    avg_first_event_latency_seconds: float | None = None
    max_observed_latency_seconds: float | None = None
    latest_sample_created_at: datetime


class LossCutShadowQueueWritePathSuspectedLatencyBucketItem(BaseModel):
    """``by_latency_bucket`` 1행 — 지연구간별 sample 분포.

    ``bucket`` 값은 다음 5개로 고정된다(``_first_event_latency_
    bucket()`` 참고):

    - ``no_event_found``: 이후 realized event를 아직 못 찾음
    - ``under_10m``: 첫 event까지 600초(10분) 미만
    - ``10m_to_1h``: 600초 이상 ~ 3600초(1시간) 미만
    - ``1h_to_1d``: 3600초 이상 ~ 86400초(1일) 미만
    - ``over_1d``: 86400초 이상
    """

    bucket: str
    count: int
    rate: float
    """``count / sample_count``. ``sample_count``가 0이면 ``0.0``."""


class LossCutShadowQueueWritePathSuspectedGroupBreakdownItem(BaseModel):
    """``by_source_type``/``by_tier`` 공통 1행."""

    group_value: str
    sample_count: int
    timeline_with_events_count: int
    timeline_without_events_count: int
    first_event_found_rate: float | None = None


class LossCutShadowQueueWritePathSuspectedTimelineSummaryResponse(BaseModel):
    """`GET /trade-decisions/loss-cut-shadow/queue-write-path-suspected-
    timeline-summary` 응답.

    **`queue-write-path-suspected-timelines`(raw batch inspection)의
    결과를 종목별/지연구간별/해소 여부 기준으로 요약한 것이다** —
    이 endpoint 자체는 새 계산을 하지 않는다. raw endpoint와
    **완전히 동일한 모집단·event 선정 규칙**(``_collect_queue_
    write_path_suspected_samples()`` 공통 helper)을 공유하므로, 같은
    조회 조건으로 두 endpoint를 호출하면 top-level 수치가 항상
    일치한다(raw는 ``limit``으로 표시 건수만 줄일 뿐 top-level
    집계는 전체 모집단 기준이다). **운영 summary inspection이지
    인과 확정 도구가 아니다.**
    """

    account_id: UUID
    start_date: date
    end_date: date
    source_type: str | None = None
    tier: str | None = None
    sample_count: int
    event_limit: int
    timeline_with_events_count: int
    timeline_without_events_count: int
    """0이 아니면 그 자체가 중요한 운영 신호다 — "queue에도 없고
    이후 realized event도 아직 없다"는 뜻."""
    first_event_found_rate: float | None = None
    max_observed_latency_seconds: float | None = None
    avg_first_event_latency_seconds: float | None = None
    median_first_event_latency_seconds: float | None = None
    by_instrument: list[LossCutShadowQueueWritePathSuspectedByInstrumentItem]
    by_latency_bucket: list[LossCutShadowQueueWritePathSuspectedLatencyBucketItem]
    by_source_type: list[LossCutShadowQueueWritePathSuspectedGroupBreakdownItem]
    by_tier: list[LossCutShadowQueueWritePathSuspectedGroupBreakdownItem]


class CandidateAlignmentStatusItem(BaseModel):
    """Deterministic candidate와 최종 decision의 정렬 상태 분포."""

    alignment_status: str
    decision_count: int


class CandidateIntentDistributionItem(BaseModel):
    """후보 intent 또는 최종 intent 분포 요약."""

    intent: str
    decision_count: int


class CandidateAlignmentSampleItem(BaseModel):
    """최근 candidate/final 불일치 sample row."""

    trade_decision_id: UUID
    symbol: str | None = None
    market: str | None = None
    source_type: str | None = None
    primary_candidate: str | None = None
    candidate_intent: str | None = None
    final_decision_type: str | None = None
    final_intent: str | None = None
    alignment_status: str | None = None
    override_applied: bool | None = None
    rationale_summary: str | None = None
    created_at: datetime | None = None


class CandidateAlignmentDiagnosticsResponse(BaseModel):
    """`GET /trade-decisions/candidate-alignment-diagnostics` 응답."""

    lookback_days: int
    sample_limit: int
    total_decision_count: int
    candidate_tracked_count: int
    candidate_missing_count: int
    override_applied_count: int
    matched_count: int
    candidate_coverage_rate: float
    match_rate: float
    alignment_status_items: list[CandidateAlignmentStatusItem]
    candidate_intent_items: list[CandidateIntentDistributionItem]
    final_intent_items: list[CandidateIntentDistributionItem]
    recent_misaligned_items: list[CandidateAlignmentSampleItem]


class TriggerAttributionBucketItem(BaseModel):
    """Trigger/override bucket별 주문·체결 전환 집계."""

    bucket: str
    decision_count: int
    actionable_decision_count: int
    order_count: int
    filled_order_count: int
    order_conversion_rate: float
    fill_conversion_rate: float


class TriggerPerformanceAttributionResponse(BaseModel):
    """`GET /performance-trigger-attribution` 응답."""

    account_id: str
    lookback_days: int
    total_decision_count: int
    tracked_decision_count: int
    actionable_decision_count: int
    ordered_decision_count: int
    filled_decision_count: int
    decision_to_order_rate: float
    decision_to_fill_rate: float
    alignment_items: list[TriggerAttributionBucketItem]
    candidate_intent_items: list[TriggerAttributionBucketItem]


class HoldingProfileAttributionItem(BaseModel):
    """holding_profile별 decision/order/fill 및 close-out proxy 집계."""

    holding_profile: str
    decision_count: int
    actionable_decision_count: int
    ordered_decision_count: int
    filled_decision_count: int
    avg_edge_after_cost_bps: float | None = None
    closed_trade_count: int
    avg_holding_minutes: float | None = None
    avg_realized_return_pct: float | None = None


class GuardrailAttributionItem(BaseModel):
    """reverse trade / probe churn / holding profile guard 차단 분포."""

    guardrail_family: str
    reason_code: str
    decision_count: int


class EdgeOutcomeAttributionItem(BaseModel):
    """edge_after_cost_bps bucket별 후행 보유기간/성과 proxy 집계."""

    edge_bucket: str
    closed_trade_count: int
    avg_holding_minutes: float | None = None
    avg_realized_return_pct: float | None = None


class HoldingProfilePerformanceAttributionResponse(BaseModel):
    """`GET /performance-holding-profile-attribution` 응답."""

    account_id: str
    lookback_days: int
    churn_window_hours: int
    total_decision_count: int
    reverse_trade_blocked_count: int
    probe_churn_blocked_count: int
    holding_profile_guard_blocked_count: int
    realized_opposite_fill_churn_count: int
    realized_opposite_fill_non_churn_count: int
    holding_profile_items: list[HoldingProfileAttributionItem]
    guardrail_items: list[GuardrailAttributionItem]
    edge_outcome_items: list[EdgeOutcomeAttributionItem]


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
    purchase_amount: float | None = None
    evaluation_amount: float | None = None
    source_of_truth: str
    snapshot_at: datetime
    created_at: datetime

    # ── Resolved instrument display fields (enriched at query time) ──
    symbol: str | None = None
    """Ticker symbol resolved from ``instrument_id`` (e.g. ``005930``)."""

    instrument_name: str | None = None
    """Human-readable instrument name resolved from ``instrument_id``
    (e.g. ``Samsung Electronics Co., Ltd.``)."""


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
    # ── KIS output2 계좌 총괄 필드 ──
    # total_asset: KIS tot_evlu_amt (총평가금액 = 유가증권 평가금액 합계 + D+2 예수금)
    # settlement_amount: KIS prvs_rcdl_excc_amt (가수도정산금액, D+2 예수금 기준)
    # total_unrealized_pnl: KIS evlu_pfls_smtl_amt (평가손익합계금액, 계좌 총괄)
    # orderable_amount: KIS ord_psbl_amt (주문가능금액, 실제 주문 가능 현금)
    total_asset: float | None = None
    settlement_amount: float | None = None
    total_unrealized_pnl: float | None = None
    orderable_amount: float | None = None
    source_of_truth: str
    snapshot_at: datetime
    created_at: datetime


class AlignmentStatus(str, Enum):
    """Snapshot alignment status between cash and position snapshots.

    ``"aligned"`` — both snapshots share the same ``snapshot_at`` timestamp.
    ``"partial"`` — timestamps differ by more than the tolerance threshold.
    ``"unknown"`` — one or both snapshots are missing (null).
    """

    ALIGNED = "aligned"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class AccountSnapshotResponse(BaseModel):
    """``GET /account-snapshots/latest`` — combined account snapshot view.

    Returns the latest position snapshots and cash balance snapshot for
    a single account in one response, along with an ``alignment_status``
    field that tells the UI whether the two data sets were captured at
    the same point in time.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    positions: list[PositionSnapshotView]
    cash_balance: CashBalanceSnapshotView | None
    alignment_status: AlignmentStatus
    """``"aligned"`` — equal snapshots / ``"partial"`` — timestamp differs /
    ``"unknown"`` — data missing."""

    positions_snapshot_at: datetime | None
    """Most recent ``snapshot_at`` among position snapshots."""

    cash_snapshot_at: datetime | None
    """Most recent ``snapshot_at`` of the cash balance snapshot."""

    snapshot_sync_run_id: str | None = None
    """The ``snapshot_sync_run_id`` used as the basis for this response.
    ``None`` when FK-based alignment was not possible (legacy data)."""

    alignment_detail: str = "unknown"
    """상세 alignment 구분 문자열.

    - ``"same_run"`` — position과 cash가 동일 sync_run에서 조회됨 (정규 장)
    - ``"after_hours_cash_updated"`` — after-hours cash 업데이트 반영,
      position은 이전 정규 장 기준
    - ``"cash_only"`` — position 정보 없이 cash만 조회됨 (PARTIAL)
    - ``"partial_position_only"`` — cash 정보 없이 position만 조회됨
    - ``"timestamp_proximity"`` — FK 없이 timestamp 근사치로 정합 (legacy)
    - ``"unknown"`` — 분류 불가
    """

    alignment_detail_description: str | None = None
    """``alignment_detail`` 값에 대한 사람이 읽기 쉬운 설명 문자열.
    API 응답에서 UI에 표시할 목적으로 제공된다.
    """


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


class GateCheckView(BaseModel):
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


class GateEvaluationView(BaseModel):
    """``GET /paper-go-no-go`` — Gate evaluation result.

    Aggregates individual checks across performance, stability and
    operational-health axes into a single ``GO`` / ``HOLD`` / ``NO_GO``
    overall status.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: str
    strategy_id: str | None
    overall_status: str  # GO / HOLD / NO_GO
    checks: list[GateCheckView]
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


class MarketSessionSummary(BaseModel):
    """Market session status summary for admin UI."""

    id: int
    run_date: date
    is_trading_day: bool
    opnd_yn: str | None = None
    bzdy_yn: str | None = None
    tr_day_yn: str | None = None
    market_phase: str | None = None
    raw_opnd_yn: str | None = None
    raw_mkop_cls_code: str | None = None
    raw_antc_mkop_cls_code: str | None = None
    source: str | None = None
    reason_code: str | None = None
    reason: str | None = None
    reason_metadata: dict[str, object] | None = None
    operations_day_scheduler_status: str | None = None
    operations_day_summary_json: dict[str, object] | None = None
    next_trading_day_readiness: dict[str, object] | None = None
    intraday_validation: dict[str, object] | None = None
    last_heartbeat_at: datetime | None = None
    checked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionEventSummary(BaseModel):
    """Session event summary for admin UI."""

    id: int
    market_session_id: int
    previous_phase: str | None = None
    new_phase: str | None = None
    trigger_source: str | None = None
    metadata: dict | None = None
    occurred_at: datetime
    created_at: datetime | None = None


class SessionEventsResponse(BaseModel):
    """``GET /market-sessions/events/recent`` — list of recent session events."""

    status: str = "ok"
    """Always ``"ok"`` — the endpoint returns 200 even for empty event sets."""

    data: list[SessionEventSummary]
    """Session events, newest first, up to the requested ``limit``."""


class MarketSessionDetailResponse(BaseModel):
    """``GET /market-sessions/by-date/{run_date}`` — single stored session row."""

    status: str  # "ok" | "no_data"
    data: MarketSessionSummary | None = None


class MarketSessionHistoryResponse(BaseModel):
    """``GET /market-sessions/history`` — stored session rows."""

    status: str = "ok"
    data: list[MarketSessionSummary]


class SchedulerStatusResponse(BaseModel):
    """Scheduler health and current session status."""

    status: str  # "ok" | "no_data"
    data: MarketSessionSummary | None = None
    healthy: bool = False
    stale_seconds: int | None = None


class OperationsDayRunSummary(BaseModel):
    """Latest operations-day scheduler state summary for admin/ops use."""

    operations_day_run_id: int
    run_date: date
    scheduler_status: str
    is_trading_day: bool
    session_source: str | None = None
    market_phase: str | None = None
    pre_market_done: bool = False
    end_of_day_done: bool = False
    after_hours_mode: bool = False
    recovery_batch_done: bool = False
    submit_count: int = 0
    held_position_sell_submit_count: int = 0
    cycles: int = 0
    last_phase_change_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    summary_json: dict[str, object] | None = None


class OperationsDayStatusResponse(BaseModel):
    """Latest ``operations_day_runs`` status with freshness metadata."""

    status: str  # "ok" | "no_data"
    data: OperationsDayRunSummary | None = None
    healthy: bool = False
    stale_seconds: int | None = None


class OperationsDayDetailResponse(BaseModel):
    """``GET /market-sessions/operations-day/by-date/{run_date}`` response."""

    status: str  # "ok" | "no_data"
    data: OperationsDayRunSummary | None = None


class OperationsDayHistoryResponse(BaseModel):
    """``GET /market-sessions/operations-day/history`` response."""

    status: str = "ok"
    data: list[OperationsDayRunSummary]


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
    var_confidence_level: float | None = None
    var_horizon_days: int | None = None
    var_lookback_days: int | None = None
    portfolio_var_1d: float | None = None
    portfolio_var_1d_adjusted: float | None = None
    largest_var_symbol: str | None = None
    largest_var_contribution_pct: float | None = None
    concentration_penalty_pct: float | None = None
    var_status: str | None = None
    var_reason_codes: list[str] | None = None
    symbol_var_json: dict[str, object] = {}
    symbol_marginal_contribution_json: dict[str, object] = {}
    symbol_exposure_json: dict[str, object] = {}
    sector_exposure_json: dict[str, object] = {}
    open_order_exposure_json: dict[str, object] = {}
    drawdown_state: str | None = None
    kill_switch_active: bool = False
    blocked_reason_codes: list[str] | None = None
    created_at: datetime | None = None


class SignalFeatureSnapshotView(BaseModel):
    """``GET /signal-feature-snapshots`` — 종목 단위 signal feature snapshot."""

    model_config = ConfigDict(from_attributes=True)

    signal_feature_snapshot_id: UUID
    instrument_id: UUID
    symbol: str
    market_code: str
    timeframe: str
    snapshot_at: datetime
    feature_set_version: str
    bar_count: int
    sma_5: float | None = None
    sma_20: float | None = None
    sma_60: float | None = None
    price_vs_sma_20_pct: float | None = None
    price_vs_sma_60_pct: float | None = None
    return_1m_pct: float | None = None
    return_3m_pct: float | None = None
    volatility_20d_pct: float | None = None
    atr_14_pct: float | None = None
    rsi_14: float | None = None
    average_volume_20d: float | None = None
    average_turnover_20d: float | None = None
    volume_surge_ratio: float | None = None
    turnover_surge_ratio: float | None = None
    fast_score: float | None = None
    slow_score: float | None = None
    overall_score: float | None = None
    component_scores_json: dict[str, object] = {}
    reason_codes: list[str] | None = None
    created_at: datetime | None = None


class DecisionContextSignalFeatureCoverageView(BaseModel):
    """최근 decision context의 signal feature anchor 부착률 요약."""

    recent_context_count: int
    anchored_context_count: int
    missing_context_count: int
    coverage_rate: float
    sampled_missing_context_ids: list[UUID] = []


# ---------------------------------------------------------------------------
# Manual status change schemas (Phase 26 — operator override)
# ---------------------------------------------------------------------------


class ManualStatusChangeRequest(BaseModel):
    """Request body for ``PUT /orders/{order_request_id}/status``.

    v1 scope: ``RECONCILE_REQUIRED`` → one of ``_MANUAL_RESOLVE_TARGETS``.
    """

    target_status: OrderStatus = Field(..., description="Target order status")
    reason_code: str | None = Field(default="MANUAL_RESOLVE")
    reason_message: str | None = None
    evidence: dict[str, object] = Field(..., description="Operator evidence payload")


class ManualStatusChangeResponse(BaseModel):
    """Response for a successful manual status change."""

    order_id: str
    old_status: str
    new_status: str
    updated_at: datetime | None = None
    actor: str


class UpdateMaxSinglePositionPctRequest(BaseModel):
    """``POST /config-versions/risk/max-single-position-pct`` 요청 본문.

    이 endpoint는 어떤 client×environment의 활성 config를 바꾸는지
    명시적으로 지정하게 강제한다 — 암묵적 "현재 계정"이라는 개념이 없다.
    """

    client_id: str = Field(..., description="Client UUID whose active config to update")
    environment: str = Field(
        ...,
        description=(
            "'paper' | 'live' only — 'real' is rejected (config_versions.environment's "
            "DB CHECK constraint does not accept it)"
        ),
    )
    max_single_position_pct: Decimal = Field(
        ..., description="New value, 0 < x <= 100 (NAV 대비 단일 종목 최대 비중 %)"
    )
    reason: str | None = Field(default=None, description="Optional operator-provided reason (audit trail)")


class UpdateMaxSinglePositionPctResponse(BaseModel):
    """성공적인 config_version 발행 결과."""

    config_version_id: str
    previous_config_version_id: str
    client_id: str
    environment: str
    version_tag: str
    previous_max_single_position_pct: str | None
    new_max_single_position_pct: str
    activated_at: datetime | None
    activated_by: str


class ExecutionFeeTaxInput(BaseModel):
    """``POST /config-versions/execution-fee-tax`` 요청의 ``execution.fee_tax`` 본문.

    설계 근거: docs/00_foundational_design/detailed_design/
    12_realized_pnl_moving_average_ledger.md 13절. 숫자는 반드시
    문자열로 보낸다(``Decimal`` 직접 입력 불가 — JSON 자체의 한계이자
    이 저장소의 기존 관례).
    """

    enabled: bool = Field(
        ..., description="false면 계산을 하지 않고 assumed_zero로 남긴다"
    )
    supported_asset_classes: list[str] = Field(
        ..., description="예: [\"kr_stock\"] — instruments.asset_class와 정확히 일치해야 매칭된다"
    )
    supported_market_segments: list[str] = Field(
        ..., description="예: [\"KOSPI\", \"KOSDAQ\"] — instruments.market_segment와 정확히 일치해야 매칭된다"
    )
    buy_commission_rate_pct: str = Field(
        ..., description="퍼센트 그 자체 숫자. 예: '0.0140527' (=0.0140527%, 0.00140527이 아님)"
    )
    sell_commission_rate_pct: str = Field(
        ..., description="퍼센트 그 자체 숫자. 예: '0.0140527'"
    )
    sell_tax_rate_pct: str = Field(
        ..., description="매도 증권거래세율(퍼센트). 예: '0.2000' (코스피는 거래세+농특세 합산 정책에 따라 다름)"
    )
    sell_agri_tax_rate_pct: str = Field(
        ..., description="매도 농어촌특별세율(퍼센트). 예: '0.0000' — 코스닥은 통상 0"
    )
    rounding_mode: str = Field(
        ..., description="'round_half_up' | 'round_down' — 다른 값은 등록 단계에서 거부된다"
    )
    rounding_unit: str = Field(
        ..., description="라운딩 단위(원). 예: '1' (원 단위 반올림/절사)"
    )
    reason: str = Field(..., description="필수 — 왜 이 정책을 등록/변경하는지(감사 추적)")
    operator_note: str | None = Field(default=None, description="선택 — 운영자 메모")
    source_note: str | None = Field(default=None, description="선택 — 요율 근거 출처(예: 계좌 계약서 확인 등)")


class FeeTaxPolicyPreviewView(BaseModel):
    """등록 전(또는 dry-run) 검증을 통과한 정규화된 정책값 + 샘플 계산 결과.

    ``sample_price``/``sample_quantity``는 재무 규칙 확정이 아니라
    "이 요율로 계산하면 이런 숫자가 나온다"를 운영자가 눈으로 바로
    확인하기 위한 고정 예시(10만원 x 10주)다.
    """

    model_config = ConfigDict(from_attributes=True)

    normalized_fee_tax: dict[str, object]
    sample_price: str
    sample_quantity: str
    sample_buy_fee: str
    sample_sell_fee: str
    sample_sell_tax: str


class PublishFeeTaxPolicyRequest(BaseModel):
    """``POST /config-versions/execution-fee-tax`` 요청 본문."""

    client_id: str = Field(..., description="Client UUID")
    environment: str = Field(..., description="'paper' | 'live' only — 'real'은 거부된다")
    execution_fee_tax: ExecutionFeeTaxInput
    activated_at: datetime | None = Field(
        default=None,
        description=(
            "생략하면 현재 시각. 지정하면 현재 활성 버전의 activated_at보다 "
            "반드시 이후여야 한다(동일 시각/과거 시각 등록은 거부)."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description="true면 검증/미리보기만 수행하고 아무것도 저장하지 않는다",
    )


class PublishFeeTaxPolicyResponse(BaseModel):
    """``POST /config-versions/execution-fee-tax`` 응답.

    ``dry_run=true``였으면 ``config_version_id``/``version_tag``/
    ``activated_at``/``activated_by``는 전부 ``None``이고 ``preview``만
    채워진다 — 아무것도 저장되지 않았기 때문이다.
    """

    dry_run: bool
    config_version_id: str | None = None
    previous_config_version_id: str | None = None
    client_id: str
    environment: str
    version_tag: str | None = None
    activated_at: datetime | None = None
    activated_by: str | None = None
    preview: FeeTaxPolicyPreviewView


class ActiveFeeTaxPolicyResponse(BaseModel):
    """``GET /config-versions/execution-fee-tax/active|at`` 응답.

    ``config_version_id``/``execution_fee_tax``가 ``None``이면 해당
    client×environment(×시점)에 아직 fee/tax 정책이 등록되지 않은
    것이다 — 오류가 아니라 ``compute_fee_tax()``가 ``assumed_zero``로
    처리하는 정상 상태와 정확히 대응한다.
    """

    client_id: str
    environment: str
    config_version_id: str | None = None
    activated_at: datetime | None = None
    execution_fee_tax: dict[str, object] | None = None


class ExternalEventView(BaseModel):
    """Lightweight external event view for UI consumption."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: str
    source_name: str
    source_reliability_tier: str
    symbol: str | None = None
    headline: str | None = None
    body_summary: str | None = None
    published_at: datetime
    created_at: datetime | None = None


class ExternalEventsResponse(BaseModel):
    """Wrapper for recent external events response."""

    status: str = "ok"
    data: list[ExternalEventView]


# ---------------------------------------------------------------------------
# Phase D — Inspection API: Broker Truth & Sell Availability
# ---------------------------------------------------------------------------


class BrokerTruthResponse(BaseModel):
    """``GET /orders/{order_request_id}/broker-truth`` — KIS broker truth result.

    Returns the raw KIS inquiry result mapped to domain status, with fallback
    to cached ``broker_orders`` data when the KIS API is unavailable.
    """

    model_config = ConfigDict(from_attributes=True)

    order_request_id: UUID
    broker_order_id: str | None = None
    kis_status_code: str | None = None
    mapped_status: str | None = None
    filled_qty: Decimal | None = None
    open_qty: Decimal | None = None
    avg_fill_price: Decimal | None = None
    order_qty: Decimal | None = None
    order_price: Decimal | None = None
    last_synced_at: datetime | None = None
    source: str = "VTTC0081R"


class SellAvailabilityResponse(BaseModel):
    """``GET /orders/sell-availability`` — available sell quantity calculation result.

    Returns the computed available sell quantity considering open orders and
    partially filled orders, along with block status.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    symbol: str
    current_position_qty: Decimal
    open_sell_qty: Decimal
    partially_filled_qty: Decimal
    available_sell_qty: Decimal
    is_blocked: bool
    block_reason: str | None = None


class ExecutionAttemptDetail(BaseModel):
    """``GET /execution-attempts`` — execution attempt detail.

    Maps 1:1 to ``ExecutionAttemptEntity`` for read-only inspection.
    """

    model_config = ConfigDict(from_attributes=True)

    execution_attempt_id: UUID
    trade_decision_id: UUID
    decision_context_id: UUID
    status: str
    stop_phase: str | None = None
    stop_reason: str | None = None
    phase_trace: list[dict[str, object]] | None = None
    order_request_id: UUID | None = None
    started_at: datetime
    completed_at: datetime | None = None
    created_at: datetime | None = None


class ExecutionAttemptListResponse(BaseModel):
    """``GET /execution-attempts?trade_decision_id=...`` — paginated list."""

    status: str = "ok"
    data: list[ExecutionAttemptDetail]


class SubmissionAttemptView(BaseModel):
    """Read-only view of a single order submission attempt."""

    model_config = ConfigDict(from_attributes=True)

    order_submission_attempt_id: UUID
    order_request_id: UUID
    attempt_number: int
    submitted_at: datetime
    broker_name: str | None = None
    accepted: bool | None
    broker_native_order_id: str | None = None
    broker_status: str | None = None
    raw_code: str | None = None
    raw_message: str | None = None
    error_type: str | None = None
    retryable: bool | None = None
    http_status: int | None = None
    duration_ms: int | None = None
    created_at: datetime | None = None
    attempt_outcome: str | None = None
    """Derived outcome for this attempt: 'accepted', 'rejected', 'exception', or None."""


def _derive_submission_outcome(
    latest_accepted: bool | None,
    latest_error_type: str | None,
) -> str | None:
    """Derive ``latest_outcome`` from stored submission attempt fields.

    Priority:
    1. latest_error_type is not None  → "exception"
    2. latest_accepted == True        → "accepted"
    3. latest_accepted == False       → "rejected"
    4. latest_accepted is None        → None (no attempts)
    """
    if latest_error_type is not None:
        return "exception"
    if latest_accepted is True:
        return "accepted"
    if latest_accepted is False:
        return "rejected"
    return None


class SubmissionAttemptSummary(BaseModel):
    """Order detail에 포함될 submission attempts 요약 (Phase 7)."""

    model_config = ConfigDict(from_attributes=True)

    attempt_count: int = 0
    """총 제출 시도 횟수 (0 = 시도 없음)."""
    latest_accepted: bool | None = None
    """마지막 시도의 accepted 여부. 시도가 없으면 None."""
    latest_raw_code: str | None = None
    """마지막 시도의 raw_code (예: ACC, PEN, REJ)."""
    latest_raw_message: str | None = None
    """마지막 시도의 raw_message."""
    latest_error_type: str | None = None
    """마지막 시도의 error_type (거부/실패 시)."""
    last_submitted_at: datetime | None = None
    """마지막 제출 시도 시각. 시도가 없으면 None."""
    # Phase 8: derived outcome for readability
    latest_outcome: str | None = None
    """Derived outcome: 'accepted', 'rejected', 'exception', or None."""


class RecentFailureItem(BaseModel):
    """A single order request whose latest submission attempt failed.

    Returned by ``GET /orders/recent-failures``.
    """

    model_config = ConfigDict(from_attributes=True)

    order_request_id: str
    symbol: str | None = None
    side: str | None = None
    latest_outcome: str  # 'rejected' | 'exception'
    latest_error_type: str | None = None
    latest_raw_code: str | None = None
    latest_raw_message: str | None = None
    last_submitted_at: datetime | None = None
    created_at: datetime | None = None


class FailureSummaryResponse(BaseModel):
    """Aggregated submission failure counts for the last 1h and 24h.

    Returned by ``GET /orders/failure-summary``.
    The ``failure_rate_pct_24h`` is computed as the ratio of failed
    attempts to **all** submission attempts (accepted + rejected + exception)
    within the last 24 hours.
    """

    last_1h_count: int = 0
    """Number of failed attempts (rejected or exception) in the last hour."""

    last_24h_count: int = 0
    """Number of failed attempts (rejected or exception) in the last 24 hours."""

    rejected_count: int = 0
    """Number of rejected attempts in the last 24 hours."""

    exception_count: int = 0
    """Number of exception attempts in the last 24 hours."""

    total_submissions_24h: int = 0
    """Total number of submission attempts (accepted + rejected + exception)
    in the last 24 hours.  Used as the denominator for ``failure_rate_pct_24h``."""

    failure_rate_pct_24h: float | None = None
    """Failure rate in the last 24 hours, computed as
    ``last_24h_count / total_submissions_24h * 100``.
    ``None`` when there are zero total submissions."""

    today_count: int = 0
    """Number of failed attempts (rejected or exception) since KST 00:00 today."""

    rejected_count_today: int = 0
    """Number of rejected attempts since KST 00:00 today."""

    exception_count_today: int = 0
    """Number of exception attempts since KST 00:00 today."""

    total_submissions_today: int = 0
    """Total number of submission attempts since KST 00:00 today."""

    failure_rate_pct_today: float | None = None
    """Failure rate since KST 00:00 today.
    ``today_count / total_submissions_today * 100``.
    ``None`` when there are zero total submissions today."""


class RealtimeQuoteLevel(BaseModel):
    """One price/quantity rung of the orderbook ladder."""

    price: float
    quantity: int


class RealtimeQuoteConnectionInfo(BaseModel):
    """Connection + capacity status for the realtime quote source.

    Phase 1: ``environment="mock"``, ``data_source="mock"`` — no KIS
    WebSocket connection exists yet. Phase 2 will populate these from the
    real KIS-backed source without changing this schema.
    """

    connection_state: str
    environment: str
    data_source: str
    registered_count: int
    max_registrations: int
    registrations_per_symbol: int
    symbol_capacity: int
    """``max_registrations // registrations_per_symbol`` — the realistic
    number of symbols that can be subscribed at once (KIS counts 체결가+호가
    as 2 registrations per symbol)."""


class RealtimeQuoteSubscriptionView(BaseModel):
    """A single subscribed symbol's identity (no price data)."""

    symbol: str
    market: str
    name: str


class RealtimeQuoteBootstrapResponse(BaseModel):
    """``GET /realtime-quotes/bootstrap`` — initial screen load payload."""

    connection: RealtimeQuoteConnectionInfo
    subscriptions: list[RealtimeQuoteSubscriptionView]
    generated_at: datetime


class RealtimeQuoteSubscribeRequest(BaseModel):
    """``POST /realtime-quotes/subscriptions`` request body."""

    symbols: list[str] = Field(min_length=1, max_length=20)


class RealtimeQuoteUnsubscribeRequest(BaseModel):
    """``DELETE /realtime-quotes/subscriptions`` request body."""

    symbols: list[str] = Field(min_length=1, max_length=20)


class RealtimeQuoteSubscriptionsResponse(BaseModel):
    """Response shared by subscribe/unsubscribe/list-subscriptions endpoints."""

    connection: RealtimeQuoteConnectionInfo
    subscriptions: list[RealtimeQuoteSubscriptionView]
    generated_at: datetime


class RealtimeQuoteTradeTickView(BaseModel):
    """One 체결(trade) tick — '실시간 체결가' 프레임의 '시별' 탭 한 행."""

    trade_time: str
    price: float
    change: float
    change_rate: float
    volume: int
    """해당 tick의 체결량(``CNTG_VOL``) — 누적거래량이 아님."""


class RealtimeQuoteSnapshotView(BaseModel):
    """``GET /realtime-quotes/snapshot`` — one symbol's latest quote."""

    symbol: str
    market: str
    name: str
    last_price: float
    prev_close: float
    change: float
    change_rate: float
    change_sign: str
    open_price: float
    high_price: float
    low_price: float
    upper_limit: float
    lower_limit: float
    accumulated_volume: int
    accumulated_value: int
    per: float | None = None
    pbr: float | None = None
    eps: float | None = None
    bps: float | None = None
    ask_levels: list[RealtimeQuoteLevel]
    bid_levels: list[RealtimeQuoteLevel]
    total_ask_quantity: int
    total_bid_quantity: int
    trade_time: str
    hour_class: str
    trading_halted: bool
    data_source: str
    updated_at: datetime
    recent_trades: list[RealtimeQuoteTradeTickView] = Field(default_factory=list)
    """최근 체결 tick 히스토리, 최신순 — '실시간 체결가' 프레임 '시별' 탭 표시용."""


class RealtimeQuoteSnapshotResponse(BaseModel):
    """Response for ``GET /realtime-quotes/snapshot``.

    ``quotes`` omits any requested symbol that is not currently subscribed
    (not an error — mirrors cache-miss behaviour of the real source).
    """

    quotes: dict[str, RealtimeQuoteSnapshotView]
    generated_at: datetime


class RealtimeQuoteDailyPriceItem(BaseModel):
    """하루치 시세 — '실시간 체결가' 프레임 '일별' 탭 한 행 (KIS ``FHKST01010400``)."""

    date: str
    """"YYYYMMDD"."""
    close: float
    change: float
    change_rate: float
    volume: int


class RealtimeQuoteDailyPriceResponse(BaseModel):
    """``GET /realtime-quotes/daily-price`` — 최근 거래일 순(최신 먼저)."""

    symbol: str
    bars: list[RealtimeQuoteDailyPriceItem]
    generated_at: datetime


class RealizedPnlPositionView(BaseModel):
    """``GET /performance/realized-pnl/positions`` 한 행 — 계좌×종목 realized PnL 종목 누계.

    .. note::

       계산은 하지 않는다. ``position_quantity``/``average_cost``/
       ``recompute_required``/``recompute_reason``은 저장된
       ``position_cost_basis_state``를 그대로 읽은 값이고,
       ``realized_pnl_net_cumulative``는 ``realized_pnl_daily_aggregates``
       (해당 계좌×종목의 모든 날짜)의 ``realized_pnl_net_sum``을 단순
       합산한 값이다 — authoritative source는 ``realized_pnl_daily_aggregates``다
       (``realized_pnl_events``에서 언제든 재생성 가능한 파생 캐시이며,
       이 값 자체를 다시 계산하지 않는다).
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    instrument_id: UUID
    symbol: str | None = None
    instrument_name: str | None = None
    position_quantity: Decimal
    average_cost: Decimal
    recompute_required: bool
    recompute_reason: str | None = None
    realized_pnl_net_cumulative: Decimal
    updated_at: datetime | None = None


class RealizedPnlEventView(BaseModel):
    """``GET /performance/realized-pnl/events`` 한 행 — 체결별 realized PnL event.

    ``trading.realized_pnl_events``를 그대로 읽은 값이다(계산 없음).
    """

    model_config = ConfigDict(from_attributes=True)

    realized_pnl_event_id: UUID
    account_id: UUID
    instrument_id: UUID
    fill_event_id: UUID
    broker_order_id: UUID
    order_request_id: UUID
    sell_quantity: Decimal
    sell_price: Decimal
    avg_cost_basis_before: Decimal
    fee: Decimal
    tax: Decimal
    fee_tax_source: str
    realized_pnl_gross: Decimal
    realized_pnl_net: Decimal
    position_quantity_after: Decimal
    fill_timestamp: datetime
    allocated_buy_fee: Decimal
    """이번 SELL에 매수 수수료 pool에서 배분된 몫(``fee``와는 분리 보존)."""
    buy_fee_allocation_source: str
    """``allocated_buy_fee``가 배분된 pool의 provenance 요약."""


class RealizedPnlEventsResponse(BaseModel):
    """``GET /performance/realized-pnl/events`` 응답 — 조회 조건 echo + 목록."""

    account_id: UUID
    instrument_id: UUID
    limit: int
    before: datetime | None = None
    events: list[RealizedPnlEventView]


class RealizedPnlProvenanceBreakdown(BaseModel):
    """provenance(``fee_tax_source``)별 이벤트 건수 분포 — 4키 고정.

    설계 근거: docs/00_foundational_design/detailed_design/
    12_realized_pnl_moving_average_ledger.md 13.5절.

    집계 단위(일자/종목/요약)에는 서로 다른 provenance를 가진 이벤트가
    섞일 수 있다 — 대표값 하나로 뭉개거나 provenance 자체를 숨기지 않고,
    4개 값 각각의 건수를 그대로 노출한다. 0건인 provenance도 키 자체는
    항상 포함한다(응답에서 빠진 것과 "0건"을 구분하기 위함). 이번 계약은
    **건수 기준만** 다룬다 — 금액 합계 breakdown은 범위 밖이다(13.6절).
    """

    model_config = ConfigDict(from_attributes=True)

    reported: int = 0
    assumed_zero: int = 0
    calculated_from_policy: int = 0
    policy_not_applicable: int = 0


class RealizedPnlDailyAggregateView(BaseModel):
    """``GET /performance/realized-pnl/daily`` 한 행 — 일자별 realized PnL aggregate.

    ``trading.realized_pnl_daily_aggregates``를 그대로 읽은 값이다(계산 없음).

    ``buy_amount_sum``/``sell_amount_sum``/``fee_tax_sum``은 Admin UI
    실현손익 화면(design/realized_pnl_screen_spec.md)을 위한 UI용 파생
    합계 캐시다 — ``realized_pnl_events``의 기존 필드를 그대로 합산한
    값이며 새로운 손익 계산식이 아니다.

    ``provenance_breakdown``은 이 날짜(``/daily-summary``는 계좌 전체,
    ``/daily``는 단일 종목)에 속한 ``realized_pnl_events``를
    ``fee_tax_source``별로 건수만 센 값이다 — 계산이 아니라 단순 집계다.
    """

    model_config = ConfigDict(from_attributes=True)

    trade_date: date
    realized_pnl_net_sum: Decimal
    sell_event_count: int
    buy_amount_sum: Decimal = Decimal("0")
    sell_amount_sum: Decimal = Decimal("0")
    fee_tax_sum: Decimal = Decimal("0")
    provenance_breakdown: RealizedPnlProvenanceBreakdown = Field(
        default_factory=RealizedPnlProvenanceBreakdown
    )


class RealizedPnlDailyResponse(BaseModel):
    """``GET /performance/realized-pnl/daily`` 응답 — 조회 조건 echo + 목록."""

    account_id: UUID
    instrument_id: UUID
    start_date: date | None = None
    end_date: date | None = None
    daily: list[RealizedPnlDailyAggregateView]


class RealizedPnlDailySummaryResponse(BaseModel):
    """``GET /performance/realized-pnl/daily-summary`` 응답 — Admin UI 탭 A(일자별)의

    종목 "전체" N+1 제거용. ``realized_pnl_daily_aggregates``(계좌의 모든 종목,
    조회 기간)를 ``trade_date``별로 단순 합산한 값이다 — 새 손익 계산식이
    아니다. 종목별 groupby는 ``/performance/realized-pnl/summary``가,
    날짜별 groupby는 이 endpoint가 담당한다(역할 분리, 계약 변경 없음).
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    start_date: date
    end_date: date
    daily: list[RealizedPnlDailyAggregateView]


class RealizedPnlRecomputeQueueItemView(BaseModel):
    """``GET /performance/realized-pnl/recompute-queue`` 한 행 — pending 재계산 큐 항목.

    ``trading.realized_pnl_recompute_queue``의 미해결(``resolved_at IS NULL``)
    항목을 그대로 읽은 값이다(계산·해소 없음, 조회 전용).
    """

    model_config = ConfigDict(from_attributes=True)

    recompute_queue_id: UUID
    account_id: UUID
    instrument_id: UUID
    reason_code: str
    triggering_fill_event_id: UUID | None = None
    requested_at: datetime | None = None


class RealizedPnlRecomputeQueueResponse(BaseModel):
    """``GET /performance/realized-pnl/recompute-queue`` 응답 — 조회 조건 echo + 목록."""

    account_id: UUID | None = None
    instrument_id: UUID | None = None
    limit: int
    items: list[RealizedPnlRecomputeQueueItemView]


class RealizedPnlSummaryInstrumentView(BaseModel):
    """``GET /performance/realized-pnl/summary``의 종목별 한 행.

    ``realized_pnl_daily_aggregates``(해당 종목, 조회 기간)의 5개 합계
    필드를 그대로 더한 값이다 — 새 손익 계산식이 아니다.
    ``recompute_required``는 ``position_cost_basis_state``를 그대로 읽은 값.
    """

    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID
    symbol: str | None = None
    instrument_name: str | None = None
    realized_pnl_net_sum: Decimal
    sell_event_count: int
    buy_amount_sum: Decimal
    sell_amount_sum: Decimal
    fee_tax_sum: Decimal
    recompute_required: bool
    provenance_breakdown: RealizedPnlProvenanceBreakdown = Field(
        default_factory=RealizedPnlProvenanceBreakdown
    )


class RealizedPnlSummaryResponse(BaseModel):
    """``GET /performance/realized-pnl/summary`` 응답 — Admin UI 실현손익 화면의

    요약 카드 + 종목별 탭을 위한 단일 호출 조회. ``instrument_id``를 생략하면
    계좌 전체(모든 종목)를 대상으로 하고, 지정하면 그 종목 하나로 좁힌다.
    최상위 합계 필드는 ``by_instrument``의 단순 합산이다 — 계산이 아니다.
    """

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    instrument_id: UUID | None = None
    start_date: date
    end_date: date
    realized_pnl_net_sum: Decimal
    sell_event_count: int
    buy_amount_sum: Decimal
    sell_amount_sum: Decimal
    fee_tax_sum: Decimal
    recompute_pending_count: int
    provenance_breakdown: RealizedPnlProvenanceBreakdown = Field(
        default_factory=RealizedPnlProvenanceBreakdown
    )
    by_instrument: list[RealizedPnlSummaryInstrumentView]


# Rebuild models to resolve forward references under ``from __future__ import annotations``.
# The ``_types_namespace`` provides the necessary type mappings that are otherwise
# evaluated lazily as strings under PEP 563.
BrokerTruthResponse.model_rebuild(_types_namespace={"Decimal": Decimal, "UUID": UUID, "datetime": datetime})
ExecutionAttemptDetail.model_rebuild(_types_namespace={"Decimal": Decimal, "UUID": UUID, "datetime": datetime})
SellAvailabilityResponse.model_rebuild(_types_namespace={"Decimal": Decimal, "UUID": UUID, "datetime": datetime})
