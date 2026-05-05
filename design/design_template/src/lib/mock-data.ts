// ── Types ──────────────────────────────────────────────────────────────────────

export type OrderStatus =
  | 'draft' | 'validated' | 'pending_submit' | 'submitted'
  | 'acknowledged' | 'partially_filled' | 'filled'
  | 'cancelled' | 'rejected' | 'expired' | 'reconcile_required' | 'error'

export type ReconciliationStatus = 'running' | 'resolved' | 'reflection_failed' | 'pending'
export type LockState = 'active' | 'expired'
export type Side = 'Buy' | 'Sell'
export type Severity = 'AMBER' | 'RED' | 'GREEN'

export interface Order {
  order_request_id: string
  symbol: string
  side: Side
  quantity: number
  status: OrderStatus
  created_at: string
  correlation_id: string
  account_id: string
  agent_label: string
  broker?: string
  filled_quantity?: number
  avg_price?: number
  state_events?: StateEvent[]
}

export interface StateEvent {
  event: string
  timestamp: string
  detail?: string
}

export interface ReconciliationRun {
  reconciliation_run_id: string
  account_id: string
  trigger_type: string
  status: ReconciliationStatus
  started_at: string
  overdue_since?: string
}

export interface Lock {
  lock_id: string
  agent_id: string
  resource: string
  severity: Severity
  locked_at: string
  expires_at: string
  is_active: boolean
  reason?: string
}

export interface Account {
  account_id: string
  account_code: string
  client_code: string
  account_type: string
  positions: Position[]
  cash_balance: number
  currency: string
  last_updated: string
}

export interface Position {
  symbol: string
  quantity: number
  average_price: number
  market_price: number
  unrealized_pnl: number
  source_of_truth: string
}

export interface Decision {
  trade_decision_id: string
  decision_context_id: string
  ticker: string
  side: Side
  decision_type: string
  confidence: number
  agent_label: string
  created_at: string
  rationale?: string
  context_summary?: string
  risk_level?: string
}

// ── Mock Orders ────────────────────────────────────────────────────────────────

