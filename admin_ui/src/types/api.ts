/* ───────────────────────────────────────────
 * TypeScript interfaces matching backend schemas
 * Based on src/agent_trading/api/schemas.py
 * ─────────────────────────────────────────── */

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
  database: string;
  runtime_mode: string;
  // ── Snapshot Sync Freshness (optional) ──
  snapshot_sync_detail: string | null;
  snapshot_sync_stale: boolean | null;
  snapshot_sync_last_successful_run_at: string | null;
  snapshot_sync_consecutive_failures: number | null;
  // ── Scheduler Freshness (optional) ──
  scheduler: SchedulerStatus | null;
}

export interface SchedulerStatus {
  last_heartbeat_at: string | null;
  is_trading_day: boolean | null;
  checked_at: string | null;
  healthy: boolean | null;
}

export interface OrderSummary {
  order_request_id: string;
  client_order_id: string;
  account_id: string;
  side: string;
  order_type: string;
  status: string;
  requested_quantity: number;
  requested_price: number | null;
  symbol: string | null;
  instrument_name: string | null;
  correlation_id: string;
  trade_decision_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  version: number;
}

export interface OrderDetail extends OrderSummary {
  instrument_id: string | null;
  filled_qty: string | null;
  avg_fill_price: string | null;
  decision_context_id: string | null;
  error_message: string | null;
  broker_order_id: string | null;
  broker_id: string | null;
}

export interface OrderEvent {
  order_state_event_id: string;
  previous_status: string | null;
  new_status: string;
  event_source: string;
  event_timestamp: string;
  reason_code: string | null;
  correlation_id?: string | null;
  created_at?: string | null;
}

