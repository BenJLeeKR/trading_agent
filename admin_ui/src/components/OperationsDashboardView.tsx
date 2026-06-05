import { useState, useEffect, useMemo } from "react";
import { StatusCard } from "./common/StatusCard";
import { DataTable, type Column } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { Panel } from "./common/Panel";
import { WarningBanner } from "./common/WarningBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { ArrowRight, RefreshCw } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { formatKrw, formatKstDateTime, formatKstElapsed, getKstTodayString } from "../lib/utils";
import {
  getHealth,
  getReadyz,
  getClients,
  getAccounts,
  getOrders,
  getPositions,
  getCashBalance,
  getReconciliationSummary,
  getSnapshotSyncRuns,
  getLatestMarketSession,
  getLatestOperationsDay,
  getRecentSessionEvents,
  getRecentFailures,
  getFailureSummary,
  getOrderDailySummary,
  getBuyBlockSummary,
} from "../api/client";
import type {
  BuyBlockSummary,
  HealthResponse,
  OrderSummary,
  PositionSnapshotView,
  CashBalanceSnapshotView,
  ReconciliationRunSummary,
  ReconciliationSummary,
  AccountSummary,
  ClientDetail,
  SnapshotSyncRunSummary,
  SchedulerStatusResponse,
  SessionEventsResponse,
  SessionEventSummary,
  MarketSessionSummary,
  OperationsDayRunSummary,
  OperationsDayStatusResponse,
  RecentFailureItem,
  FailureSummary,
  OrderDailySummary,
} from "../types/api";
import { deriveAlerts } from "../lib/alerts";
import {
  formatSnapshotBudgetParts,
  parseSnapshotBudgetCounters,
} from "../lib/snapshotBudget";

/* ── Feature flags ── */
// 현재 운영 화면 단순화를 위해 숨김, 추후 필요 시 true
const SHOW_ADVANCED_OPERATION_CARDS = false;
// 최근 5개 요약 섹션 표시 (true 시 하단에 compact 요약 카드 표시)
const SHOW_DASHBOARD_RECENT_SUMMARIES = true;

/* ── Types ── */
interface ApiErrorEntry {
  apiName: string;
  message: string;
}

/* ── Compact Summary Types ── */
interface CompactOrderItem {
  id: string;
  createdAt: string;
  symbol: string;
  instrumentName: string;
  side: string;
  quantity: number;
  status: string;
  statusVariant: "success" | "warning" | "error" | "info" | "neutral";
}

interface CompactReconciliationItem {
  id: string;
  startedAt: string;
  status: string;
  statusVariant: "success" | "warning" | "error" | "neutral";
  mismatchCount: number;
  completedAt: string | null;
}

interface CompactAlertItem {
  id: string;
  level: "긴급" | "주의";
  levelVariant: "error" | "warning";
  title: string;
  description: string;
}

interface DashboardData {
  clients: ClientDetail[];
  health: HealthResponse | null;
  readyz: Record<string, string> | null;
  reconSummary: ReconciliationSummary | null;
  reconRuns: ReconciliationRunSummary[];
  orders: OrderSummary[];
  accounts: AccountSummary[];
  positionsMap: Map<string, PositionSnapshotView[]>;
  cashMap: Map<string, CashBalanceSnapshotView | null>;
  snapshotSyncRuns: SnapshotSyncRunSummary[];
  sessionData: SchedulerStatusResponse | null;
  operationsDayData: OperationsDayStatusResponse | null;
  sessionEvents: SessionEventSummary[];
  todayOrderSummary: OrderDailySummary | null;
}

/* ── Helpers ── */
function formatPercent(val: number | null | undefined): string {
  if (val == null) return "N/A";
  const prefix = val >= 0 ? "+" : "";
  return `${prefix}${val.toFixed(2)}%`;
}

/* ── Scheduler Status Types & Helper ── */
export interface SchedulerCardState {
  badgeLabel: string;
  variant: "healthy" | "warning" | "error" | "neutral";
  value: string;
  subtitle: string;
}

/**
 * Determine scheduler status card state based on session data and fetch errors.
 * Distinguishes: No Data (neutral) vs Stale (warning) vs Real Error (error).
 */
