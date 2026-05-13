/* ───────────────────────────────────────────
 * TypeScript interfaces matching backend schemas
 * Based on src/agent_trading/api/schemas.py
 * ─────────────────────────────────────────── */

export interface HealthResponse {
  status: string;
  database: string;
  runtime_mode: string;
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
  event_id: string;
  order_request_id: string;
  from_status: string;
  to_status: string;
  reason: string;
  timestamp: string;
}

export interface BrokerOrderView {
  broker_order_id: string;
  order_request_id: string;
  broker_id: string;
  native_order_id: string | null;
  status: string;
  submitted_at: string | null;
}

export interface AuditLogEntry {
  log_id: string;
  correlation_id: string;
  event_type: string;
  summary: string;
  timestamp: string;
}

export interface ReconciliationRunSummary {
  run_id: string;
  account_id: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  order_mismatches: number;
  position_mismatches: number;
}

export interface BlockingLockStatus {
  lock_id: string;
  lock_key: string;
  account_id: string;
  symbol: string;
  strategy_code: string;
  lock_type: string;
  acquired_at: string;
  expires_at: string;
  is_expired: boolean;
}

export interface ReconciliationSummary {
  active_locks_count: number;
  incomplete_recon_count: number;
  recent_active_locks: BlockingLockStatus[];
  recent_incomplete_runs: ReconciliationRunSummary[];
  generated_at: string;
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
  source_of_truth: string;
  snapshot_at: string;
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
  market: string;
  entry_style: string;
  created_at: string;
  entry_price: number | null;
  quantity: number | null;
  max_order_value: number | null;
  confidence: number | null;
  rationale_summary: string | null;
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
 * API response wrapper types
 * ─────────────────────────────────────────── */

export interface ApiError {
  detail: string;
}
