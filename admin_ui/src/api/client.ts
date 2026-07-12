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

export async function getClients(): Promise<import("../types/api").ClientDetail[]> {
  return request<import("../types/api").ClientDetail[]>("/clients");
}

export async function getDefaultClient(): Promise<import("../types/api").ClientDetail | null> {
  try {
    const res = await fetch("/clients/default", {
      headers: getStoredToken()
        ? { Authorization: `Bearer ${getStoredToken()}` }
        : {},
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Failed to fetch default client: ${res.status}`);
    return (await res.json()) as import("../types/api").ClientDetail;
  } catch {
    return null;
  }
}

export async function getOrders(
  status?: string,
  limit?: number,
  date?: string,
): Promise<import("../types/api").OrderSummary[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (limit != null) params.set("limit", String(limit));
  if (date) params.set("date", date);
  const query = params.toString() ? `?${params.toString()}` : "";
  return request<import("../types/api").OrderSummary[]>(`/orders${query}`);
}

export async function getOrderDailySummary(date?: string): Promise<import("../types/api").OrderDailySummary> {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<import("../types/api").OrderDailySummary>(`/orders/daily-summary${query}`);
}

export async function getBuyBlockSummary(date?: string): Promise<import("../types/api").BuyBlockSummary> {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<import("../types/api").BuyBlockSummary>(`/orders/buy-block-summary${query}`);
}

export async function getRecentFailures(
  limit = 5,
  date?: string,
): Promise<import("../types/api").RecentFailureItem[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (date) params.set("date", date);
  return request<import("../types/api").RecentFailureItem[]>(
    `/orders/recent-failures?${params.toString()}`
  );
}

export async function getFailureSummary(): Promise<import("../types/api").FailureSummary> {
  return request<import("../types/api").FailureSummary>("/orders/failure-summary");
}

export async function getFillHistory(date?: string): Promise<import("../types/api").FillHistoryItem[]> {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<import("../types/api").FillHistoryItem[]>(`/fill-history${query}`);
}

export async function getFillSyncRuns(limit = 10): Promise<import("../types/api").FillSyncRunSummary[]> {
  return request<import("../types/api").FillSyncRunSummary[]>(`/fill-sync-runs?limit=${limit}`);
}

export async function getFillSyncRunSummary(): Promise<import("../types/api").FillSyncRunHealthSummary> {
  return request<import("../types/api").FillSyncRunHealthSummary>("/fill-sync-runs/summary");
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

export async function getSubmissionAttempts(
  orderId: string
): Promise<import("../types/api").SubmissionAttemptView[]> {
  return request<import("../types/api").SubmissionAttemptView[]>(
    `/orders/${orderId}/submission-attempts`
  );
}

export async function getReconciliationRuns(
  accountId?: string,
  includeHistorical?: boolean,
): Promise<import("../types/api").ReconciliationRunSummary[]> {
  const params = new URLSearchParams();
  if (accountId) params.set("account_id", accountId);
  if (includeHistorical) params.set("include_historical", "true");
  // 기본 동작: active_only=true → active issue만 반환
  const qs = params.toString();
  return request<import("../types/api").ReconciliationRunSummary[]>(
    `/reconciliation/runs${qs ? `?${qs}` : ""}`
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

export async function getReconciliationSummary(
  includeHistorical?: boolean,
): Promise<import("../types/api").ReconciliationSummary> {
  const params = new URLSearchParams();
  if (includeHistorical) params.set("include_historical", "true");
  const qs = params.toString();
  return request<import("../types/api").ReconciliationSummary>(
    `/reconciliation/summary${qs ? `?${qs}` : ""}`
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

export async function getTradingUniversePreview(
  accountId: string,
  options?: {
    lookbackHours?: number;
    maxCap?: number;
    excludeHeldFromCap?: boolean;
    marketOverlayCap?: number;
    prePoolSize?: number;
  },
): Promise<import("../types/api").TradingUniversePreviewResponse> {
  const params = new URLSearchParams({
    account_id: accountId,
  });
  if (options?.lookbackHours != null) params.set("lookback_hours", String(options.lookbackHours));
  if (options?.maxCap != null) params.set("max_cap", String(options.maxCap));
  if (options?.excludeHeldFromCap != null) {
    params.set("exclude_held_from_cap", String(options.excludeHeldFromCap));
  }
  if (options?.marketOverlayCap != null) {
    params.set("market_overlay_cap", String(options.marketOverlayCap));
  }
  if (options?.prePoolSize != null) params.set("pre_pool_size", String(options.prePoolSize));
  return request<import("../types/api").TradingUniversePreviewResponse>(
    `/instruments/trading-universe/preview?${params.toString()}`
  );
}

export async function getTradingUniverseCoverageSummary(
  lookbackDays = 14,
): Promise<import("../types/api").TradingUniverseCoverageSummaryResponse> {
  return request<import("../types/api").TradingUniverseCoverageSummaryResponse>(
    `/instruments/trading-universe/coverage-summary?lookback_days=${lookbackDays}`
  );
}

export async function getMarketOverlayFunnel(
  lookbackDays = 14,
  sampleLimit = 20,
): Promise<import("../types/api").MarketOverlayFunnelResponse> {
  return request<import("../types/api").MarketOverlayFunnelResponse>(
    `/instruments/trading-universe/market-overlay-funnel?lookback_days=${lookbackDays}&sample_limit=${sampleLimit}`
  );
}

export async function getIndexMembershipStaleness(
  thresholdDays = 21,
): Promise<import("../types/api").IndexMembershipStalenessResponse> {
  return request<import("../types/api").IndexMembershipStalenessResponse>(
    `/instruments/index-membership/staleness?threshold_days=${thresholdDays}`
  );
}

export async function getCashBalance(
  accountId: string
): Promise<import("../types/api").CashBalanceSnapshotView | null> {
  return request<import("../types/api").CashBalanceSnapshotView | null>(
    `/cash-balances?account_id=${encodeURIComponent(accountId)}`
  );
}

export async function getAccountSnapshots(
  accountId: string
): Promise<import("../types/api").AccountSnapshotResponse> {
  return request<import("../types/api").AccountSnapshotResponse>(
    `/account-snapshots/latest?account_id=${encodeURIComponent(accountId)}`
  );
}

export async function getTradeDecisions(
  decisionContextId?: string,
  limit?: number,
  offset?: number,
  filters?: Record<string, string | boolean | undefined>,
): Promise<import("../types/api").PaginatedTradeDecisionsResponse> {
  const searchParams = new URLSearchParams();
  if (decisionContextId) {
    searchParams.set("decision_context_id", decisionContextId);
  }
  if (limit !== undefined) {
    searchParams.set("limit", String(limit));
  }
  if (offset !== undefined) {
    searchParams.set("offset", String(offset));
  }
  if (filters) {
    for (const [key, value] of Object.entries(filters)) {
      if (value === undefined || value === "") continue;
      searchParams.set(key, String(value));
    }
  }
  const qs = searchParams.toString();
  return request<import("../types/api").PaginatedTradeDecisionsResponse>(
    `/trade-decisions${qs ? `?${qs}` : ""}`
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

export async function getBrokerCapacity(): Promise<import("../types/api").BrokerCapacityResponse> {
  return request<import("../types/api").BrokerCapacityResponse>("/broker-capacity");
}

/* ───────────────────────────────────────────
 * Realtime Quote screen (Phase 1: mock-backed)
 * ─────────────────────────────────────────── */

export async function getRealtimeQuoteBootstrap(): Promise<
  import("../types/api").RealtimeQuoteBootstrapResponse
> {
  return request<import("../types/api").RealtimeQuoteBootstrapResponse>(
    "/realtime-quotes/bootstrap"
  );
}

export async function subscribeRealtimeQuote(
  symbols: string[]
): Promise<import("../types/api").RealtimeQuoteSubscriptionsResponse> {
  return request<import("../types/api").RealtimeQuoteSubscriptionsResponse>(
    "/realtime-quotes/subscriptions",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbols }),
    }
  );
}

export async function unsubscribeRealtimeQuote(
  symbols: string[]
): Promise<import("../types/api").RealtimeQuoteSubscriptionsResponse> {
  return request<import("../types/api").RealtimeQuoteSubscriptionsResponse>(
    "/realtime-quotes/subscriptions",
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbols }),
    }
  );
}

export async function getRealtimeQuoteSnapshot(
  symbols: string[]
): Promise<import("../types/api").RealtimeQuoteSnapshotResponse> {
  return request<import("../types/api").RealtimeQuoteSnapshotResponse>(
    `/realtime-quotes/snapshot?symbols=${encodeURIComponent(symbols.join(","))}`
  );
}

export async function getRealtimeQuoteDailyPrice(
  symbol: string
): Promise<import("../types/api").RealtimeQuoteDailyPriceResponse> {
  return request<import("../types/api").RealtimeQuoteDailyPriceResponse>(
    `/realtime-quotes/daily-price?symbol=${encodeURIComponent(symbol)}`
  );
}

/**
 * Phase 4 push relay — subscribes to `GET /realtime-quotes/stream?symbol=...`
 * (Server-Sent Events) for exactly one symbol.
 *
 * Uses `fetch` + a manually-parsed `ReadableStream` rather than the native
 * `EventSource` — `EventSource` cannot send an `Authorization` header, and
 * this API's Bearer-token auth is shared with every other endpoint. Owns its
 * own reconnect-with-backoff loop (`EventSource` would normally do this for
 * us) so a dropped connection recovers automatically; `onTransportError`
 * lets the caller fall back to REST polling while a reconnect is pending.
 *
 * Returns a cleanup function — call it on symbol switch/unmount to stop the
 * stream and cancel any in-flight retry.
 */
export function subscribeRealtimeQuoteStream(
  symbol: string,
  handlers: {
    onEvent: (event: import("../types/api").RealtimeQuoteStreamEvent) => void;
    onTransportError?: () => void;
  }
): () => void {
  const controller = new AbortController();
  let stopped = false;
  let retryDelayMs = 1000;
  const MAX_RETRY_DELAY_MS = 10_000;

  async function runOnce(): Promise<void> {
    const token = getStoredToken();
    const res = await fetch(
      `/realtime-quotes/stream?symbol=${encodeURIComponent(symbol)}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      }
    );
    if (res.status === 401) {
      // 인증 만료 — 일반 transport error(backoff 재시도 대상)가 아니라 request()의
      // 401 처리와 동일한 "로그인 세션 종료" 이벤트로 다뤄야 한다. 토큰을 지우고
      // 공용 unauthorized 콜백(AuthContext의 logout)을 호출해, 다른 REST 호출이
      // 401을 받았을 때와 동일한 사용자 경험(로그아웃)이 되게 한다.
      clearStoredToken();
      if (_onUnauthorized) _onUnauthorized();
      throw new UnauthorizedError();
    }
    if (!res.ok || !res.body) {
      throw new Error(`realtime-quote stream error ${res.status}`);
    }
    retryDelayMs = 1000; // connected successfully — reset backoff for next drop

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!stopped) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sepIndex: number;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        const dataLine = rawEvent.split("\n").find((l) => l.startsWith("data: "));
        if (!dataLine) continue;
        try {
          const event = JSON.parse(
            dataLine.slice("data: ".length)
          ) as import("../types/api").RealtimeQuoteStreamEvent;
          handlers.onEvent(event);
        } catch {
          // Malformed frame — skip it, the stream itself is still alive.
        }
      }
    }
  }

  async function loop(): Promise<void> {
    while (!stopped) {
      try {
        await runOnce();
        if (stopped) return;
        // The stream ended without an error (server closed it) — treat like
        // a drop and reconnect through the same backoff path below.
        handlers.onTransportError?.();
      } catch (err) {
        if (stopped || controller.signal.aborted) return;
        if (err instanceof UnauthorizedError) {
          // 세션이 끝났다 — transport 재시도로 계속 이어가면 안 되고, 여기서
          // 완전히 멈춘다(무한 backoff 루프 방지). clearStoredToken()/
          // _onUnauthorized()는 이미 runOnce()에서 처리했다.
          stopped = true;
          return;
        }
        handlers.onTransportError?.();
      }
      if (stopped) return;
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      retryDelayMs = Math.min(retryDelayMs * 2, MAX_RETRY_DELAY_MS);
    }
  }

  loop();

  return () => {
    stopped = true;
    controller.abort();
  };
}

