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
    """'broker_submit/AAPL' → ('broker_submit', 'AAPL')
    'ai_assemble' → ('ai_assemble', None)
    """
    if "/" in phase:
        parts = phase.split("/", maxsplit=1)
        return parts[0], parts[1]
    return phase, None


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
    decision_json: dict[str, object] | None = None
    """Raw decision payload from EI/AR agents (``event_bias``, ``risk_opinion``, etc.)."""

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
        elif self.decision_type in ('HOLD', 'WATCH'):
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
    reason: str | None = None
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


class SchedulerStatusResponse(BaseModel):
    """Scheduler health and current session status."""

    status: str  # "ok" | "no_data"
    data: MarketSessionSummary | None = None
    healthy: bool = False
    stale_seconds: int | None = None


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


# Rebuild models to resolve forward references under ``from __future__ import annotations``.
# The ``_types_namespace`` provides the necessary type mappings that are otherwise
# evaluated lazily as strings under PEP 563.
BrokerTruthResponse.model_rebuild(_types_namespace={"Decimal": Decimal, "UUID": UUID, "datetime": datetime})
ExecutionAttemptDetail.model_rebuild(_types_namespace={"Decimal": Decimal, "UUID": UUID, "datetime": datetime})
SellAvailabilityResponse.model_rebuild(_types_namespace={"Decimal": Decimal, "UUID": UUID, "datetime": datetime})
