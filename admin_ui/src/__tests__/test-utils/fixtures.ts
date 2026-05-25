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
  EnumMetadataListResponse,
  ExternalEventView,
  PaginatedTradeDecisionsResponse,
} from "../../types/api";

export const mockHealthOk: HealthResponse = {
  status: "ok",
  version: "1.0.0",
  timestamp: "2026-05-16T00:00:00Z",
  database: "connected",
  runtime_mode: "in_memory",
  snapshot_sync_detail: null,
  snapshot_sync_stale: null,
  snapshot_sync_last_successful_run_at: null,
  snapshot_sync_consecutive_failures: null,
  scheduler: null,
};

export const mockHealthDegraded: HealthResponse = {
  status: "degraded",
  version: "1.0.0",
  timestamp: "2026-05-16T00:00:00Z",
  database: "disconnected",
  runtime_mode: "postgres",
  snapshot_sync_detail: null,
  snapshot_sync_stale: null,
  snapshot_sync_last_successful_run_at: null,
  snapshot_sync_consecutive_failures: null,
  scheduler: null,
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
    instrument_name: null,
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
    status: "pending_submit",
    requested_quantity: 50,
    requested_price: null,
    symbol: "TSLA",
    instrument_name: null,
    correlation_id: "corr-002",
    trade_decision_id: null,
    created_at: "2026-05-05T00:01:00Z",
    updated_at: null,
    version: 1,
  },
];

export const mockReconciliationRuns: ReconciliationRunSummary[] = [
  {
    reconciliation_run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r1",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    trigger_type: "manual",
    status: "completed",
    started_at: "2026-05-05T00:00:00Z",
    completed_at: "2026-05-05T00:00:05Z",
    mismatch_count: 0,
    isActive: false,
  },
];

export const mockLocks: BlockingLockStatus[] = [
  {
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    strategy_id: "strat-a",
    locked_at: "2026-05-05T00:00:00Z",
    is_active: true,
    side: "buy",
    reason: "Manual review required",
    locked_by_run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r1",
  },
];

export const mockReconciliationSummary: ReconciliationSummary = {
  active_locks_count: 1,
  incomplete_recon_count: 1,
  activeIssueCount: 0,
  historicalFailedCount: 0,
  recentActiveIssues: [],
  recent_active_locks: [
    {
      account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
      strategy_id: "strat-a",
      locked_at: "2026-05-05T00:00:00Z",
      is_active: true,
      side: "buy",
      reason: "Manual review required",
      locked_by_run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r1",
    },
  ],
  recent_incomplete_runs: [
    {
      reconciliation_run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r2",
      account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
      trigger_type: "scheduled",
      status: "in_progress",
      started_at: "2026-05-05T00:01:00Z",
      completed_at: null,
      mismatch_count: 1,
      isActive: false,
    },
  ],
  generated_at: "2026-05-08T05:00:00Z",
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
  instrument_name: null,
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
    order_state_event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00e1",
    previous_status: null,
    new_status: "submitted",
    event_source: "INTERNAL",
    event_timestamp: "2026-05-05T00:00:01Z",
    reason_code: null,
  },
  {
    order_state_event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00e2",
    previous_status: "submitted",
    new_status: "filled",
    event_source: "BROKER",
    event_timestamp: "2026-05-05T00:00:05Z",
    reason_code: "FILL_CONFIRMED",
  },
];