export const mockOrders: Order[] = [
  {
    order_request_id: 'ORD-001',
    symbol: 'NVDA',
    side: 'Buy',
    quantity: 1000,
    status: 'filled',
    created_at: '2023-02-11 14:23:33.49',
    correlation_id: 'CORR-A1B2C3',
    account_id: 'ACC-001',
    agent_label: 'Agent 1',
    broker: 'Monospace',
    filled_quantity: 1000,
    avg_price: 214.52,
    state_events: [
      { event: 'draft', timestamp: '2023-02-11 14:23:30.10' },
      { event: 'validated', timestamp: '2023-02-11 14:23:31.22' },
      { event: 'submitted', timestamp: '2023-02-11 14:23:32.45' },
      { event: 'filled', timestamp: '2023-02-11 14:23:33.49', detail: 'Full fill at avg 214.52' },
    ],
  },
  {
    order_request_id: 'ORD-002',
    symbol: 'AAPL',
    side: 'Buy',
    quantity: 300,
    status: 'pending_submit',
    created_at: '2023-02-11 14:23:35.47',
    correlation_id: 'CORR-D4E5F6',
    account_id: 'ACC-002',
    agent_label: 'Agent 2',
    broker: 'Monospace',
    state_events: [
      { event: 'draft', timestamp: '2023-02-11 14:23:34.00' },
      { event: 'validated', timestamp: '2023-02-11 14:23:34.80' },
      { event: 'pending_submit', timestamp: '2023-02-11 14:23:35.47' },
    ],
  },
  {
    order_request_id: 'ORD-003',
    symbol: 'AMZN',
    side: 'Sell',
    quantity: 200,
    status: 'pending_submit',
    created_at: '2023-02-11 14:23:35.37',
    correlation_id: 'CORR-G7H8I9',
    account_id: 'ACC-003',
    agent_label: 'Agent 3',
    broker: 'Monospace',
    state_events: [
      { event: 'draft', timestamp: '2023-02-11 14:23:33.90' },
      { event: 'pending_submit', timestamp: '2023-02-11 14:23:35.37' },
    ],
  },
  {
    order_request_id: 'ORD-004',
    symbol: 'NVDA',
    side: 'Buy',
    quantity: 200,
    status: 'rejected',
    created_at: '2023-02-11 14:23:35.47',
    correlation_id: 'CORR-J0K1L2',
    account_id: 'ACC-001',
    agent_label: 'Agent 1',
    broker: 'Monospace',
    state_events: [
      { event: 'draft', timestamp: '2023-02-11 14:23:34.10' },
      { event: 'submitted', timestamp: '2023-02-11 14:23:35.00' },
      { event: 'rejected', timestamp: '2023-02-11 14:23:35.47', detail: 'Insufficient margin' },
    ],
  },
  {
    order_request_id: 'ORD-005',
    symbol: 'NVDA',
    side: 'Sell',
    quantity: 100,
    status: 'pending_submit',
    created_at: '2023-02-11 14:23:35.67',
    correlation_id: 'CORR-M3N4O5',
    account_id: 'ACC-002',
    agent_label: 'Agent 7',
    broker: 'Monospace',
    state_events: [
      { event: 'draft', timestamp: '2023-02-11 14:23:34.50' },
      { event: 'pending_submit', timestamp: '2023-02-11 14:23:35.67' },
    ],
  },
  {
    order_request_id: 'ORD-006',
    symbol: 'AAPL',
    side: 'Buy',
    quantity: 300,
    status: 'pending_submit',
    created_at: '2023-02-11 14:23:35.37',
    correlation_id: 'CORR-P6Q7R8',
    account_id: 'ACC-003',
    agent_label: 'Agent 4',
    broker: 'Monospace',
    state_events: [
      { event: 'draft', timestamp: '2023-02-11 14:23:33.80' },
      { event: 'validated', timestamp: '2023-02-11 14:23:34.90' },
      { event: 'pending_submit', timestamp: '2023-02-11 14:23:35.37' },
    ],
  },
  {
    order_request_id: 'ORD-007',
    symbol: 'AMZN',
    side: 'Sell',
    quantity: 200,
    status: 'pending_submit',
    created_at: '2023-02-11 14:23:35.37',
    correlation_id: 'CORR-S9T0U1',
    account_id: 'ACC-001',
    agent_label: 'Agent 2',
    broker: 'Monospace',
  },
  {
    order_request_id: 'ORD-008',
    symbol: 'NVDA',
    side: 'Buy',
    quantity: 200,
    status: 'rejected',
    created_at: '2023-02-11 14:23:35.67',
    correlation_id: 'CORR-V2W3X4',
    account_id: 'ACC-002',
    agent_label: 'Agent 5',
    broker: 'Monospace',
    state_events: [
      { event: 'rejected', timestamp: '2023-02-11 14:23:35.67', detail: 'Risk limit exceeded' },
    ],
  },
  {
    order_request_id: 'ORD-009',
    symbol: 'NVDA',
    side: 'Buy',
    quantity: 100,
    status: 'error',
    created_at: '2023-02-11 14:23:35.45',
    correlation_id: 'CORR-Y5Z6A7',
    account_id: 'ACC-003',
    agent_label: 'Agent 7',
    broker: 'Monospace',
    state_events: [
      { event: 'error', timestamp: '2023-02-11 14:23:35.45', detail: 'Broker connection timeout' },
    ],
  },
  {
    order_request_id: 'ORD-010',
    symbol: 'AAPL',
    side: 'Sell',
    quantity: 100,
    status: 'error',
    created_at: '2023-02-11 14:23:35.87',
    correlation_id: 'CORR-B8C9D0',
    account_id: 'ACC-001',
    agent_label: 'Agent 3',
    broker: 'Monospace',
    state_events: [
      { event: 'error', timestamp: '2023-02-11 14:23:35.87', detail: 'Order routing failure' },
    ],
  },
  {
    order_request_id: 'ORD-011',
    symbol: 'AAPL',
    side: 'Sell',
    quantity: 200,
    status: 'pending_submit',
    created_at: '2023-02-11 14:23:35.37',
    correlation_id: 'CORR-E1F2G3',
    account_id: 'ACC-002',
    agent_label: 'Agent 6',
    broker: 'Monospace',
  },
  {
    order_request_id: 'ORD-012',
    symbol: 'TSLA',
    side: 'Buy',
    quantity: 150,
    status: 'reconcile_required',
    created_at: '2023-02-11 14:22:50.00',
    correlation_id: 'CORR-H4I5J6',
    account_id: 'ACC-003',
    agent_label: 'Agent 2',
    broker: 'Monospace',
    state_events: [
      { event: 'submitted', timestamp: '2023-02-11 14:22:49.00' },
      { event: 'reconcile_required', timestamp: '2023-02-11 14:22:50.00', detail: 'Position mismatch detected' },
    ],
  },
]