export interface BrokerOrderView {
  broker_order_id: string;
  order_request_id: string;
  broker_name: string;
  broker_status: string;
  broker_native_order_id: string | null;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface AuditLogEntry {
  log_id: string;
  correlation_id: string;
  event_type: string;
  summary: string;
  timestamp: string;
}

export interface ReconciliationRunSummary {
  reconciliation_run_id: string;
  account_id: string;
  trigger_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  mismatch_count: number;
  isActive: boolean;
  /** 분류된 실패 사유 label (historical failed run에만 설정) */
  failure_reason?: string | null;
  /** summary_json.error 원문 */
  summary_error?: string | null;
  /** 이 run에 연결된 order link 수 */
  order_count?: number;
}

export interface BlockingLockStatus {
  account_id: string;
  strategy_id: string;
  locked_at: string;
  is_active: boolean;
  side: string;
  reason: string;
  locked_by_run_id: string;
}

export interface ReconciliationSummary {
  active_locks_count: number;
  incomplete_recon_count: number;
  recent_active_locks: BlockingLockStatus[];
  recent_incomplete_runs: ReconciliationRunSummary[];
  generated_at: string;
  activeIssueCount: number;
  historicalFailedCount: number;
  recentActiveIssues: ReconciliationRunSummary[];
}

export interface AccountSummary {
  account_id: string;
  client_id: string;
  broker_account_id: string;
  account_alias: string | null;
  account_masked: string | null;
  broker_account_ref: string | null;
  broker_account_code: string | null;
  account_code: string | null;
  environment: string;
  status: string;
  risk_profile: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
}

export interface PositionSnapshotView {
  position_snapshot_id: string;
  account_id: string;
  instrument_id: string;
  quantity: number;
  average_price: number;
  market_price: number;
  unrealized_pnl: number | null;
  purchase_amount: number | null;
  evaluation_amount: number | null;
  source_of_truth: string;
  snapshot_at: string;
  // ── Resolved instrument display fields (enriched at query time) ──
  symbol: string | null;
  instrument_name: string | null;
}

export interface CashBalanceSnapshotView {
  cash_balance_snapshot_id: string;
  account_id: string;
  currency: string;
  available_cash: number;
  settled_cash: number;
  unsettled_cash: number;
  // ── KIS output2 계좌 총괄 필드 ──
  // total_asset: KIS tot_evlu_amt (총평가금액)
  // settlement_amount: KIS prvs_rcdl_excc_amt (가수도정산금액, D+2 예수금 기준)
  // total_unrealized_pnl: KIS evlu_pfls_smtl_amt (평가손익합계금액)
  total_asset?: number;
  settlement_amount?: number;
  total_unrealized_pnl?: number;
  source_of_truth: string;
  snapshot_at: string;
}

export type AlignmentStatus = "aligned" | "partial" | "unknown";

export type AlignmentDetail =
  | "same_run"
  | "after_hours_cash_updated"
  | "cash_only"
  | "partial_position_only"
  | "timestamp_proximity"
  | "unknown";

export interface AccountSnapshotResponse {
  account_id: string;
  positions: PositionSnapshotView[];
  cash_balance: CashBalanceSnapshotView | null;
  alignment_status: AlignmentStatus;
  positions_snapshot_at: string | null;
  cash_snapshot_at: string | null;
  /** 어떤 sync_run 기준인지 나타내는 UUID (truncated for display) */
  snapshot_sync_run_id: string | null;
  /** 상세 alignment 구분: same_run | after_hours_cash_updated | cash_only | partial_position_only | timestamp_proximity | unknown */
  alignment_detail: AlignmentDetail;
  /** alignment_detail 값에 대한 사람이 읽기 쉬운 설명 */
  alignment_detail_description?: string;
}

export interface ClientDetail {
  client_id: string;
  client_code: string;
  name: string;
  status: string;
  base_currency: string;
  created_at: string;
  updated_at: string | null;
}

export interface InstrumentDetail {
  instrument_id: string;
  symbol: string;
  market_code: string;
  currency: string;
  instrument_type: string;
  tick_size: string;
  lot_size: number;
}

export interface TradeDecisionDetail {
  trade_decision_id: string;
  decision_context_id: string;
  decision_type: string;
  side: string;
  strategy_id: string;
  symbol: string;
  instrument_name: string | null;
  market: string;
  entry_style: string;
  created_at: string;
  entry_price: number | null;
  quantity: number | null;
  max_order_value: number | null;
  confidence: number | null;
  rationale_summary: string | null;
  source_type: string | null;
  decision_json?: Record<string, unknown>;
  // ── Pipeline stop / order exposure ──
  order_request_id: string | null;
  order_status: string | null;

  // ── Execution Attempt status (P2: LEFT JOIN LATERAL from execution_attempts) ──
  execution_attempt_status: string | null;

  // ── Latest execution attempt summary (Phase 5) ──
  latest_execution_attempt_id: string | null;
  latest_stop_phase: string | null;
  latest_stop_reason: string | null;
  latest_completed_at: string | null;
  latest_phase_count: number | null;

