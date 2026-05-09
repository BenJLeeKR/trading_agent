"""Pydantic response models for the FastAPI inspection API (Phase 1).

These are minimal **read models** — not 1:1 mirrors of domain entities.
``pydantic`` v2 handles common type coercions automatically
(``UUID`` → ``str``, ``Decimal`` → ``float``, ``Enum`` → ``str``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
