import type {
  HealthResponse,
  OrderSummary,
  ReconciliationRunSummary,
  BlockingLockStatus,
  ReconciliationSummary,
  OrderDetail,
  OrderEvent,
  BrokerOrderView,
  AccountSummary,
  PositionSnapshotView,
  CashBalanceSnapshotView,
  ClientDetail,
  TradeDecisionDetail,
  DecisionContextDetail,
  AgentRunResponse,
  BrokerCapacityResponse,
} from "../../types/api";

export const mockHealthOk: HealthResponse = {
  status: "ok",
  database: "connected",
  runtime_mode: "in_memory",
};

export const mockHealthDegraded: HealthResponse = {
  status: "degraded",
  database: "disconnected",
  runtime_mode: "postgres",
};

export const mockOrders: OrderSummary[] = [
  {
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
    client_order_id: "client-ref-001",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    side: "buy",
    order_type: "limit",
    status: "filled",
    requested_quantity: 100,
    requested_price: null,
    symbol: "AAPL",
    correlation_id: "corr-001",
    trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td1",
    created_at: "2026-05-05T00:00:00Z",
    updated_at: "2026-05-05T00:00:10Z",
    version: 1,
  },
  {
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0002",
    client_order_id: "client-ref-002",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    side: "sell",
    order_type: "market",
    status: "pending",
    requested_quantity: 50,
    requested_price: null,
    symbol: "TSLA",
    correlation_id: "corr-002",
    trade_decision_id: null,
    created_at: "2026-05-05T00:01:00Z",
    updated_at: null,
    version: 1,
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

export const mockReconciliationSummary: ReconciliationSummary = {
  active_locks_count: 1,
  incomplete_recon_count: 1,
  recent_active_locks: [
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
  ],
  recent_incomplete_runs: [
    {
      run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r2",
      account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
      status: "in_progress",
      started_at: "2026-05-05T00:01:00Z",
      completed_at: null,
      order_mismatches: 1,
      position_mismatches: 0,
    },
  ],
};

/** Dashboard parallel API responses — order matches fetchAll() call order */
export const dashboardApiResponses = [
  mockHealthOk,
  mockOrders,
];

/** A valid token for testing */
export const VALID_TOKEN = "test-token-valid-000000000000";

/* ──────────────────────────────────────────────
 * Plan 50 fixtures — OrderDetail, Accounts, Decisions
 * ────────────────────────────────────────────── */

export const mockOrderDetail: OrderDetail = {
  order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
  client_order_id: "client-ref-001",
  account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
  side: "buy",
  order_type: "limit",
  status: "filled",
  requested_quantity: 100,
  requested_price: null,
  symbol: "AAPL",
  correlation_id: "corr-001",
  trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td1",
  created_at: "2026-05-05T00:00:00Z",
  updated_at: "2026-05-05T00:00:10Z",
  version: 1,
  instrument_id: null,
  filled_qty: "100",
  avg_fill_price: "185.50",
  decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
  error_message: null,
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

export const mockClients: ClientDetail[] = [
  {
    client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
    client_code: "CLIENT1",
    name: "Test Client 1",
    status: "active",
    base_currency: "KRW",
    created_at: "2026-05-05T00:00:00Z",
    updated_at: null,
  },
];

export const mockAccounts: AccountSummary[] = [
  {
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
    broker_account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00b1",
    account_alias: "Paper Account 1",
    account_masked: "****1234",
    broker_account_ref: "50045678",
    broker_account_code: "KIS-PAPER-****5678",
    account_code: "CLIENT1-PAPER-PAPER",
    environment: "paper",
    status: "active",
    risk_profile: null,
    created_at: "2026-05-05T00:00:00Z",
    updated_at: null,
  },
  {
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a2",
    client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
    broker_account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00b2",
    account_alias: "Live Account 1",
    account_masked: "****5678",
    broker_account_ref: "50091234",
    broker_account_code: "KIS-LIVE-****1234",
    account_code: "CLIENT1-LIVE-LIVE",
    environment: "live",
    status: "active",
    risk_profile: null,
    created_at: "2026-05-05T00:00:00Z",
    updated_at: null,
  },
  {
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a3",
    client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
    broker_account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00b3",
    account_alias: "Locked Paper Account",
    account_masked: "****9999",
    broker_account_ref: "50099999",
    broker_account_code: "KIS-PAPER-****9999",
    account_code: "CLIENT1-PAPER-LOCKED",
    environment: "paper",
    status: "locked",
    risk_profile: null,
    created_at: "2026-05-05T00:00:00Z",
    updated_at: null,
  },
];

export const mockAccountsNoPositions: AccountSummary[] = [
  {
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a4",
    client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00c1",
    broker_account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00b4",
    account_alias: "Empty Account",
    account_masked: "****0000",
    broker_account_ref: "50000000",
    broker_account_code: "KIS-PAPER-****0000",
    account_code: "CLIENT1-PAPER-EMPTY",
    environment: "paper",
    status: "active",
    risk_profile: null,
    created_at: "2026-05-05T00:00:00Z",
    updated_at: null,
  },
];

export const mockPositions: PositionSnapshotView[] = [
  {
    position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00p1",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    instrument_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i1",
    quantity: 100,
    average_price: 180.0,
    market_price: 185.5,
    unrealized_pnl: 550.0,
    source_of_truth: "broker",
    snapshot_at: "2026-05-05T00:00:00Z",
  },
  {
    position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00p2",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    instrument_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i2",
    quantity: 50,
    average_price: 250.0,
    market_price: 245.0,
    unrealized_pnl: 250.0,
    source_of_truth: "broker",
    snapshot_at: "2026-05-05T00:00:00Z",
  },
];

export const mockPositionsForLocked: PositionSnapshotView[] = [
  {
    position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00p3",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a3",
    instrument_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i1",
    quantity: 10,
    average_price: 200.0,
    market_price: 210.0,
    unrealized_pnl: 100.0,
    source_of_truth: "broker",
    snapshot_at: "2026-05-05T00:00:00Z",
  },
];

export const mockCashBalance: CashBalanceSnapshotView = {
  cash_balance_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00cb1",
  account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
  currency: "USD",
  available_cash: 50000.0,
  settled_cash: 100000.0,
  unsettled_cash: 0,
  source_of_truth: "broker",
  snapshot_at: "2026-05-05T00:00:00Z",
};

export const mockCashBalanceForLocked: CashBalanceSnapshotView = {
  cash_balance_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00cb2",
  account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a3",
  currency: "KRW",
  available_cash: 1000000.0,
  settled_cash: 2000000.0,
  unsettled_cash: 0,
  source_of_truth: "broker",
  snapshot_at: "2026-05-05T00:00:00Z",
};

export const mockCashBalanceNull: CashBalanceSnapshotView | null = null;

/** Dashboard — incomplete reconciliation run (status !== "completed") */
export const mockIncompleteReconRuns: ReconciliationRunSummary[] = [
  {
    run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r2",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    status: "in_progress",
    started_at: "2026-05-05T00:00:00Z",
    completed_at: null,
    order_mismatches: 2,
    position_mismatches: 1,
  },
];

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

export const mockAgentRuns: AgentRunResponse[] = [
  {
    agent_run_id: "rrrrrrrr-bbbb-cccc-dddd-eeeeeeee00r1",
    decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    agent_type: "event_interpretation",
    started_at: "2026-05-05T00:00:02Z",
    status: "completed",
    structured_output_json: { signal: "bullish", confidence: 0.82, summary: "Strong earnings momentum" },
    completed_at: "2026-05-05T00:00:05Z",
    model_id: null,
    prompt_id: null,
    temperature: null,
    seed: null,
    raw_output_uri: null,
    created_at: null,
  },
  {
    agent_run_id: "rrrrrrrr-bbbb-cccc-dddd-eeeeeeee00r2",
    decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    agent_type: "ai_risk",
    started_at: "2026-05-05T00:00:06Z",
    status: "completed",
    structured_output_json: { risk_score: 0.35, max_order_value: 20000, approved: true },
    completed_at: "2026-05-05T00:00:09Z",
    model_id: null,
    prompt_id: null,
    temperature: null,
    seed: null,
    raw_output_uri: null,
    created_at: null,
  },
  {
    agent_run_id: "rrrrrrrr-bbbb-cccc-dddd-eeeeeeee00r3",
    decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    agent_type: "final_decision_composer",
    started_at: "2026-05-05T00:00:10Z",
    status: "completed",
    structured_output_json: { decision: "buy", quantity: 100, entry_price: 185.50 },
    completed_at: "2026-05-05T00:00:12Z",
    model_id: null,
    prompt_id: null,
    temperature: null,
    seed: null,
    raw_output_uri: null,
    created_at: null,
  },
];

/* ──────────────────────────────────────────────
 * Broker Capacity fixtures
 * ────────────────────────────────────────────── */

export const mockBrokerCapacity: BrokerCapacityResponse = {
  broker_name: "koreainvestment",
  environment: "paper",
  rest_budget: {
    auth: { remaining: 1, capacity: 1, refill_rate: 0.1, utilization: 0 },
    order: { remaining: 5, capacity: 8, refill_rate: 0.5, utilization: 0.375 },
    inquiry: { remaining: 15, capacity: 20, refill_rate: 2.0, utilization: 0.25 },
    reconciliation: { remaining: 3, capacity: 5, refill_rate: 0.5, utilization: 0.4 },
    market_data: { remaining: 10, capacity: 10, refill_rate: 1.0, utilization: 0 },
  },
  can_accept_new_entries: true,
  websocket: {
    max_subscriptions: 50,
    critical_limit: 40,
    optional_limit: 10,
    current_critical: 5,
    current_optional: 2,
    total_used: 7,
    remaining: 43,
    ws_connected: true,
  },
  market_data_subscriptions: 3,
  order_event_accounts: ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1"],
};
