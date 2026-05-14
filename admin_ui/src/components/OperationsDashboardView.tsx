import { useState, useEffect, useMemo } from "react";
import { StatusCard } from "./common/StatusCard";
import { DataTable, type Column } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { WarningBanner } from "./common/WarningBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { ArrowRight, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  getHealth,
  getReadyz,
  getClients,
  getAccounts,
  getOrders,
  getPositions,
  getCashBalance,
  getReconciliationSummary,
  getReconciliationRuns,
  getSnapshotSyncRuns,
} from "../api/client";
import type {
  HealthResponse,
  OrderSummary,
  PositionSnapshotView,
  CashBalanceSnapshotView,
  ReconciliationRunSummary,
  AccountSummary,
  ClientDetail,
  SnapshotSyncRunSummary,
} from "../types/api";
import { deriveAlerts } from "../lib/alerts";

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
  reconSummary: { active_locks_count: number; incomplete_recon_count: number } | null;
  reconRuns: ReconciliationRunSummary[];
  orders: OrderSummary[];
  accounts: AccountSummary[];
  positionsMap: Map<string, PositionSnapshotView[]>;
  cashMap: Map<string, CashBalanceSnapshotView | null>;
  snapshotSyncRuns: SnapshotSyncRunSummary[];
}

/* ── Helpers ── */
function formatCurrency(val: number | null | undefined): string {
  if (val == null || val === undefined) return "—";
  if (Number.isNaN(val)) return "—";
  const formatted = Math.abs(val).toLocaleString("ko-KR");
  const prefix = val >= 0 ? "" : "-";
  return `${prefix}${formatted}원`;
}