export const mockBrokerOrders: BrokerOrderView[] = [
  {
    broker_order_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00b1",
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
    broker_name: "KIS",
    broker_status: "filled",
    broker_native_order_id: "KIS-NATIVE-001",
    last_synced_at: "2026-05-05T00:00:02Z",
    created_at: "2026-05-05T00:00:00Z",
    updated_at: "2026-05-05T00:00:02Z",
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
    purchase_amount: 18000.0,
    evaluation_amount: 18550.0,
    source_of_truth: "broker",
    snapshot_at: "2026-05-05T00:00:00Z",
    symbol: "AAPL",
    instrument_name: "Apple Inc.",
  },
  {
    position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00p2",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    instrument_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i2",
    quantity: 50,
    average_price: 250.0,
    market_price: 245.0,
    unrealized_pnl: 250.0,
    purchase_amount: 12500.0,
    evaluation_amount: 12250.0,
    source_of_truth: "broker",
    snapshot_at: "2026-05-05T00:00:00Z",
    symbol: "MSFT",
    instrument_name: "Microsoft Corporation",
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
    purchase_amount: 2000.0,
    evaluation_amount: 2100.0,
    source_of_truth: "broker",
    snapshot_at: "2026-05-05T00:00:00Z",
    symbol: "AAPL",
    instrument_name: "Apple Inc.",
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
    reconciliation_run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00r2",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    trigger_type: "post_trade",
    status: "in_progress",
    started_at: "2026-05-05T00:00:00Z",
    completed_at: null,
    mismatch_count: 3,
    isActive: false,
  },
];

export const mockTradeDecisions: PaginatedTradeDecisionsResponse = {
  items: [
    {
      trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td1",
      decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
      decision_type: "auto_execute",
      side: "buy",
      strategy_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s1",
      symbol: "AAPL",
      instrument_name: null,
      market: "NASDAQ",
      entry_style: "limit",
      created_at: "2026-05-05T00:00:00Z",
      entry_price: 185.50,
      quantity: 100,
      max_order_value: 20000,
      confidence: 0.85,
      rationale_summary: "Strong earnings outlook for AAPL",
      source_type: null,
      order_request_id: null,
      order_status: null,
      execution_attempt_status: null,
      latest_execution_attempt_id: null,
      latest_stop_phase: null,
      latest_stop_reason: null,
      latest_completed_at: null,
      latest_phase_count: null,
      execution_status: null,
      decision_json: {
        event_bias: "Positive earnings surprise expected",
        event_conflict: false,
        event_reason_codes: ['foreign_investor_selling', 'price_decline'],
        risk_reason_codes: ['high_volatility'],
        reason_codes: ['FDC_APPROVED'],
        opposing_evidence: ['low_liquidity'],
        confidence: 0.85,
        conviction: 0.75,
        risk_opinion: "Low risk — strong fundamentals",
        risk_flags: [],
        risk_score: 25.0,
      },
    },
    {
      trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td2",
      decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
      decision_type: "hold",
      side: "hold",
      strategy_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s1",
      symbol: "TSLA",
      instrument_name: null,
      market: "NASDAQ",
      entry_style: "market",
      created_at: "2026-05-05T00:00:01Z",
      entry_price: null,
      quantity: 0,
      max_order_value: 0,
      confidence: 0.55,
      rationale_summary: "Market uncertainty — holding position",
      source_type: null,
      order_request_id: null,
      order_status: null,
      execution_attempt_status: null,
      latest_execution_attempt_id: null,
      latest_stop_phase: null,
      latest_stop_reason: null,
      latest_completed_at: null,
      latest_phase_count: null,
      execution_status: null,
      decision_json: {
        event_bias: "Neutral — no significant catalysts",
        event_conflict: true,
        event_reason_codes: ['foreign_investor_selling', 'price_decline'],
        risk_opinion: "Medium risk — market volatility",
        risk_flags: ["high_volatility", "low_liquidity"],
      },
    },
    {
      trade_decision_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td3",
      decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc2",
      decision_type: "auto_execute",
      side: "sell",
      strategy_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s2",
      symbol: "MSFT",
      instrument_name: null,
      market: "NASDAQ",
      entry_style: "market",
      created_at: "2026-05-05T00:00:02Z",
      entry_price: 420.00,
      quantity: 50,
      max_order_value: 22000,
      confidence: 0.25,
      rationale_summary: "Stop-loss triggered for MSFT",
      source_type: null,
      order_request_id: null,
      order_status: null,
      execution_attempt_status: null,
      latest_execution_attempt_id: null,
      latest_stop_phase: null,
      latest_stop_reason: null,
      latest_completed_at: null,
      latest_phase_count: null,
      execution_status: null,
      decision_json: {
        event_bias: "Bearish — competitive pressure",
        event_conflict: false,
        event_reason_codes: ['foreign_investor_selling', 'price_decline'],
        risk_opinion: "High risk — stop-loss breach",
        risk_flags: ["stop_loss_breach"],
      },
    },
  ],
  total: 3,
  limit: 20,
  offset: 0,
};

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
  generated_at: "2026-05-08T05:00:00Z",
};