// ── Mock Reconciliation Runs ────────────────────────────────────────────────────

export const mockReconRuns: ReconciliationRun[] = [
  {
    reconciliation_run_id: '1913350238',
    account_id: 'ACC-001',
    trigger_type: 'scheduled',
    status: 'pending',
    started_at: '2023-02-11 14:13:00.00',
    overdue_since: '10 minutes ago',
  },
  {
    reconciliation_run_id: '1913350233',
    account_id: 'ACC-002',
    trigger_type: 'manual',
    status: 'pending',
    started_at: '2023-02-11 14:21:00.00',
    overdue_since: '2 minutes ago',
  },
  {
    reconciliation_run_id: '1913350230',
    account_id: 'ACC-003',
    trigger_type: 'triggered',
    status: 'pending',
    started_at: '2023-02-11 14:19:00.00',
    overdue_since: '4 minutes ago',
  },
  {
    reconciliation_run_id: '1913350225',
    account_id: 'ACC-001',
    trigger_type: 'scheduled',
    status: 'resolved',
    started_at: '2023-02-11 14:00:00.00',
  },
  {
    reconciliation_run_id: '1913350220',
    account_id: 'ACC-002',
    trigger_type: 'scheduled',
    status: 'reflection_failed',
    started_at: '2023-02-11 13:50:00.00',
  },
  {
    reconciliation_run_id: '1913350218',
    account_id: 'ACC-003',
    trigger_type: 'manual',
    status: 'resolved',
    started_at: '2023-02-11 13:45:00.00',
  },
  {
    reconciliation_run_id: '1913350215',
    account_id: 'ACC-001',
    trigger_type: 'scheduled',
    status: 'running',
    started_at: '2023-02-11 14:23:00.00',
  },
]

// ── Mock Locks ─────────────────────────────────────────────────────────────────

export const mockLocks: Lock[] = [
  {
    lock_id: 'LOCK-001',
    agent_id: 'Agent 7',
    resource: 'Resource 1',
    severity: 'AMBER',
    locked_at: '2023-02-11 14:10:00.00',
    expires_at: '2023-02-11 14:40:00.00',
    is_active: true,
    reason: 'Waiting for broker acknowledgment',
  },
  {
    lock_id: 'LOCK-002',
    agent_id: 'Agent 2',
    resource: 'Locks, Resource',
    severity: 'AMBER',
    locked_at: '2023-02-11 14:15:00.00',
    expires_at: '2023-02-11 14:45:00.00',
    is_active: true,
    reason: 'Reconciliation in progress',
  },
  {
    lock_id: 'LOCK-003',
    agent_id: 'Agent 3',
    resource: 'Resource 2',
    severity: 'AMBER',
    locked_at: '2023-02-11 14:18:00.00',
    expires_at: '2023-02-11 14:48:00.00',
    is_active: true,
    reason: 'Position snapshot pending',
  },
  {
    lock_id: 'LOCK-004',
    agent_id: 'Agent 5',
    resource: 'Resource 3',
    severity: 'AMBER',
    locked_at: '2023-02-11 14:20:00.00',
    expires_at: '2023-02-11 14:50:00.00',
    is_active: true,
    reason: 'Cash balance verification',
  },
  {
    lock_id: 'LOCK-005',
    agent_id: 'Agent 1',
    resource: 'Resource 4',
    severity: 'AMBER',
    locked_at: '2023-02-11 13:55:00.00',
    expires_at: '2023-02-11 14:25:00.00',
    is_active: false,
    reason: 'Expired — order routing completed',
  },
]