function formatPercent(val: number | null | undefined): string {
  if (val == null) return "N/A";
  const prefix = val >= 0 ? "+" : "";
  return `${prefix}${val.toFixed(2)}%`;
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "없음";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  return `${hours}시간 전`;
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
    const clientsPromise = getClients().catch((e) => {
      addError("GET /clients", e);
      return [] as ClientDetail[];
    });

    const [health, readyz, reconSummary, orders, clients] = await Promise.all([
      healthPromise,
      readyzPromise,
      reconSummaryPromise,
      ordersPromise,
      clientsPromise,
    ]);

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

    // ── Reconciliation runs (first account) ──
    let reconRuns: ReconciliationRunSummary[] = [];
    if (accounts.length > 0) {
      try {
        reconRuns = await getReconciliationRuns(accounts[0].account_id);
      } catch {
        addError("GET /reconciliation/runs", "정합성 실행 이력 조회 실패");
      }
    }

    // ── Snapshot sync runs ──
    let snapshotSyncRuns: SnapshotSyncRunSummary[] = [];
    try {
      snapshotSyncRuns = await getSnapshotSyncRuns(10);
    } catch {
      addError("GET /snapshot-sync-runs", "스냅샷 동기화 이력 조회 실패");
    }

    setApiErrors(errors);
    setData({
      clients,
      health,
      readyz,
      reconSummary: reconSummary as { active_locks_count: number; incomplete_recon_count: number } | null,
      reconRuns,
      orders,
      accounts,
      positionsMap,
      cashMap,
      snapshotSyncRuns,
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

    const pendingSubmitCount = data.orders.filter(
      (o) => o.status === "submitted"
    ).length;
    const reconcileRequiredCount = data.orders.filter(
      (o) => o.status === "reconcile_required"
    ).length;
    const filledCount = data.orders.filter(
      (o) => o.status === "filled"
    ).length;
    const rejectedCount = data.orders.filter(
      (o) => o.status === "rejected"
    ).length;

    const incompleteReconCount = data.reconSummary?.incomplete_recon_count ?? 0;
    const activeLocksCount = data.reconSummary?.active_locks_count ?? 0;

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
      reconSummary: data.reconSummary,
      reconSummaryError: apiErrors.some((e) => e.apiName === "GET /reconciliation/summary"),
      reconRuns: data.reconRuns,
      reconRunsError: apiErrors.some((e) => e.apiName === "GET /reconciliation/runs"),
      agentRuns: [],
      agentRunsError: false,
      positionsCount: totalPositions,
      positionsError: apiErrors.some((e) => e.apiName === "GET /positions"),
      snapshotSyncRun: latestSyncRun,
      snapshotSyncError: apiErrors.some((e) => e.apiName === "GET /snapshot-sync-runs"),
      latestPositionSnapshotAt: latestSnapshotAt,
      latestCashSnapshotAt: latestSnapshotAt,
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

    return {
      totalPositions,
      totalAvailableCash,
      cashUsedFallback,
      latestSnapshotAt,
      pendingSubmitCount,
      reconcileRequiredCount,
      filledCount,
      rejectedCount,
      incompleteReconCount,
      activeLocksCount,
      readyzOk,
      latestSyncRun,
      urgentCount,
      cautionCount,
      recentAlertItems,
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
          id: r.run_id,
          startedAt: r.started_at ?? "-",
          status: statusLabel,
          statusVariant,
          mismatchCount: (r.order_mismatches ?? 0) + (r.position_mismatches ?? 0),
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
      ? `포지션/현금 snapshot_at: ${timeAgo(d.latestSnapshotAt)}`
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
      ? `snapshot_at: ${timeAgo(d.latestSnapshotAt)}`
      : "snapshot 데이터 없음";
    snapshotSubtitle = `${snapshotTimeStr} (${syncRun.succeeded_accounts}/${syncRun.total_accounts} 계좌 성공)`;
  }

  const reconStatus = d.incompleteReconCount > 0 || d.activeLocksCount > 0
    ? `${d.incompleteReconCount + d.activeLocksCount}건`
    : "정상";
  const reconVariant = d.incompleteReconCount > 0 || d.activeLocksCount > 0
    ? "warning" as const
    : "healthy" as const;

  const orderCount = data.orders.length;

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

      {/* Warning Banner */}
      {(d.incompleteReconCount > 0 || d.activeLocksCount > 0) && (
        <WarningBanner
          variant="warning"
          title={`미해결 정합성 상태: ${d.incompleteReconCount + d.activeLocksCount}건`}
          message="포지션 또는 현금 불일치가 발생했습니다. 정합성 점검 화면에서 확인하세요."
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
        {/* ── 항상 표시되는 핵심 카드 (6개) ── */}
        <StatusCard title="Ready 상태" value={readyzStatus} status={readyzVariant} subtitle="출처: GET /readyz" />
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
          subtitle={`출처: GET /orders (체결 ${d.filledCount} / 대기 ${d.pendingSubmitCount})`}
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
          value={d.totalAvailableCash > 0 ? formatCurrency(d.totalAvailableCash) : "N/A"}
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

        {/* ── 고급 카드 (feature flag로 제어) ── */}
        {SHOW_ADVANCED_OPERATION_CARDS && (
          <>
            <StatusCard title="API 상태" value={apiStatus} status={apiStatusVariant} subtitle="출처: GET /health" />
            <StatusCard title="DB 상태" value={dbStatus} status={dbStatusVariant} subtitle="출처: GET /health.database" />
            <StatusCard
              title="미해결 정합성"
              value={reconStatus}
              status={reconVariant}
              subtitle={d.incompleteReconCount > 0 || d.activeLocksCount > 0 ? "수동 확인 필요" : "정상"}
            />
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
                { key: "createdAt", header: "생성시각", width: "140px" },
                { key: "symbol", header: "종목", width: "80px" },
                { key: "side", header: "매매", width: "60px" },
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
                { key: "startedAt", header: "시작시각", width: "140px" },
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
                    <span className="text-[#64748b]">{row.completedAt ?? "—"}</span>
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
        </div>
      )}
    </div>
  );
}