/**
 * Mock ``GET /metadata/enums`` response.
 *
 * Includes ``side``, ``order_type``, ``order_status``, ``decision_type``,
 * and ``entry_style`` fields with Korean labels.
 */
export const mockEnumMetadataResponse: EnumMetadataListResponse = {
  fields: [
    {
      field: "side",
      type: "Side",
      values: [
        { value: "buy", label: "매수", description: null, broker_code: null, supported: true },
        { value: "sell", label: "매도", description: null, broker_code: null, supported: true },
        { value: "hold", label: "보류", description: null, broker_code: null, supported: true },
      ],
    },
    {
      field: "order_type",
      type: "OrderType",
      values: [
        { value: "market", label: "시장가", description: null, broker_code: null, supported: true },
        { value: "limit", label: "지정가", description: null, broker_code: null, supported: true },
        { value: "stop", label: "스탑", description: null, broker_code: null, supported: false },
        { value: "stop_limit", label: "스탑 리밋", description: null, broker_code: null, supported: false },
      ],
    },
    {
      field: "order_status",
      type: "OrderStatus",
      values: [
        { value: "draft", label: "초안", description: null, broker_code: null, supported: true },
        { value: "validated", label: "검증됨", description: null, broker_code: null, supported: true },
        { value: "pending_submit", label: "제출 대기", description: null, broker_code: null, supported: true },
        { value: "submitted", label: "제출됨", description: null, broker_code: null, supported: true },
        { value: "acknowledged", label: "확인됨", description: null, broker_code: null, supported: true },
        { value: "partially_filled", label: "부분 체결", description: null, broker_code: null, supported: true },
        { value: "filled", label: "체결", description: null, broker_code: null, supported: true },
        { value: "cancel_pending", label: "취소 대기", description: null, broker_code: null, supported: true },
        { value: "cancelled", label: "취소됨", description: null, broker_code: null, supported: true },
        { value: "rejected", label: "거부됨", description: null, broker_code: null, supported: true },
        { value: "expired", label: "만료", description: null, broker_code: null, supported: true },
        { value: "reconcile_required", label: "조정 필요", description: null, broker_code: null, supported: true },
      ],
    },
    {
      field: "decision_type",
      type: "DecisionType",
      values: [
        { value: "auto_execute", label: "자동 실행", description: null, broker_code: null, supported: true },
        { value: "manual_review", label: "수동 검토", description: null, broker_code: null, supported: true },
        { value: "hold", label: "보류", description: null, broker_code: null, supported: true },
        { value: "escalate", label: "에스컬레이션", description: null, broker_code: null, supported: true },
      ],
    },
    {
      field: "entry_style",
      type: "EntryStyle",
      values: [
        { value: "market", label: "시장가", description: null, broker_code: null, supported: true },
        { value: "limit", label: "지정가", description: null, broker_code: null, supported: true },
        { value: "vwap", label: "VWAP", description: null, broker_code: null, supported: true },
        { value: "twap", label: "TWAP", description: null, broker_code: null, supported: true },
      ],
    },
    {
      field: "reason_code",
      type: "string",
      values: [
        { value: "BLOCKED", label: "차단됨", description: "Blocking lock에 의해 submit 차단", broker_code: null, supported: true },
        { value: "UNCERTAIN", label: "불확실 상태", description: "Broker 응답 불확실로 조정 필요", broker_code: null, supported: true },
        { value: "RECONCILE_RESOLVED", label: "조정 해소", description: "Broker 조회로 상태 확정", broker_code: null, supported: true },
        { value: "MANUAL_RESOLVE", label: "운영자 수동 해소", description: "관리자가 수동으로 상태 변경", broker_code: null, supported: true },
        { value: "manual_paper_resolution", label: "운영자 수동 해소", description: "관리자 수동 해소 (legacy)", broker_code: null, supported: true },
        { value: "WS_FILL", label: "WS 체결 수신", description: "WebSocket 실시간 체결 통보", broker_code: null, supported: true },
        { value: "FILL_CONFIRMED", label: "체결 확인", description: "체결 내역 확인 완료", broker_code: null, supported: true },
        { value: "REJECTED", label: "거부됨", description: "Broker 주문 거부", broker_code: null, supported: true },
      ],
    },
  ],
};