// ── Mock Accounts ──────────────────────────────────────────────────────────────

export const mockAccounts: Account[] = [
  {
    account_id: 'ACC-001',
    account_code: 'TRD-ALPHA-01',
    client_code: 'CLT-0012',
    account_type: 'Equity',
    cash_balance: 1_240_500.00,
    currency: 'USD',
    last_updated: '2023-02-11 14:23:20.00',
    positions: [
      { symbol: 'NVDA', quantity: 2500, average_price: 198.40, market_price: 214.52, unrealized_pnl: 40_300.00, source_of_truth: 'broker' },
      { symbol: 'AAPL', quantity: 800, average_price: 148.20, market_price: 155.30, unrealized_pnl: 5_680.00, source_of_truth: 'broker' },
      { symbol: 'MSFT', quantity: 600, average_price: 280.00, market_price: 291.45, unrealized_pnl: 6_870.00, source_of_truth: 'broker' },
    ],
  },
  {
    account_id: 'ACC-002',
    account_code: 'TRD-BETA-02',
    client_code: 'CLT-0013',
    account_type: 'Mixed',
    cash_balance: 560_000.00,
    currency: 'USD',
    last_updated: '2023-02-11 14:23:10.00',
    positions: [
      { symbol: 'AMZN', quantity: 300, average_price: 96.50, market_price: 103.80, unrealized_pnl: 2_190.00, source_of_truth: 'broker' },
      { symbol: 'TSLA', quantity: 400, average_price: 210.00, market_price: 198.20, unrealized_pnl: -4_720.00, source_of_truth: 'system' },
    ],
  },
  {
    account_id: 'ACC-003',
    account_code: 'TRD-GAMMA-03',
    client_code: 'CLT-0015',
    account_type: 'Derivatives',
    cash_balance: 88_300.00,
    currency: 'USD',
    last_updated: '2023-02-11 14:22:50.00',
    positions: [
      { symbol: 'NVDA', quantity: 150, average_price: 205.00, market_price: 214.52, unrealized_pnl: 1_428.00, source_of_truth: 'broker' },
    ],
  },
  {
    account_id: 'ACC-004',
    account_code: 'TRD-DELTA-04',
    client_code: 'CLT-0018',
    account_type: 'Equity',
    cash_balance: 2_105_000.00,
    currency: 'USD',
    last_updated: '2023-02-11 14:23:05.00',
    positions: [
      { symbol: 'AAPL', quantity: 1200, average_price: 145.00, market_price: 155.30, unrealized_pnl: 12_360.00, source_of_truth: 'broker' },
      { symbol: 'GOOGL', quantity: 500, average_price: 98.00, market_price: 102.40, unrealized_pnl: 2_200.00, source_of_truth: 'broker' },
    ],
  },
]

// ── Mock Decisions ─────────────────────────────────────────────────────────────