export function getSchedulerStatus(
  operationsDay: OperationsDayRunSummary | null,
  operationsDayHealthy: boolean,
  operationsDayStaleSeconds: number | null,
  operationsDayFetchError: string | null,
  session: MarketSessionSummary | null,
  sessionHealthy: boolean,
  staleSeconds: number | null,
  hasFetchError: boolean,
  fetchErrorMessage: string | null,
): SchedulerCardState {
  // 0. Prefer operations-day scheduler state when available
  if (operationsDay) {
    if (operationsDayFetchError) {
      return {
        badgeLabel: "오류",
        variant: "error",
        value: "오류",
        subtitle: operationsDayFetchError,
      };
    }

    const schedulerStatus = operationsDay.scheduler_status;
    const schedulerSubtitle =
      `제출 ${operationsDay.submit_count} / HP매도 ${operationsDay.held_position_sell_submit_count} / cycles ${operationsDay.cycles}`;

    if (operationsDay.is_trading_day === false) {
      return {
        badgeLabel: "휴장",
        variant: "neutral",
        value: "휴장",
        subtitle: schedulerSubtitle,
      };
    }

    const STALE_THRESHOLD_SECONDS = 600;
    if (
      !operationsDayHealthy ||
      (operationsDayStaleSeconds != null && operationsDayStaleSeconds > STALE_THRESHOLD_SECONDS)
    ) {
      return {
        badgeLabel: "지연",
        variant: "warning",
        value: "지연",
        subtitle: `Last heartbeat: ${formatKstElapsed(operationsDay.last_heartbeat_at)} | ${schedulerSubtitle}`,
      };
    }

    if (schedulerStatus === "intraday") {
      return {
        badgeLabel: "운영중",
        variant: "healthy",
        value: "운영중",
        subtitle: `${operationsDay.market_phase ?? "-"} | ${schedulerSubtitle}`,
      };
    }
    if (schedulerStatus === "after_hours") {
      return {
        badgeLabel: "장후",
        variant: "neutral",
        value: "장후",
        subtitle: schedulerSubtitle,
      };
    }
    if (schedulerStatus === "end_of_day_complete") {
      return {
        badgeLabel: "종료",
        variant: "neutral",
        value: "종료",
        subtitle: schedulerSubtitle,
      };
    }
    return {
      badgeLabel: "준비",
      variant: "neutral",
      value: "준비",
      subtitle: schedulerSubtitle,
    };
  }

  // 1. Fetch error → real error (red)
  if (hasFetchError) {
    return {
      badgeLabel: "오류",
      variant: "error",
      value: "오류",
      subtitle: fetchErrorMessage ?? "API fetch failed",
    };
  }

  // 2. No session data → No Data (neutral gray, NOT error)
  if (!session) {
    return {
      badgeLabel: "미수집",
      variant: "neutral",
      value: "미수집",
      subtitle: "No session data yet",
    };
  }

  // 3. Fallback source → warning (orange), NOT error
  if (session.source === "gate_error_fallback" || session.source === "fallback") {
    return {
      badgeLabel: "대체",
      variant: "warning",
      value: "대체",
      subtitle: `Fallback: ${session.market_phase ?? "-"}`,
    };
  }

  // 4. Stale (unhealthy or stale_seconds exceeds 10 min threshold)
  const STALE_THRESHOLD_SECONDS = 600;
  if (!sessionHealthy || (staleSeconds != null && staleSeconds > STALE_THRESHOLD_SECONDS)) {
    return {
      badgeLabel: "지연",
      variant: "warning",
      value: "지연",
      subtitle: `Last checked: ${formatKstElapsed(session.checked_at)}`,
    };
  }

  // 5. Healthy (green)
  return {
    badgeLabel: "정상",
    variant: "healthy",
    value: "정상",
    subtitle: `Source: ${session.source ?? "-"} | Phase: ${session.market_phase ?? "-"}`,
  };
}

/* ── Legacy Columns (feature flag SHOW_DASHBOARD_SECTIONS 복원 시 사용) ── */
/*
interface RecentEvent {
  id: string;
  time: string;
  type: string;
  description: string;
  symbol: string;
  status: string;
}

const eventColumns: Column<RecentEvent>[] = [
  { key: "time", header: "시간", width: "100px" },
  {
    key: "type",
    header: "유형",
    render: (row: RecentEvent) => (
      <span className="font-mono text-xs text-[#64748b]">{row.type}</span>
    ),
  },
  { key: "description", header: "설명" },
  {
    key: "symbol",
    header: "종목",
    render: (row: RecentEvent) =>
      row.symbol !== "-" ? (
        <StatusBadge variant="info">{row.symbol}</StatusBadge>
      ) : (
        <span className="text-[#94a3b8]">-</span>
      ),
  },
  {
    key: "status",
    header: "상태",
    render: (row: RecentEvent) => (
      <StatusBadge variant={row.status === "SUCCESS" ? "success" : "error"}>
        {row.status === "SUCCESS" ? "성공" : "실패"}
      </StatusBadge>
    ),
  },
];

interface PendingRecon {
  id: string;
  type: string;
  account: string;
  createdAt: string;
}

const reconColumns: Column<PendingRecon>[] = [
  { key: "id", header: "ID" },
  { key: "type", header: "유형" },
  { key: "account", header: "계좌" },
  { key: "createdAt", header: "발생 시간" },
];
*/