/* ───────────────────────────────────────────
 * Reconcile-required test fixtures
 * ─────────────────────────────────────────── */

/** 계정 ID (mockOrders/mockLocks와 동일한 계정) */
export const RECONCILE_ACCOUNT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1";

/** instrument_id: AAPL */
export const RECONCILE_INSTRUMENT_ID_AAPL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i1";

/** instrument_id: TSLA */
export const RECONCILE_INSTRUMENT_ID_TSLA = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i2";

/** 포지션이 반영된 reconcile_required 주문 */
export const mockReconcileRequiredWithPosition: OrderSummary = {
  order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00rq1",
  client_order_id: "client-reconcile-001",
  account_id: RECONCILE_ACCOUNT_ID,
  side: "buy",
  order_type: "limit",
  status: "reconcile_required",
  requested_quantity: 100,
  requested_price: 50000,
  symbol: "AAPL",
  instrument_name: null,
  correlation_id: "corr-reconcile-001",
  trade_decision_id: null,
  created_at: "2026-05-13T01:00:00Z",
  updated_at: "2026-05-13T01:05:00Z",
  version: 2,
};

/** 포지션이 반영되지 않은 reconcile_required 주문 */
export const mockReconcileRequiredNoPosition: OrderSummary = {
  order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00rq2",
  client_order_id: "client-reconcile-002",
  account_id: RECONCILE_ACCOUNT_ID,
  side: "sell",
  order_type: "market",
  status: "reconcile_required",
  requested_quantity: 50,
  requested_price: null,
  symbol: "TSLA",
  instrument_name: null,
  correlation_id: "corr-reconcile-002",
  trade_decision_id: null,
  created_at: "2026-05-13T02:00:00Z",
  updated_at: "2026-05-13T02:10:00Z",
  version: 2,
};

/** 포지션이 반영된 reconcile_required 주문 (수량/단가 정합) */
export const mockReconcileRequiredPositionMatched: OrderSummary = {
  order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00rq3",
  client_order_id: "client-reconcile-003",
  account_id: RECONCILE_ACCOUNT_ID,
  side: "buy",
  order_type: "limit",
  status: "reconcile_required",
  requested_quantity: 100,
  requested_price: 50000,
  symbol: "AAPL",
  instrument_name: null,
  correlation_id: "corr-reconcile-003",
  trade_decision_id: null,
  created_at: "2026-05-13T03:00:00Z",
  updated_at: "2026-05-13T03:05:00Z",
  version: 2,
};

/** reconcile_required 전용 BrokerOrderView */
export const mockBrokerOrderForReconcile: BrokerOrderView = {
  broker_order_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00bo1",
  order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00rq1",
  broker_name: "KIS",
  broker_status: "confirmed",
  broker_native_order_id: "KIS-NATIVE-001",
  last_synced_at: "2026-05-13T01:04:00Z",
  created_at: "2026-05-13T01:00:00Z",
  updated_at: "2026-05-13T01:04:00Z",
};