export async function getEnumMetadata(): Promise<import("../types/api").EnumMetadataListResponse> {
  return request<import("../types/api").EnumMetadataListResponse>("/metadata/enums");
}

export async function getEnumFieldMetadata(
  field: string
): Promise<import("../types/api").EnumFieldMetadataSchema> {
  return request<import("../types/api").EnumFieldMetadataSchema>(
    `/metadata/enums/${encodeURIComponent(field)}`
  );
}

/* ── Snapshot Sync Runs ──────────────────── */

export async function getSnapshotSyncRuns(
  limit?: number,
  status?: string
): Promise<import("../types/api").SnapshotSyncRunSummary[]> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (status) params.set("status", status);
  const qs = params.toString();
  return request<import("../types/api").SnapshotSyncRunSummary[]>(
    `/snapshot-sync-runs${qs ? `?${qs}` : ""}`
  );
}

export async function getSnapshotSyncSummary(): Promise<
  import("../types/api").SnapshotSyncRunHealthSummary
> {
  return request<import("../types/api").SnapshotSyncRunHealthSummary>(
    "/snapshot-sync-runs/summary"
  );
}

/* ── Market Session ──────────────────────── */

export async function getLatestMarketSession(): Promise<import("../types/api").SchedulerStatusResponse> {
  return request<import("../types/api").SchedulerStatusResponse>("/market-sessions/latest");
}

export async function getLatestOperationsDay(): Promise<import("../types/api").OperationsDayStatusResponse> {
  return request<import("../types/api").OperationsDayStatusResponse>("/market-sessions/operations-day/latest");
}

export async function getRecentSessionEvents(limit: number = 5): Promise<import("../types/api").SessionEventsResponse> {
  return request<import("../types/api").SessionEventsResponse>(`/market-sessions/events/recent?limit=${limit}`);
}

/* ── External Events (Recent Events Panel) ─── */

export async function getRecentExternalEvents(
  symbol: string,
  limit: number = 5
): Promise<import("../types/api").ExternalEventView[]> {
  const params = new URLSearchParams({
    symbol,
    limit: String(limit),
    include_non_listed: 'true',
  });
  const res = await fetch(`/external-events/recent?${params}`, {
    headers: getStoredToken()
      ? { Authorization: `Bearer ${getStoredToken()}` }
      : {},
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch { /* ignore */ }
    throw new ApiResponseError(res.status, detail);
  }
  const body: import("../types/api").ExternalEventsResponse = await res.json();
  return body.data ?? [];
}
