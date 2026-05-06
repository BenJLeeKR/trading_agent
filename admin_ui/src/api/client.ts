/* ───────────────────────────────────────────
 * Fetch wrapper — attaches Bearer token,
 * handles 401, returns typed JSON responses.
 * ─────────────────────────────────────────── */

const TOKEN_KEY = "auth_token";

export function getStoredToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

export class ApiResponseError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`);
    this.name = "ApiResponseError";
    this.status = status;
    this.detail = detail;
  }
}

let _onUnauthorized: (() => void) | null = null;

export function setOnUnauthorized(cb: () => void): void {
  _onUnauthorized = cb;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(path, { ...options, headers });

  if (res.status === 401) {
    clearStoredToken();
    if (_onUnauthorized) _onUnauthorized();
    throw new UnauthorizedError();
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body.detail !== undefined) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // ignore parse error
    }
    throw new ApiResponseError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

/* ───────────────────────────────────────────
 * Public helpers — no auth required
 * ─────────────────────────────────────────── */

export async function getHealth(): Promise<import("../types/api").HealthResponse> {
  return request<import("../types/api").HealthResponse>("/health");
}

export async function getReadyz(): Promise<Record<string, string>> {
  return request<Record<string, string>>("/health/readyz");
}

/* ───────────────────────────────────────────
 * Protected API helpers — require Bearer token
 * ─────────────────────────────────────────── */

export async function getOrders(): Promise<import("../types/api").OrderSummary[]> {
  return request<import("../types/api").OrderSummary[]>("/orders");
}

export async function getOrderDetail(
  orderId: string
): Promise<import("../types/api").OrderDetail> {
  return request<import("../types/api").OrderDetail>(`/orders/${orderId}`);
}

export async function getOrderEvents(
  orderId: string
): Promise<import("../types/api").OrderEvent[]> {
  return request<import("../types/api").OrderEvent[]>(
    `/orders/${orderId}/events`
  );
}

export async function getBrokerOrders(
  orderId: string
): Promise<import("../types/api").BrokerOrderView[]> {
  return request<import("../types/api").BrokerOrderView[]>(
    `/orders/${orderId}/broker-orders`
  );
}

export async function getReconciliationRuns(
  accountId?: string
): Promise<import("../types/api").ReconciliationRunSummary[]> {
  const params = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  return request<import("../types/api").ReconciliationRunSummary[]>(
    `/reconciliation/runs${params}`
  );
}

export async function getReconciliationLocks(
  accountId?: string
): Promise<import("../types/api").BlockingLockStatus[]> {
  const params = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  return request<import("../types/api").BlockingLockStatus[]>(
    `/reconciliation/locks${params}`
  );
}

/**
 * Fetch accounts for a given client.
 *
 * NOTE: `clientId` is required by the backend (`GET /accounts?client_id=...`).
 * As a temporary heuristic, the caller should obtain a `client_id` from
 * `getOrders()[0].client_id` — see components that call this function.
 */
export async function getAccounts(
  clientId?: string
): Promise<import("../types/api").AccountSummary[]> {
  const params = clientId
    ? `?client_id=${encodeURIComponent(clientId)}`
    : "";
  return request<import("../types/api").AccountSummary[]>(
    `/accounts${params}`
  );
}

export async function getAccountDetail(
  accountId: string
): Promise<import("../types/api").AccountSummary> {
  return request<import("../types/api").AccountSummary>(
    `/accounts/${accountId}`
  );
}

export async function getPositions(
  accountId: string
): Promise<import("../types/api").PositionSnapshotView[]> {
  return request<import("../types/api").PositionSnapshotView[]>(
    `/positions?account_id=${encodeURIComponent(accountId)}`
  );
}

export async function getCashBalance(
  accountId: string
): Promise<import("../types/api").CashBalanceSnapshotView | null> {
  return request<import("../types/api").CashBalanceSnapshotView | null>(
    `/cash-balances?account_id=${encodeURIComponent(accountId)}`
  );
}

export async function getTradeDecisions(
  decisionContextId?: string
): Promise<import("../types/api").TradeDecisionDetail[]> {
  const params = decisionContextId
    ? `?decision_context_id=${encodeURIComponent(decisionContextId)}`
    : "";
  return request<import("../types/api").TradeDecisionDetail[]>(
    `/trade-decisions${params}`
  );
}

export async function getAgentRuns(
  decisionContextId?: string
): Promise<import("../types/api").AgentRunResponse[]> {
  const params = decisionContextId
    ? `?decision_context_id=${encodeURIComponent(decisionContextId)}`
    : "";
  return request<import("../types/api").AgentRunResponse[]>(
    `/agent-runs${params}`
  );
}

export async function getDecisionContext(
  contextId: string
): Promise<import("../types/api").DecisionContextDetail> {
  return request<import("../types/api").DecisionContextDetail>(
    `/decision-contexts/${contextId}`
  );
}

export async function getAuditLogs(
  correlationId: string
): Promise<import("../types/api").AuditLogEntry[]> {
  return request<import("../types/api").AuditLogEntry[]>(
    `/audit-logs?correlation_id=${encodeURIComponent(correlationId)}`
  );
}