  execution_status: string | null;
}

export interface PaginatedTradeDecisionsResponse {
  items: TradeDecisionDetail[];
  total: number;
  limit: number;
  offset: number;
}

export interface DecisionContextDetail {
  decision_context_id: string;
  account_id: string;
  strategy_id: string;
  config_version_id: string;
  market_timestamp: string;
  correlation_id: string;
  trading_session_id: string | null;
  created_at: string | null;
}

export interface AgentRunResponse {
  agent_run_id: string;
  decision_context_id: string;
  agent_type: string;
  started_at: string;
  model_id: string | null;
  prompt_id: string | null;
  temperature: number | null;
  seed: number | null;
  raw_output_uri: string | null;
  structured_output_json: Record<string, unknown> | null;
  status: string;
  completed_at: string | null;
  created_at: string | null;
}

/* ───────────────────────────────────────────
 * Broker Capacity Inspection types
 * ─────────────────────────────────────────── */

export interface BucketSnapshot {
  remaining: number;
  capacity: number;
  refill_rate: number;
  utilization: number;
}

export interface WsSubscriptionSnapshot {
  max_subscriptions: number;
  critical_limit: number;
  optional_limit: number;
  current_critical: number;
  current_optional: number;
  total_used: number;
  remaining: number;
  ws_connected: boolean;
}

export interface BrokerCapacityResponse {
  broker_name: string;
  environment: string;
  rest_budget: Record<string, BucketSnapshot>;
  can_accept_new_entries: boolean;
  websocket: WsSubscriptionSnapshot;
  market_data_subscriptions: number;
  order_event_accounts: string[];
  generated_at: string;
}

/* ───────────────────────────────────────────
 * Enum Metadata types
 * ─────────────────────────────────────────── */

export interface EnumValueMetadataSchema {
  value: string;
  label: string;
  description: string | null;
  broker_code: string | null;
  supported: boolean;
}

export interface EnumFieldMetadataSchema {
  field: string;
  type: string;
  values: EnumValueMetadataSchema[];
}

export interface EnumMetadataListResponse {
  fields: EnumFieldMetadataSchema[];
}

/* ───────────────────────────────────────────
 * Snapshot Sync Run types
 * ─────────────────────────────────────────── */

export interface SnapshotSyncRunSummary {
  snapshot_sync_run_id: string;
  trigger_type: string;
  scope: string;
  dry_run: boolean;
  total_accounts: number;
  succeeded_accounts: number;
  partial_accounts: number;
  failed_accounts: number;
  skipped_accounts: number;
  positions_synced_total: number;
  positions_skipped_total: number;
  cash_synced_count: number;
  error_count: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  after_hours: boolean;
  env_filter: string | null;
  status_filter: string | null;
  summary_json: Record<string, unknown> | null;
}

export interface SnapshotSyncRunHealthSummary {
  last_run_started_at: string | null;
  last_run_completed_at: string | null;
  last_status: string | null;
  last_successful_run_at: string | null;
  consecutive_failures: number;
  is_stale: boolean;
  stale_threshold_seconds: number;
  after_hours: boolean;
}

/* ───────────────────────────────────────────
 * API response wrapper types
 * ─────────────────────────────────────────── */

export interface MarketSessionSummary {
  id: number;
  run_date: string;
  is_trading_day: boolean;
  opnd_yn: string | null;
  bzdy_yn: string | null;
  tr_day_yn: string | null;
  market_phase: string | null;
  raw_opnd_yn: string | null;
  raw_mkop_cls_code: string | null;
  raw_antc_mkop_cls_code: string | null;
  source: string | null;
  reason: string | null;
  checked_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SessionEventSummary {
  id: number;
  market_session_id: number;
  previous_phase: string | null;
  new_phase: string | null;
  trigger_source: string | null;
  metadata: Record<string, unknown> | null;
  occurred_at: string;
  created_at: string | null;
}

export interface SchedulerStatusResponse {
  status: 'ok' | 'no_data';
  data: MarketSessionSummary | null;
  healthy: boolean;
  stale_seconds: number | null;
}

export interface SessionEventsResponse {
  status: 'ok';
  data: SessionEventSummary[];
}

export interface ExternalEventView {
  event_id: string;
  event_type: string;
  source_name: string;
  source_reliability_tier: string;
  symbol: string | null;
  headline: string | null;
  body_summary: string | null;
  published_at: string;
  created_at: string | null;
}

export interface ExternalEventsResponse {
  status: string;
  data: ExternalEventView[];
}

export interface ExecutionAttemptDetail {
  execution_attempt_id: string;
  trade_decision_id: string;
  decision_context_id: string;
  status: string;
  stop_phase: string | null;
  stop_reason: string | null;
  phase_trace: Record<string, unknown>[] | null;
  order_request_id: string | null;
  started_at: string;
  completed_at: string | null;
  created_at: string | null;
}

export interface ExecutionAttemptListResponse {
  status: string;
  data: ExecutionAttemptDetail[];
}

export interface ApiError {
  detail: string;
}