/** reconcile_required 계정의 포지션 스냅샷 (AAPL — 포지션 존재) */
export const mockPositionForReconcile: PositionSnapshotView = {
  position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00ps1",
  account_id: RECONCILE_ACCOUNT_ID,
  instrument_id: RECONCILE_INSTRUMENT_ID_AAPL,
  symbol: "AAPL",
  instrument_name: "Apple Inc.",
  quantity: 100,
  average_price: 50000,
  market_price: 50100,
  unrealized_pnl: 10000,
  purchase_amount: null,
  evaluation_amount: null,
  source_of_truth: "broker",
  snapshot_at: "2026-05-13T01:05:00Z",
};

/** reconcile_required 계정의 포지션 스냅샷 (TSLA — quantity 불일치) */
export const mockPositionForReconcilePartial: PositionSnapshotView = {
  position_snapshot_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00ps2",
  account_id: RECONCILE_ACCOUNT_ID,
  instrument_id: RECONCILE_INSTRUMENT_ID_TSLA,
  symbol: "TSLA",
  instrument_name: "Tesla Inc.",
  quantity: 10,
  average_price: 200000,
  market_price: 201000,
  unrealized_pnl: 10000,
  purchase_amount: null,
  evaluation_amount: null,
  source_of_truth: "broker",
  snapshot_at: "2026-05-13T02:10:00Z",
};

/* ───────────────────────────────────────────
 * External Events fixtures (Recent Events Panel)
 * ─────────────────────────────────────────── */

export const mockRecentEvents005930: ExternalEventView[] = [
  {
    event_id: 'evt-001',
    event_type: 'Y|정기공시',
    source_name: 'opendart',
    source_reliability_tier: 'T1',
    symbol: '005930',
    headline: '삼성전자, 2026년 1분기 영업이익 14조원 기록',
    body_summary: '삼성전자가 2026년 1분기 잠정 실적을 발표...',
    published_at: '2026-05-17T08:00:00Z',
    created_at: '2026-05-17T08:05:00Z',
  },
  {
    event_id: 'evt-002',
    event_type: 'N|seeded_news',
    source_name: 'naver_news',
    source_reliability_tier: 'T3',
    symbol: '005930',
    headline: '삼성전자, 차세대 HBM4 개발 속도',
    body_summary: '삼성전자가 차세대 고대역폭 메모리 HBM4의...',
    published_at: '2026-05-17T07:30:00Z',
    created_at: '2026-05-17T07:32:00Z',
  },
  {
    event_id: 'evt-003',
    event_type: 'Y|공정공시',
    source_name: 'opendart',
    source_reliability_tier: 'T1',
    symbol: '005930',
    headline: '삼성전자, 2조원 자사주 매입 결정',
    body_summary: '삼성전자가 2조원 규모의 자사주 매입을 결정...',
    published_at: '2026-05-17T06:00:00Z',
    created_at: '2026-05-17T06:03:00Z',
  },
  {
    event_id: 'evt-004',
    event_type: 'N|seeded_news',
    source_name: 'naver_news',
    source_reliability_tier: 'T3',
    symbol: '005930',
    headline: '삼성전자, 반도체 공급과잉 우려에 주가 하락',
    body_summary: '삼성전자 주가가 글로벌 반도체 공급과잉 우려로...',
    published_at: '2026-05-17T05:00:00Z',
    created_at: '2026-05-17T05:05:00Z',
  },
  {
    event_id: 'evt-005',
    event_type: 'Y|실적발표',
    source_name: 'opendart',
    source_reliability_tier: 'T1',
    symbol: '005930',
    headline: '삼성전자, 2026년 2분기 가이던스 발표',
    body_summary: '삼성전자가 2026년 2분기 실적 가이던스를 발표...',
    published_at: '2026-05-16T23:00:00Z',
    created_at: '2026-05-16T23:05:00Z',
  },
];
