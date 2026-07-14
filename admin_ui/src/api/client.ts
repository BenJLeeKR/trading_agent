/* ───────────────────────────────────────────
 * Fetch wrapper — attaches Bearer token,
 * handles 401, returns typed JSON responses.
 * ─────────────────────────────────────────── */

/**
 * 백엔드 API 호출 접두사.
 *
 * 프로덕션 빌드(Docker) 기본값은 **``/api``**다 — 프론트 컨테이너의
 * nginx(``nginx.frontend.conf``)가 ``/api/*`` 요청만 접두사를 벗기고 백엔드로
 * 내부 프록시한다. 브라우저는 항상 자신이 접속한 origin(그게 `trd.puwa.net`이든
 * zrok 터널 주소든 `localhost:3000`이든)으로만 호출하므로 CORS도, HTTPS
 * 페이지에서 HTTP API를 부를 때 브라우저가 막는 mixed-content 문제도 애초에
 * 발생하지 않는다.
 *
 * ``/api`` 접두사가 반드시 필요한 이유(단순 상대경로로는 안 되는 이유):
 * React Router의 클라이언트 라우트(``/orders``, ``/accounts``,
 * ``/reconciliation``, ``/agent-runs`` 등, App.tsx 참고)가 백엔드 API 라우터
 * prefix와 이름이 그대로 겹친다 — 접두사 없이 경로만 보고 nginx가 "이건
 * API다/화면이다"를 구분하려 하면, `/orders` 새로고침 같은 페이지 내비게이션이
 * SPA 대신 API 응답을 받아버리는 충돌이 생긴다(실측 확인됨). ``/api``로 항상
 * 명확히 구분한다.
 *
 * (과거엔 프론트 빌드 시점에 절대 URL, 예: `http://trd.puwa.net:8000`을
 * 박아 넣었는데, zrok처럼 프론트만 터널링되고 백엔드는 별도 HTTPS 주소가
 * 없는 환경에서 mixed-content로 막히는 문제가 있었다.)
 *
 * 로컬 `npm run dev`(vite dev server, nginx 프록시 없음)에서는 백엔드
 * 8000 포트로 직접 호출해야 하므로 `import.meta.env.DEV`일 때만
 * `http://localhost:8000`로 폴백한다. `VITE_API_BASE_URL`을 명시적으로
 * 지정하면 그 값이 항상 우선한다.
 *
 * `??`가 아니라 `||`를 쓴다 — Docker build arg 기본값이 빈 문자열(``""``)로
 * 전달되는데(``Dockerfile``의 ``ARG VITE_API_BASE_URL=""``), `??`(nullish
 * coalescing)는 `null`/`undefined`일 때만 폴백하고 빈 문자열은 "설정된 값"으로
 * 취급해버려서 `API_BASE_URL`이 의도와 다르게 빈 문자열이 되는 실제 버그가
 * 있었다(`/api` 접두사가 안 붙어 `fetch("/orders")`처럼 호출됨 — 실측 확인).
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? "http://localhost:8000" : "/api");

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

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

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
    const res = await fetch(`${API_BASE_URL}/clients/default`, {
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

/**
 * 오늘 이미 얼려둔(freeze) 유니버스 요약만 가져온다 — 라이브 재계산 없음.
 *
 * 2026-07-14: 운영 대시보드는 원래 ``getTradingUniversePreview()``를 썼는데,
 * 그 API는 "freeze vs live 비교" 카드를 위해 유니버스 선정 알고리즘 전체를
 * 그 순간 다시 계산하는 무거운 작업(실측 0.7~1.0초)을 매번 같이 수행했다.
 * "freeze / live 비교" 카드를 없애면서 그 무거운 재계산이 필요 없어졌으므로,
 * DB에서 오늘 freeze 결과만 가볍게 읽어오는 이 엔드포인트로 교체한다. 계좌
 * 정보도 필요 없다(freeze view는 계좌 무관).
 */
export async function getActiveIntradayFreezeSummary(): Promise<
  import("../types/api").TradingUniverseFreezeView | null
> {
  return request<import("../types/api").TradingUniverseFreezeView | null>(
    "/instruments/trading-universe/freeze-summary"
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
      `${API_BASE_URL}/realtime-quotes/stream?symbol=${encodeURIComponent(symbol)}`,
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
  const res = await fetch(`${API_BASE_URL}/external-events/recent?${params}`, {
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