export const mockDecisions: Decision[] = [
  {
    trade_decision_id: 'DEC-001',
    decision_context_id: 'CTX-A01',
    ticker: 'NVDA',
    side: 'Buy',
    decision_type: 'momentum',
    confidence: 0.91,
    agent_label: 'Agent 1',
    created_at: '2023-02-11 14:23:30.00',
    risk_level: 'medium',
    rationale: 'Strong momentum signal detected. RSI at 62, MACD crossover confirmed. Volume above 20-day average by 35%. Earnings beat catalyst from prior quarter still carrying weight.',
    context_summary: 'Market microstructure favourable. Agent correlation with sector ETF showing 0.84. No conflicting signals from other agents in current decision window.',
  },
  {
    trade_decision_id: 'DEC-002',
    decision_context_id: 'CTX-A02',
    ticker: 'AAPL',
    side: 'Buy',
    decision_type: 'mean_reversion',
    confidence: 0.78,
    agent_label: 'Agent 2',
    created_at: '2023-02-11 14:23:28.00',
    risk_level: 'low',
    rationale: 'Price retracement to key support level. 3-day RSI oversold. Historical mean reversion probability at this level: 72%.',
    context_summary: 'Sector sentiment neutral. Cash position available. Risk limits within bounds.',
  },
  {
    trade_decision_id: 'DEC-003',
    decision_context_id: 'CTX-A03',
    ticker: 'AMZN',
    side: 'Sell',
    decision_type: 'risk_reduction',
    confidence: 0.85,
    agent_label: 'Agent 3',
    created_at: '2023-02-11 14:23:25.00',
    risk_level: 'low',
    rationale: 'Position exceeded target allocation by 8%. Risk reduction triggered per portfolio rules. No adverse signal — purely mechanical rebalance.',
    context_summary: 'Portfolio heat map shows overweight in consumer discretionary. Coordinated with Agent 7 to avoid simultaneous sells.',
  },
  {
    trade_decision_id: 'DEC-004',
    decision_context_id: 'CTX-A04',
    ticker: 'NVDA',
    side: 'Buy',
    decision_type: 'momentum',
    confidence: 0.62,
    agent_label: 'Agent 7',
    created_at: '2023-02-11 14:23:22.00',
    risk_level: 'high',
    rationale: 'Secondary momentum signal. Below confidence threshold of 0.65 — flagged for review. IV elevated ahead of sector event.',
    context_summary: 'Agent 1 has conflicting signal on same ticker. Coordination flag raised. Decision gated pending review.',
  },
  {
    trade_decision_id: 'DEC-005',
    decision_context_id: 'CTX-A05',
    ticker: 'TSLA',
    side: 'Buy',
    decision_type: 'breakout',
    confidence: 0.88,
    agent_label: 'Agent 4',
    created_at: '2023-02-11 14:23:18.00',
    risk_level: 'medium',
    rationale: 'Breakout confirmed above 30-day consolidation range. Volume surge +62% vs. baseline. Stop defined at prior range high.',
    context_summary: 'No open positions in TSLA for this account. Clean entry. Max position sizing applied.',
  },
  {
    trade_decision_id: 'DEC-006',
    decision_context_id: 'CTX-A06',
    ticker: 'AAPL',
    side: 'Sell',
    decision_type: 'risk_reduction',
    confidence: 0.74,
    agent_label: 'Agent 5',
    created_at: '2023-02-11 14:23:12.00',
    risk_level: 'low',
    rationale: 'Trailing stop triggered. Locked in 12% gain from entry. Systematic exit per strategy rules.',
    context_summary: 'No replacement signal queued. Cash will be held pending next allocation cycle.',
  },
  {
    trade_decision_id: 'DEC-007',
    decision_context_id: 'CTX-A07',
    ticker: 'MSFT',
    side: 'Buy',
    decision_type: 'fundamental',
    confidence: 0.93,
    agent_label: 'Agent 6',
    created_at: '2023-02-11 14:23:05.00',
    risk_level: 'low',
    rationale: 'Fundamental valuation model shows 18% discount to intrinsic value. Cloud segment growth accelerating. High conviction entry.',
    context_summary: 'Long-term allocation bucket. Not subject to intraday reconciliation. Agent 6 specialised in fundamental overlay.',
  },
]

// ── System Health ──────────────────────────────────────────────────────────────

export const systemHealth = {
  api: {
    status: 'GREEN' as Severity,
    label: 'Operational',
    latency: '45ms',
    uptime: '99.99%',
  },
  database: {
    status: 'GREEN' as Severity,
    label: 'Connected',
    replicas: 3,
    storage: '72%',
  },
  activeLocks: {
    status: 'AMBER' as Severity,
    label: 'Warning',
    count: 12,
    max: 15,
  },
  incompleteRecon: {
    status: 'RED' as Severity,
    label: 'Critical',
    pending: 4,
    overdue: 2,
  },
}

export const degradedAgents = [
  { agent_id: 'Agent 7', issue: 'High Latency', severity: 'RED' as Severity },
  { agent_id: 'Agent 7', issue: 'Model Failure on Reflection', severity: 'RED' as Severity },
  { agent_id: 'Agent 2', issue: 'Degraded Model Accuracy', severity: 'AMBER' as Severity },
  { agent_id: 'Agent 5', issue: 'Slow Reflection Response', severity: 'AMBER' as Severity },
]
