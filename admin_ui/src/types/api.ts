/* ───────────────────────────────────────────
 * TypeScript interfaces matching backend schemas
 * Based on src/agent_trading/api/schemas.py
 * ─────────────────────────────────────────── */

export interface HealthResponse {
  status: string;
  database: string;
  mode: string;
}

export interface OrderSummary {
  order_request_id: string;
  symbol: string;
  side: string;
  order_type: string;
  qty: string;
  status: string;
  created_at: string;
  client_id: string;
  strategy_code: string;
}

export interface OrderDetail extends OrderSummary {
  updated_at: string | null;
  filled_qty: string | null;
  avg_fill_price: string | null;
  decision_context_id: string | null;
  trade_decision_id: string | null;
  error_message: string | null;
  client_order_id: string | null;
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

export interface AccountSummary {
  account_id: string;
  account_code: string;
  client_code: string;
  account_type: string;
  status: string;
  currency: string;
}

export interface PositionSnapshotView {
  position_snapshot_id: string;
  account_id: string;
  symbol: string;
  side: string;
  quantity: string;
  avg_price: string;
  current_price: string;
  pnl: string;
  snapshot_time: string;
}

export interface CashBalanceSnapshotView {
  cash_balance_snapshot_id: string;
  account_id: string;
  currency: string;
  available_amount: string;
  total_amount: string;
  snapshot_time: string;
}

export interface ClientDetail {
  client_id: string;
  client_code: string;
  client_name: string;
  status: string;
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
  intent: string;
  ticker: string;
  side: string;
  qty: string;
  confidence: number;
  agent_label: string;
  created_at: string;
}

export interface DecisionContextDetail {
  decision_context_id: string;
  strategy_code: string;
  client_id: string;
  session_id: string | null;
  timestamp: string;
  agent_count: number;
}

/* ───────────────────────────────────────────
 * API response wrapper types
 * ─────────────────────────────────────────── */

export interface ApiError {
  detail: string;
}