/* ── Component ── */
export default function OperationsDashboardView() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiErrors, setApiErrors] = useState<ApiErrorEntry[]>([]);
  const [data, setData] = useState<DashboardData | null>(null);
  const [buyBlockSummary, setBuyBlockSummary] = useState<BuyBlockSummary | null>(null);
  const [buyBlockSummaryLoading, setBuyBlockSummaryLoading] = useState(false);
  const [failureSummary, setFailureSummary] = useState<FailureSummary | null>(null);
  const [failureSummaryLoading, setFailureSummaryLoading] = useState(false);
  const [recentFailures, setRecentFailures] = useState<RecentFailureItem[]>([]);
  const [failuresLoading, setFailuresLoading] = useState(false);
  const [failuresError, setFailuresError] = useState<string | null>(null);

  const fetchAll = async () => {
    setLoading(true);
    setError(null);
    const errors: ApiErrorEntry[] = [];
    const addError = (apiName: string, err: unknown) => {
      errors.push({ apiName, message: String(err) });
    };

    const healthPromise = getHealth().catch((e) => {
      addError("GET /health", e);
      return null;
    });
    const readyzPromise = getReadyz().catch((e) => {
      addError("GET /readyz", e);
      return null;
    });
    const reconSummaryPromise = getReconciliationSummary().catch((e) => {
      addError("GET /reconciliation/summary", e);
      return null;
    });
    const ordersPromise = getOrders().catch((e) => {
      addError("GET /orders", e);
      return [];
    });
    const todayOrderSummaryPromise = getOrderDailySummary().catch((e) => {
      addError("GET /orders/daily-summary", e);
      return null;
    });
    const buyBlockSummaryPromise = getBuyBlockSummary().catch((e) => {
      addError("GET /orders/buy-block-summary", e);
      return null;
    });
    const clientsPromise = getClients().catch((e) => {
      addError("GET /clients", e);
      return [] as ClientDetail[];
    });

    // ── Session status fetch ──
    const sessionPromise = getLatestMarketSession().catch((e) => {
      addError("GET /market-sessions/latest", e);
      return null;
    });
    const operationsDayPromise = getLatestOperationsDay().catch((e) => {
      addError("GET /market-sessions/operations-day/latest", e);
      return null;
    });
    const eventsPromise = getRecentSessionEvents(5).catch((e) => {
      addError("GET /market-sessions/events/recent", e);
      return null;
    });

    const [health, readyz, reconSummary, orders, todayOrderSummary, buyBlockSummaryData, clients, sessionData, operationsDayData, eventsResp] = await Promise.all([
      healthPromise,
      readyzPromise,
      reconSummaryPromise,
      ordersPromise,
      todayOrderSummaryPromise,
      buyBlockSummaryPromise,
      clientsPromise,
      sessionPromise,
      operationsDayPromise,
      eventsPromise,
    ]);
    const sessionEvents = eventsResp?.data ?? [];

    // ── Accounts per client ──
    let accounts: AccountSummary[] = [];
    if (clients.length > 0) {
      const results = await Promise.allSettled(
        clients.map((c) => getAccounts(c.client_id))
      );
      for (const r of results) {
        if (r.status === "fulfilled") accounts.push(...r.value);
      }
      if (results.some((r) => r.status === "rejected")) {
        addError("GET /accounts", "일부 클라이언트 계좌 조회 실패");
      }
    }

    // ── Positions per account ──
    const positionsMap = new Map<string, PositionSnapshotView[]>();
    if (accounts.length > 0) {
      const posResults = await Promise.allSettled(
        accounts.map((a) => getPositions(a.account_id).then((p) => ({ accountId: a.account_id, positions: p })))
      );
      posResults.forEach((r) => {
        if (r.status === "fulfilled") {
          positionsMap.set(r.value.accountId, r.value.positions);
        } else {
          addError("GET /positions", "일부 계좌 포지션 조회 실패");
        }
      });
    }

    // ── Cash per account ──
    const cashMap = new Map<string, CashBalanceSnapshotView | null>();
    if (accounts.length > 0) {
      const cashResults = await Promise.allSettled(
        accounts.map((a) => getCashBalance(a.account_id).then((c) => ({ accountId: a.account_id, cash: c })))
      );
      cashResults.forEach((r) => {
        if (r.status === "fulfilled") {
          cashMap.set(r.value.accountId, r.value.cash);
        } else {
          addError("GET /cash-balance", "일부 계좌 현금 조회 실패");
        }
      });
    }

    // ── Reconciliation runs (from summary's recentActiveIssues — active-only data) ──
    // NOTE: 별도 getReconciliationRuns API 호출 대신 이미 fetch된 summary 응답의
    //       recentActiveIssues를 사용. 이 필드는 백엔드에서 active-only로 필터링됨.
    const reconRuns: ReconciliationRunSummary[] = (reconSummary?.recentActiveIssues ?? []).slice(0, 5);

    // ── Snapshot sync runs ──
    let snapshotSyncRuns: SnapshotSyncRunSummary[] = [];
    try {
      snapshotSyncRuns = await getSnapshotSyncRuns(10);
    } catch {
      addError("GET /snapshot-sync-runs", "스냅샷 동기화 이력 조회 실패");
    }

    // ── Recent submission failures ──
    setFailuresLoading(true);
    try {
      const failuresData = await getRecentFailures(5, getKstTodayString());
      setRecentFailures(failuresData);
      setFailuresError(null);
    } catch (e) {
      setRecentFailures([]);
      setFailuresError(String(e));
    }
    setFailuresLoading(false);

    // ── Submission failure summary (aggregated counts) ──
    setFailureSummaryLoading(true);
    try {
      const summaryData = await getFailureSummary();
      setFailureSummary(summaryData);
    } catch {
      setFailureSummary(null);
    }
    setFailureSummaryLoading(false);
    setBuyBlockSummaryLoading(true);
    setBuyBlockSummary(buyBlockSummaryData);
    setBuyBlockSummaryLoading(false);

    setApiErrors(errors);
    setData({
      clients,
      health,
      readyz,
      reconSummary: reconSummary as ReconciliationSummary | null,
      reconRuns,
      orders,
      accounts,
      positionsMap,
      cashMap,
      snapshotSyncRuns,
      sessionData: sessionData as SchedulerStatusResponse | null,
      operationsDayData: operationsDayData as OperationsDayStatusResponse | null,
      sessionEvents,
      todayOrderSummary: todayOrderSummary as OrderDailySummary | null,
    });
    setLoading(false);
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const derived = useMemo(() => {
    if (!data) return null;

    // ── Position dedup: instrument_id 기준 최신 snapshot (AccountsView와 동일 기준) ──
    const latestPositionMap = new Map<string, PositionSnapshotView>();
    for (const positions of data.positionsMap.values()) {
      for (const p of positions) {
        const existing = latestPositionMap.get(p.instrument_id);
        // instrument_id 기준 최신 snapshot_at 유지 (AccountsView와 동일)
        if (!existing || p.snapshot_at > existing.snapshot_at) {
          latestPositionMap.set(p.instrument_id, p);
        }
      }
    }
    // quantity > 0인 포지션만 카운트
    const totalPositions = Array.from(latestPositionMap.values()).filter(
      (p) => (p.quantity ?? 0) > 0
    ).length;

    // ── Cash balance: settled_cash 우선, fallback available_cash ──
    let totalAvailableCash = 0;
    let cashUsedFallback = false;
    for (const cash of data.cashMap.values()) {
      if (cash) {
        const val = cash.settled_cash ?? cash.available_cash;
        if (val !== null && val !== undefined) {
          totalAvailableCash += val;
        }
        if (cash.settled_cash === null || cash.settled_cash === undefined) {
          cashUsedFallback = true;
        }
      }
    }

    const pendingSubmitCount = data.todayOrderSummary?.pending_submit_count ?? 0;
    const filledCount = data.todayOrderSummary?.filled_count ?? 0;
    const submittedCount = data.todayOrderSummary?.submitted_count ?? 0;
    const rejectedCount = data.orders.filter(
      (o) => o.status === "rejected"
    ).length;

    const incompleteReconCount = data.reconSummary?.incomplete_recon_count ?? 0;
    const activeLocksCount = data.reconSummary?.active_locks_count ?? 0;
    const activeIssueCount = data.reconSummary?.activeIssueCount ?? 0;
    const historicalFailedCount = data.reconSummary?.historicalFailedCount ?? 0;

    // Snapshot freshness: position/cash snapshot_at 최신값 (reconciliation run 아님)
    let latestSnapshotAt: string | null = null;
    for (const positions of data.positionsMap.values()) {
      for (const p of positions) {
        if (
          p.snapshot_at &&
          (!latestSnapshotAt || p.snapshot_at > latestSnapshotAt)
        ) {
          latestSnapshotAt = p.snapshot_at;
        }
      }
    }
    for (const cash of data.cashMap.values()) {
      if (
        cash?.snapshot_at &&
        (!latestSnapshotAt || cash.snapshot_at > latestSnapshotAt)
      ) {
        latestSnapshotAt = cash.snapshot_at;
      }
    }

    // Ready state
    const readyzOk =
      data.readyz &&
      Object.values(data.readyz).every((v) => v === "ok");

    // ── Snapshot sync run status (primary indicator) ──
    const latestSyncRun = data.snapshotSyncRuns.length > 0 ? data.snapshotSyncRuns[0] : null;

    // ── Alert count (shared deriveAlerts 사용) ──
    // Dashboard가 가진 데이터로 AlertRuleInput 구성
    const alertInput = {
      health: data.health,
      healthError: apiErrors.some((e) => e.apiName === "GET /health"),
      orders: data.orders,
      ordersError: apiErrors.some((e) => e.apiName === "GET /orders"),
      reconSummary: data.reconSummary ? {
        active_locks_count: data.reconSummary.active_locks_count,
        incomplete_recon_count: data.reconSummary.incomplete_recon_count,
        activeIssueCount: data.reconSummary.activeIssueCount,
        historicalFailedCount: data.reconSummary.historicalFailedCount,
      } : null,
      reconSummaryError: apiErrors.some((e) => e.apiName === "GET /reconciliation/summary"),
      agentRuns: [],
      agentRunsError: false,
      positionsCount: totalPositions,
      positionsError: apiErrors.some((e) => e.apiName === "GET /positions"),
      snapshotSyncRun: latestSyncRun,
      snapshotSyncError: apiErrors.some((e) => e.apiName === "GET /snapshot-sync-runs"),
      latestPositionSnapshotAt: latestSnapshotAt,
      latestCashSnapshotAt: latestSnapshotAt,
      schedulerHealth: data.health?.scheduler ?? null,
      sessionData: data.sessionData ?? null,
      apiErrors,
    };
    const alertItems = deriveAlerts(alertInput);
    const urgentCount = alertItems.filter((a) => a.level === "긴급" && a.status === "OPEN").length;
    const cautionCount = alertItems.filter((a) => a.level === "주의" && a.status === "OPEN").length;

    // ── Recent alert items for compact section C (긴급+주의 only, max 5) ──
    const recentAlertItems: CompactAlertItem[] = alertItems
      .filter((a) => (a.level === "긴급" || a.level === "주의") && a.status === "OPEN")
      .slice(0, 5)
      .map((a) => ({
        id: a.id,
        level: a.level as "긴급" | "주의",
        levelVariant: a.level === "긴급" ? "error" as const : "warning" as const,
        title: a.title,
        description: a.description,
      }));

    // ── Session status derived ──
    const session = data.sessionData?.data;
    const operationsDay = data.operationsDayData?.data;
    const operationsDayHealthy = data.operationsDayData?.healthy ?? false;
    const operationsDayStaleSeconds = data.operationsDayData?.stale_seconds;
    const sessionHealthy = data.sessionData?.healthy ?? false;
    const sessionStaleSeconds = data.sessionData?.stale_seconds;
    const sessionFetchError = apiErrors.find(e => e.apiName === "GET /market-sessions/latest");
    const operationsDayFetchError = apiErrors.find(
      (e) => e.apiName === "GET /market-sessions/operations-day/latest"
    );
    const schedulerState = getSchedulerStatus(
      operationsDay ?? null,
      operationsDayHealthy,
      operationsDayStaleSeconds ?? null,
      operationsDayFetchError?.message ?? null,
      session ?? null,
      sessionHealthy,
      sessionStaleSeconds ?? null,
      !!sessionFetchError,
      sessionFetchError?.message ?? null,
    );
    const phaseVariant: 'success' | 'warning' | 'error' | 'info' | 'neutral' =
      session?.market_phase === 'OPEN' ? 'success' :
      session?.market_phase === 'PRE_MARKET' ? 'warning' :
      session?.market_phase === 'CLOSING' ? 'warning' :
      session?.market_phase === 'AFTER_HOURS' ? 'info' :
      session?.market_phase === 'HALT' ? 'error' : 'neutral';

    return {
      totalPositions,
      totalAvailableCash,
      cashUsedFallback,
      latestSnapshotAt,
      todayOrderSummary: data.todayOrderSummary,
      pendingSubmitCount,
      filledCount,
      submittedCount,
      rejectedCount,
      incompleteReconCount,
      activeLocksCount,
      activeIssueCount,
      historicalFailedCount,
      readyzOk,
      latestSyncRun,
      urgentCount,
      cautionCount,
      recentAlertItems,
      session,
      sessionData: data.sessionData,
      operationsDayData: data.operationsDayData,
      sessionHealthy,
      sessionStaleSeconds,
      phaseVariant,
      sessionEvents: data.sessionEvents,
      schedulerState,
    };
  }, [data, apiErrors]);

  /* ── Deprecated: legacy detailed sections (feature flag SHOW_DASHBOARD_SECTIONS 복원 시 사용)
  const recentEvents: RecentEvent[] = useMemo(() => {
    if (!data) return [];
    return data.orders.slice(0, 10).map((o) => ({
      id: o.order_request_id,
      time: o.created_at ?? "-",
      type: o.side ?? "-",
      description: `${o.symbol ?? "-"} ${o.requested_quantity ?? 0}주`,
      symbol: o.symbol ?? "-",
      status: o.status === "filled" ? "SUCCESS" : o.status === "rejected" ? "FAIL" : "PENDING",
    }));
  }, [data]);

  const pendingRecons: PendingRecon[] = useMemo(() => {
    if (!data) return [];
    return data.orders
      .filter((o) => o.status === "reconcile_required")
      .map((r) => ({
        id: r.order_request_id,
        type: "주문-브로커 불일치",
        account: r.account_id ?? "-",
        createdAt: r.created_at ?? "-",
      }));
  }, [data]);
  ── */

  /* ── Compact summary data (for SHOW_DASHBOARD_RECENT_SUMMARIES) ── */

  // Section A: 최근 주문/제출 내역 (created_at 내림차순 정렬 후 5개)
  const compactOrders: CompactOrderItem[] = useMemo(() => {
    if (!data) return [];
    return [...data.orders]
      .sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime())
      .slice(0, 5)
      .map((o) => {
        let sideLabel: string;
        switch (o.side) {
          case "buy": sideLabel = "매수"; break;
          case "sell": sideLabel = "매도"; break;
          default: sideLabel = o.side ?? "-";
        }
        let statusLabel: string;
        let statusVariant: "success" | "warning" | "error" | "info" | "neutral";
        switch (o.status) {
          case "filled":
            statusLabel = "체결";
            statusVariant = "success";
            break;
          case "submitted":
            statusLabel = "제출";
            statusVariant = "info";
            break;
          case "rejected":
            statusLabel = "거부";
            statusVariant = "error";
            break;
          case "reconcile_required":
            statusLabel = "조정필요";
            statusVariant = "warning";
            break;
          default:
            statusLabel = o.status;
            statusVariant = "neutral";
        }
        return {
          id: o.order_request_id,
          createdAt: o.created_at ?? "-",
          symbol: o.symbol ?? "-",
          instrumentName: o.instrument_name ?? "",
          side: sideLabel,
          quantity: o.requested_quantity ?? 0,
          status: statusLabel,
          statusVariant,
        };
      });
  }, [data]);

  // Section B: 최근 정합성 점검 (started_at 내림차순 정렬 후 5개)
  const compactReconciliationRuns: CompactReconciliationItem[] = useMemo(() => {
    if (!data) return [];
    return [...data.reconRuns]
      .sort((a, b) => new Date(b.started_at ?? 0).getTime() - new Date(a.started_at ?? 0).getTime())
      .slice(0, 5)
      .map((r) => {
        let statusLabel: string;
        let statusVariant: "success" | "warning" | "error" | "neutral";
        switch (r.status) {
          case "completed":
            statusLabel = "정상";
            statusVariant = "success";
            break;
          case "partial":
            statusLabel = "주의";
            statusVariant = "warning";
            break;
          case "failed":
            statusLabel = "긴급";
            statusVariant = "error";
            break;
          default:
            statusLabel = r.status;
            statusVariant = "neutral";
        }
        return {
          id: r.reconciliation_run_id,
          startedAt: r.started_at ?? "-",
          status: statusLabel,
          statusVariant,
          mismatchCount: (r.mismatch_count ?? 0),
          completedAt: r.completed_at,
        };
      });
  }, [data]);

  /* ── Loading / Error ── */
  if (loading) return <LoadingSpinner text="운영 데이터 로딩 중..." />;

  if (error) {
    return (
      <div className="p-6 space-y-4">
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
        <button
          onClick={fetchAll}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-[#3b82f6] rounded-lg hover:bg-[#2563eb] transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          다시 시도
        </button>
      </div>
    );
  }

  if (!data || !derived) {
    return (
      <div className="p-6">
        <ErrorBanner message="데이터를 불러오지 못했습니다" onDismiss={() => {}} />
      </div>
    );
  }

  const d = derived;

  /* ── StatusCard helpers ── */
  const apiStatus = data.health?.status === "ok" ? "정상" : "미연동";
  const apiStatusVariant = data.health?.status === "ok" ? "healthy" as const : "error" as const;

  const dbStatus = data.health?.database === "connected" || data.health?.database === "ok"
    ? "연결됨"
    : "미연동";
  const dbStatusVariant = dbStatus === "연결됨" ? "healthy" as const : "error" as const;

  const readyzStatus = d.readyzOk ? "운영 준비" : "확인 필요";
  const readyzVariant = d.readyzOk ? "healthy" as const : "error" as const;

  // ── Snapshot sync StatusCard: sync run status primary, snapshot_at secondary ──
  const syncRun = d.latestSyncRun;
  let snapshotStatus: string;
  let snapshotVariant: "healthy" | "warning" | "error" | "neutral";
  let snapshotSubtitle: string;

  if (!syncRun) {
    // No run exists
    snapshotStatus = "스냅샷 없음";
    snapshotVariant = "error";
    snapshotSubtitle = d.latestSnapshotAt
      ? `포지션/현금 snapshot_at: ${formatKstElapsed(d.latestSnapshotAt)}`
      : "동기화 이력 없음";
  } else {
    // Sync run exists — use status as primary indicator
    switch (syncRun.status) {
      case "completed":
        snapshotStatus = "정상";
        snapshotVariant = "healthy";
        break;
      case "partial":
        snapshotStatus = "주의";
        snapshotVariant = "warning";
        break;
      case "failed":
        snapshotStatus = "즉시 확인";
        snapshotVariant = "error";
        break;
      default:
        snapshotStatus = syncRun.status;
        snapshotVariant = "warning";
    }
    // Secondary: position/cash snapshot_at freshness
    const snapshotTimeStr = d.latestSnapshotAt
      ? `snapshot_at: ${formatKstElapsed(d.latestSnapshotAt)}`
      : "snapshot 데이터 없음";

    // Budget fallback / after-hours skip summary from summary_json
    let budgetLabel = "";
    const sj = syncRun.summary_json;
    if (sj) {
      const parts = formatSnapshotBudgetParts(
        parseSnapshotBudgetCounters(sj as Record<string, number>),
      );
      if (parts.length > 0) {
        budgetLabel = ` | ${parts.join(", ")}`;
      }
    }

    snapshotSubtitle = `${snapshotTimeStr} (${syncRun.succeeded_accounts}/${syncRun.total_accounts} 계좌 성공${budgetLabel})`;
  }

  const reconStatus = d.activeIssueCount > 0 || d.activeLocksCount > 0
    ? `${d.activeIssueCount + d.activeLocksCount}건`
    : "정상";
  const reconVariant = d.activeIssueCount > 0 || d.activeLocksCount > 0
    ? "warning" as const
    : "healthy" as const;

  const orderCount = data.todayOrderSummary?.total_count ?? 0;

  // Alert count status
  const alertStatusVariant: "error" | "warning" | "healthy" =
    d.urgentCount > 0 ? "error" : d.cautionCount > 0 ? "warning" : "healthy";

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">운영 대시보드</h1>
        <p className="text-sm text-[#64748b] mt-1">시스템 상태 및 오늘의 운영 현황</p>
      </div>

      {/* Warning Banner — 정합성 (active issue만 트리거) */}
      {(d.activeIssueCount > 0 || d.activeLocksCount > 0) && (
        <WarningBanner
          variant="warning"
          title={`정합성 문제: ${d.activeIssueCount}건 조치 필요`}
          message="포지션 또는 현금 불일치가 발생했습니다. 정합성 점검 화면에서 확인하세요."
        />
      )}

      {/* Warning Banner — Fallback Session */}
      {d.session?.source === 'fallback' && (
        <WarningBanner
          variant="warning"
          title="Fallback Session Detection"
          message="Session provider가 fallback 모드로 동작 중입니다. KIS live-info 연결을 확인하세요."
        />
      )}

      {/* API Errors Banner */}
      {apiErrors.length > 0 && (
        <div className="bg-[#fef2f2] border border-[#f87171] rounded-xl p-4">
          <h3 className="text-sm font-semibold text-[#991b1b] mb-2">일부 데이터를 불러오지 못했습니다</h3>
          <ul className="text-xs text-[#b91c1c] space-y-1">
            {apiErrors.map((e, i) => (
              <li key={i}>• {e.apiName}: {e.message}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Status Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
        {/* ── 항상 표시되는 핵심 카드 (7개) ── */}
        <StatusCard title="Ready 상태" value={readyzStatus} status={readyzVariant} subtitle="출처: GET /readyz" />
        <StatusCard
          title="Scheduler Status"
          value={d.schedulerState.value}
          status={d.schedulerState.variant}
          badgeLabel={d.schedulerState.badgeLabel}
          subtitle={d.schedulerState.subtitle}
        />
        <StatusCard
          title="마지막 스냅샷 동기화"
          value={snapshotStatus}
          status={snapshotVariant}
          subtitle={snapshotSubtitle}
        />
        <StatusCard
          title="오늘 주문 제출"
          value={`${orderCount}건`}
          status="neutral"
          subtitle={`출처: GET /orders/daily-summary (체결 ${d.filledCount} / 제출됨 ${d.submittedCount} / 제출대기 ${d.pendingSubmitCount})`}
        />
        <StatusCard
          title="오늘 BUY 차단"
          value={
            buyBlockSummary
              ? `${buyBlockSummary.blocked_count}건`
              : buyBlockSummaryLoading
                ? "로딩 중..."
                : "N/A"
          }
          status={
            buyBlockSummary
              ? buyBlockSummary.blocked_count > 0
                ? "warning"
                : "neutral"
              : "neutral"
          }
          subtitle=""
        />
        <StatusCard
          title="현재 포지션"
          value={`${d.totalPositions}종목`}
          status="neutral"
          subtitle={
            d.totalPositions > 0
              ? "출처: /positions (최신 스냅샷 기준, quantity>0)"
              : "포지션 없음"
          }
        />
        <StatusCard
          title="가용 현금"
          value={d.totalAvailableCash > 0 ? formatKrw(d.totalAvailableCash) : "N/A"}
          status="neutral"
          subtitle={
            d.totalAvailableCash > 0
              ? d.cashUsedFallback
                ? "출처: /cash-balance (settled_cash 없음, available_cash fallback)"
                : "출처: /cash-balance (settled_cash 합계)"
              : "데이터 없음"
          }
        />
        <StatusCard
          title="운영 경고"
          value={`긴급 ${d.urgentCount} / 주의 ${d.cautionCount}`}
          status={alertStatusVariant}
          subtitle={
            <button
              onClick={() => navigate("/operations/alerts")}
              className="text-[#3b82f6] hover:text-[#2563eb] hover:underline font-medium"
            >
              운영 경고 보기 →
            </button>
          }
        />

        {/* 최근 제출 실패 */}
        <StatusCard
          title="최근 제출 실패"
          value={
            failureSummary
              ? `오늘 ${failureSummary.today_count}건`
              : failureSummaryLoading || failuresLoading
                ? "로딩 중..."
                : failuresError
                  ? "오류"
                  : recentFailures.length === 0
                    ? "0건"
                    : `${recentFailures.length}건 발생`
          }
          status={
            failuresError
              ? "error"
              : failureSummary && failureSummary.today_count > 0
                  ? "warning"
                  : "neutral"
          }
          subtitle={
            failureSummary
              ? `실패율: ${failureSummary.failure_rate_pct_today}% (오늘) | 거절 ${failureSummary.rejected_count_today}건 · 예외 ${failureSummary.exception_count_today}건`
              : failureSummaryLoading || failuresLoading
                ? "데이터를 불러오는 중..."
                : failuresError
                  ? `API 오류: ${failuresError}`
                  : recentFailures.length === 0
                    ? "오늘 제출 실패 없음"
                    : undefined
          }
        >
          {!failuresLoading && !failuresError && recentFailures.length > 0 && (
            <div className="space-y-1.5">
              {recentFailures.map((f) => (
                <div key={f.order_request_id} className="flex items-center gap-1.5">
                  <Link
                    to={`/orders/${f.order_request_id}`}
                    className="text-xs text-[#3b82f6] hover:text-[#2563eb] hover:underline flex items-center gap-1"
                  >
                    <span className="font-mono text-[10px]">
                      {f.symbol || '(unknown)'}
                    </span>
                    {f.side && (
                      <span className={`ml-0.5 text-[10px] font-medium ${
                        f.side === 'BUY' ? 'text-red-600' : 'text-blue-600'
                      }`}>
                        {f.side}
                      </span>
                    )}
                    <span className={`ml-1 inline-flex items-center px-1 py-0.5 rounded text-[10px] font-medium ${
                      f.latest_outcome === 'exception'
                        ? 'bg-yellow-100 text-yellow-800'
                        : 'bg-red-100 text-red-800'
                    }`}>
                      {f.latest_outcome === 'exception' ? 'Exception' : 'Rejected'}
                    </span>
                    {f.latest_error_type && (
                      <span
                        className="ml-1 text-[10px] text-[#94a3b8]"
                        title={f.latest_raw_message ?? undefined}
                      >
                        {f.latest_raw_code && (
                          <span className="font-mono">[{f.latest_raw_code}] </span>
                        )}
                        {f.latest_error_type}
                        {f.latest_raw_message && (
                          <span className="italic">
                            {" "}— "{f.latest_raw_message.length > 40 ? f.latest_raw_message.slice(0, 40) + '…' : f.latest_raw_message}"
                          </span>
                        )}
                      </span>
                    )}
                  </Link>
                  {/* 제출 이력 직접 링크 — OrderDetail 거치지 않고 바로 submission attempts 페이지로 */}
                  <Link
                    to={`/orders/${f.order_request_id}/submission-attempts`}
                    className="text-[10px] text-[#3b82f6] hover:text-[#2563eb] hover:underline whitespace-nowrap"
                  >
                    제출 이력 보기 →
                  </Link>
                </div>
              ))}
              <Link
                to="/orders?status=failed"
                className="block text-[10px] text-[#94a3b8] hover:text-[#64748b] hover:underline mt-1"
              >
                모든 실패 주문 보기 →
              </Link>
            </div>
          )}
        </StatusCard>

        {/* ── 고급 카드 (feature flag로 제어) ── */}
        {SHOW_ADVANCED_OPERATION_CARDS && (
          <>
            <StatusCard title="API 상태" value={apiStatus} status={apiStatusVariant} subtitle="출처: GET /health" />
            <StatusCard title="DB 상태" value={dbStatus} status={dbStatusVariant} subtitle="출처: GET /health.database" />
            <StatusCard
              title="정합성"
              value={reconStatus}
              status={reconVariant}
              subtitle={d.activeIssueCount > 0 || d.activeLocksCount > 0 ? "수동 확인 필요" : "정상"}
            >
              <div className="space-y-1 mt-1">
                {d.activeIssueCount > 0 ? (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-[#64748b]">🟡 조치 필요</span>
                    <span className="text-sm font-semibold text-[#0f172a]">{d.activeIssueCount}건</span>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-green-600">✅ 정합성 양호</span>
                  </div>
                )}
              </div>
            </StatusCard>
            <StatusCard
              title="미실현 손익"
              value="N/A"
              status="neutral"
              subtitle="숨김 처리 (feature flag)"
            />
            <StatusCard
              title="당일 성과"
              value="N/A"
              status="neutral"
              subtitle="계산 불가 (별도 지표 필요)"
            />
          </>
        )}
      </div>

      {/* Recent Summaries Sections (feature flag) */}
      {SHOW_DASHBOARD_RECENT_SUMMARIES && (
        <div className="space-y-6">
          {/* ── Section A: 최근 주문/제출 내역 ── */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-[#0f172a]">최근 주문/제출 내역</h2>
              <button
                onClick={() => navigate("/operations/orders")}
                className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
              >
                주문 추적 보기
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
            <DataTable
              columns={[
                { key: "createdAt", header: "생성시각", width: "140px", render: (row: CompactOrderItem) => formatKstDateTime(row.createdAt) },
                { key: "symbol", header: "종목", width: "80px", render: (row: CompactOrderItem) => (
                  <span className="text-sm font-medium text-[#0f172a]">{row.symbol}</span>
                )},
                { key: "instrumentName", header: "종목명", width: "80px", render: (row: CompactOrderItem) => (
                  <span className="text-sm text-[#334155]">{row.instrumentName || "—"}</span>
                )},
                { key: "side", header: "매매", width: "90px" },
                { key: "quantity", header: "수량", width: "80px" },
                {
                  key: "status",
                  header: "상태",
                  width: "80px",
                  render: (row: CompactOrderItem) => (
                    <StatusBadge variant={row.statusVariant}>{row.status}</StatusBadge>
                  ),
                },
              ]}
              data={compactOrders}
              idKey="id"
              compact
              emptyMessage="오늘 주문 없음"
            />
          </div>

          {/* ── Section B: 최근 정합성 점검 ── */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-[#0f172a]">최근 정합성 점검</h2>
              <button
                onClick={() => navigate("/reconciliation")}
                className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
              >
                정합성 점검 보기
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
            <DataTable
              columns={[
                { key: "startedAt", header: "시작시각", width: "140px", render: (row: CompactReconciliationItem) => formatKstDateTime(row.startedAt) },
                {
                  key: "status",
                  header: "상태",
                  width: "80px",
                  render: (row: CompactReconciliationItem) => (
                    <StatusBadge variant={row.statusVariant}>{row.status}</StatusBadge>
                  ),
                },
                { key: "mismatchCount", header: "불일치건수", width: "90px" },
                {
                  key: "completedAt",
                  header: "완료시각",
                  width: "140px",
                  render: (row: CompactReconciliationItem) => (
                    <span className="text-[#64748b]">{formatKstDateTime(row.completedAt)}</span>
                  ),
                },
              ]}
              data={compactReconciliationRuns}
              idKey="id"
              compact
              emptyMessage="정합성 점검 이력 없음"
            />
          </div>

          {/* ── Section C: 최근 운영 경고 ── */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-[#0f172a]">최근 운영 경고</h2>
              <button
                onClick={() => navigate("/operations/alerts")}
                className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
              >
                운영 경고 보기
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
            <DataTable
              columns={[
                {
                  key: "level",
                  header: "수준",
                  width: "60px",
                  render: (row: CompactAlertItem) => (
                    <StatusBadge variant={row.levelVariant}>{row.level}</StatusBadge>
                  ),
                },
                { key: "title", header: "제목" },
                { key: "description", header: "설명" },
              ]}
              data={d.recentAlertItems}
              idKey="id"
              compact
              emptyMessage="운영 경고 없음"
            />
          </div>

          {/* ── Section D: 최근 Session Events ── */}
          <Panel title="Session Events" subtitle="최근 5건">
            {d.sessionEvents.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-gray-700 text-left">
                    <th className="py-1 pr-2">Time</th>
                    <th className="py-1 pr-2">Phase</th>
                    <th className="py-1 pr-2">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {d.sessionEvents.map(evt => (
                    <tr key={evt.id} className="border-b border-gray-100 dark:border-gray-800">
                      <td className="py-1 pr-2 text-xs">
                        {formatKstDateTime(evt.occurred_at)}
                      </td>
                      <td className="py-1 pr-2">
                        <StatusBadge
                          variant={
                            evt.new_phase === 'OPEN' ? 'success' :
                            evt.new_phase === 'AFTER_HOURS' ? 'info' :
                            evt.new_phase === 'HALT' ? 'error' : 'warning'
                          }
                        >
                          {evt.previous_phase ?? '-'} → {evt.new_phase ?? '-'}
                        </StatusBadge>
                      </td>
                      <td className="py-1 text-xs text-gray-500">{evt.trigger_source ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-[#94a3b8] py-2">No events yet</p>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
