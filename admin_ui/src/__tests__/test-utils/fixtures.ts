import type {
  HealthResponse,
  OrderSummary,
  ReconciliationRunSummary,
  BlockingLockStatus,
  OrderDetail,
  OrderEvent,
  BrokerOrderView,
  AccountSummary,
  PositionSnapshotView,
  CashBalanceSnapshotView,
  TradeDecisionDetail,
  DecisionContextDetail,
} from "../../types/api";

export const mockHealthOk: HealthResponse = {
  status: "ok",
  database: "connected",
  mode: "in_memory",
};

export const mockHealthDegraded: HealthResponse = {
  status: "degraded",
  database: "disconnected",
  mode: "in_memory",
};

export const mockOrders: OrderSummary[] = [
  {
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
    symbol: "AAPL",
    side: "buy",
    order_type: "limit",
    qty: "100",
    status: "filled",
    created_at: "2026-05-05T00:00:00Z",
    client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
    strategy_code: "strat-a",
  },
  {
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0002",
    symbol: "TSLA",
    side: "sell",
    order_type: "market",
    qty: "50",
    status: "pending",
    created_at: "2026-05-05T00:01:00Z",
    client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
    strategy_code: "strat-b",
  },
];

export const mockReconciliationRuns: ReconciliationRunSummary[] = [
  {
    run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r1",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    status: "completed",
    started_at: "2026-05-05T00:00:00Z",
    completed_at: "2026-05-05T00:00:05Z",
    order_mismatches: 0,
    position_mismatches: 0,
  },
];

export const mockLocks: BlockingLockStatus[] = [
  {
    lock_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00l1",
    lock_key: "manual-review-account-a1",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    symbol: "AAPL",
    strategy_code: "strat-a",
    lock_type: "manual",
    acquired_at: "2026-05-05T00:00:00Z",
    expires_at: "2026-05-06T00:00:00Z",
    is_expired: false,
  },
];

/** Dashboard parallel API responses — order matches fetchAll() call order */
export const dashboardApiResponses = [
  mockHealthOk,
  mockOrders,
  mockReconciliationRuns,
  mockLocks,
];

/** A valid token for testing */
export const VALID_TOKEN = "test-token-valid-000000000000";

/* ──────────────────────────────────────────────
 * Plan 50 fixtures — OrderDetail, Accounts, Decisions
 * ────────────────────────────────────────────── */

export const mockOrderDetail: OrderDetail = {
  order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
  symbol: "AAPL",
  side: "buy",
  order_type: "limit",
  qty: "100",
  status: "filled",
  created_at: "2026-05-05T00:00:00Z",
  client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
  strategy_code: "strat-a",
  updated_at: "2026-05-05T00:00:10Z",
  filled_qty: "100",
  avg_fill_price: "185.50",
  decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
  trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td1",
  error_message: null,
  client_order_id: "client-ref-001",
  broker_order_id: "broker-ref-001",
  broker_id: "KIS",
};

/** OrderDetail variant without decision links — for testing conditional rendering */
export const mockOrderDetailNoDecision: OrderDetail = {
  ...mockOrderDetail,
  decision_context_id: null,
  trade_decision_id: null,
};

export const mockOrderEvents: OrderEvent[] = [
  {
    event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00e1",
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
    from_status: "pending",
    to_status: "submitted",
    reason: "Order submitted to broker",
    timestamp: "2026-05-05T00:00:01Z",
  },
  {
    event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00e2",
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
    from_status: "submitted",
    to_status: "filled",
    reason: "Fill confirmed by broker",
    timestamp: "2026-05-05T00:00:05Z",
  },
];

export const mockBrokerOrders: BrokerOrderView[] = [
  {
    broker_order_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00b1",
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
    broker_id: "KIS",
    native_order_id: "KIS-NATIVE-001",
    status: "filled",
    submitted_at: "2026-05-05T00:00:02Z",
  },
];

export const mockAccounts: AccountSummary[] = [
  {
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    account_code: "ACC-001",
    client_code: "CLIENT-001",
    account_type: "cash",
    status: "active",
    currency: "USD",
  },
  {
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a2",
    account_code: "ACC-002",
    client_code: "CLIENT-001",
    account_type: "margin",
    status: "active",
    currency: "USD",
  },
];

export const mockPositions: PositionSnapshotView[] = [
  {
    position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00p1",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    symbol: "AAPL",
    side: "long",
    quantity: "100",
    avg_price: "180.00",
    current_price: "185.50",
    pnl: "+550.00",
    snapshot_time: "2026-05-05T00:00:00Z",
  },
  {
    position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00p2",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    symbol: "TSLA",
    side: "short",
    quantity: "50",
    avg_price: "250.00",
    current_price: "245.00",
    pnl: "+250.00",
    snapshot_time: "2026-05-05T00:00:00Z",
  },
];

export const mockCashBalance: CashBalanceSnapshotView = {
  cash_balance_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00cb1",
  account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
  currency: "USD",
  available_amount: "50000.00",
  total_amount: "100000.00",
  snapshot_time: "2026-05-05T00:00:00Z",
};

export const mockTradeDecisions: TradeDecisionDetail[] = [
  {
    trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td1",
    decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    decision_type: "auto_execute",
    side: "buy",
    strategy_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s1",
    symbol: "AAPL",
    market: "NASDAQ",
    entry_style: "limit",
    created_at: "2026-05-05T00:00:00Z",
    entry_price: 185.50,
    quantity: 100,
    max_order_value: 20000,
    confidence: 0.85,
    rationale_summary: "Strong earnings outlook for AAPL",
  },
  {
    trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td2",
    decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    decision_type: "hold",
    side: "hold",
    strategy_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s1",
    symbol: "TSLA",
    market: "NASDAQ",
    entry_style: "market",
    created_at: "2026-05-05T00:00:01Z",
    entry_price: null,
    quantity: 0,
    max_order_value: 0,
    confidence: 0.55,
    rationale_summary: "Market uncertainty — holding position",
  },
  {
    trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td3",
    decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc2",
    decision_type: "auto_execute",
    side: "sell",
    strategy_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s2",
    symbol: "MSFT",
    market: "NASDAQ",
    entry_style: "market",
    created_at: "2026-05-05T00:00:02Z",
    entry_price: 420.00,
    quantity: 50,
    max_order_value: 22000,
    confidence: 0.25,
    rationale_summary: "Stop-loss triggered for MSFT",
  },
];

export const mockDecisionContext: DecisionContextDetail = {
  decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
  account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
  strategy_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s1",
  config_version_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00cv1",
  market_timestamp: "2026-05-05T00:00:00Z",
  correlation_id: "corr-001",
  trading_session_id: "session-001",
  created_at: "2026-05-05T00:00:00Z",
};
