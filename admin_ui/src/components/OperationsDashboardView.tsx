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
  getTradeDecisions,
  getAgentRuns,
  getBrokerCapacity,
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

/* ── Types ── */
interface ApiErrorEntry {
  apiName: string;
  message: string;
}

interface DashboardData {
  clients: ClientDetail[];
  health: HealthResponse | null;
  readyz: Record<string, string> | null;
  brokerCapacity: { broker_name: string; can_accept_new_entries: boolean } | null;
  reconSummary: { active_locks_count: number; incomplete_recon_count: number } | null;
  reconRuns: ReconciliationRunSummary[];
  orders: OrderSummary[];
  decisions: unknown[];
  agentRuns: unknown[];
  accounts: AccountSummary[];
  positionsMap: Map<string, PositionSnapshotView[]>;
  cashMap: Map<string, CashBalanceSnapshotView | null>;
  snapshotSyncRuns: SnapshotSyncRunSummary[];
}

/* ── Helpers ── */
function formatCurrency(val: number | null | undefined): string {
  if (val == null) return "N/A";
  const prefix = val >= 0 ? "" : "-";
  return `${prefix}$${Math.abs(val).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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

/* ── Columns ── */
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
    setApiErrors([]);

    const errors: ApiErrorEntry[] = [];
    const addError = (apiName: string, err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err);
      errors.push({ apiName, message: msg });
    };

    // ── 시스템 상태 ──
    const healthPromise = getHealth().catch((e) => {
      addError("getHealth", e);
      return null;
    });

    const readyzPromise = getReadyz().catch((e) => {
      addError("getReadyz", e);
      return null;
    });

    // ── 브로커 ──
    const brokerCapacityPromise = getBrokerCapacity().catch((e) => {
      addError("getBrokerCapacity", e);
      return null;
    });

    // ── 정합성 요약 (account_id 불필요) ──
    const reconSummaryPromise = getReconciliationSummary().catch((e) => {
      addError("getReconciliationSummary", e);
      return null;
    });

    // ── 주문 / 결정 / 에이전트 ──
    const ordersPromise = getOrders().catch((e) => {
      addError("getOrders", e);
      return [] as OrderSummary[];
    });

    const decisionsPromise = getTradeDecisions().catch((e) => {
      addError("getTradeDecisions", e);
      return [];
    });

    const agentRunsPromise = getAgentRuns().catch((e) => {
      addError("getAgentRuns", e);
      return [];
    });

    // ── 클라이언트 → 계좌 (Dashboard.tsx와 동일한 패턴) ──
    const clientsPromise = getClients().catch((e) => {
      addError("getClients", e);
      return [] as ClientDetail[];
    });

    const [health, readyz, brokerCapacity, reconSummary, orders, decisions, agentRuns, clients] =
      await Promise.all([
        healthPromise,
        readyzPromise,
        brokerCapacityPromise,
        reconSummaryPromise,
        ordersPromise,
        decisionsPromise,
        agentRunsPromise,
        clientsPromise,
      ]);

    // ── 클라이언트별 계좌 조회 (client_id 필수) ──
    let accounts: AccountSummary[] = [];
    if (clients.length > 0) {
      const results = await Promise.allSettled(
        clients.map((c) => getAccounts(c.client_id))
      );
      for (const r of results) {
        if (r.status === "fulfilled") {
          accounts.push(...r.value);
        }
      }
      if (results.some((r) => r.status === "rejected")) {
        addError("getAccounts", "일부 클라이언트 계좌 조회 실패");
      }
    }

    // ── 정합성 실행 이력 (account_id 있을 때만 호출) ──
    const firstAccountId = accounts.length > 0 ? accounts[0].account_id : null;
    let reconRuns: ReconciliationRunSummary[] = [];
    if (firstAccountId) {
      try {
        reconRuns = await getReconciliationRuns(firstAccountId);
      } catch (e) {
        addError("getReconciliationRuns", e);
      }
    }

    // ── 포지션 + 현금 (계좌별 병렬) ──
    let positionsMap = new Map<string, PositionSnapshotView[]>();
    let cashMap = new Map<string, CashBalanceSnapshotView | null>();

    if (accounts.length > 0) {
      const posResults = await Promise.allSettled(
        accounts.map((a) => getPositions(a.account_id))
      );
      const cashResults = await Promise.allSettled(
        accounts.map((a) => getCashBalance(a.account_id))
      );

      posResults.forEach((r, i) => {
        if (r.status === "fulfilled") {
          positionsMap.set(accounts[i].account_id, r.value);
        } else {
          addError(`getPositions(${accounts[i].account_id})`, r.reason);
          positionsMap.set(accounts[i].account_id, []);
        }
      });

      cashResults.forEach((r, i) => {
        if (r.status === "fulfilled") {
          cashMap.set(accounts[i].account_id, r.value);
        } else {
          addError(`getCashBalance(${accounts[i].account_id})`, r.reason);
          cashMap.set(accounts[i].account_id, null);
        }
      });
    }

    // ── Snapshot sync runs (최신 1건) ──
    let snapshotSyncRuns: SnapshotSyncRunSummary[] = [];
    try {
      snapshotSyncRuns = await getSnapshotSyncRuns(1);
    } catch (e) {
      addError("getSnapshotSyncRuns", e);
    }

    setApiErrors(errors);
    setData({
      clients,
      health,
      readyz,
      brokerCapacity,
      reconSummary,
      reconRuns,
      orders: orders ?? [],
      decisions: decisions ?? [],
      agentRuns: agentRuns ?? [],
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

  /* ── Derived metrics ── */
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

    let totalUnrealizedPnl = 0;
    for (const p of latestPositionMap.values()) {
      totalUnrealizedPnl += p.unrealized_pnl ?? 0;
    }

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

    const recentAgentFailures = (data.agentRuns as { status?: string }[]).filter(
      (r) => r.status === "failed" || r.status === "error"
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

    // Broker capacity (단일 객체)
    const brokerEntry = data.brokerCapacity;
    const brokerConnected = brokerEntry !== null;
    const brokerHealthy = brokerConnected && brokerEntry.can_accept_new_entries;

    // Ready state
    const readyzOk =
      data.readyz &&
      Object.values(data.readyz).every((v) => v === "ok");

    // ── Snapshot sync run status (primary indicator) ──
    const latestSyncRun = data.snapshotSyncRuns.length > 0 ? data.snapshotSyncRuns[0] : null;

    return {
      totalPositions,
      totalUnrealizedPnl,
      totalAvailableCash,
      cashUsedFallback,
      latestSnapshotAt,
      pendingSubmitCount,
      reconcileRequiredCount,
      filledCount,
      rejectedCount,
      recentAgentFailures,
      incompleteReconCount,
      activeLocksCount,
      brokerConnected,
      brokerHealthy,
      readyzOk,
      brokerEntry,
      latestSyncRun,
    };
  }, [data]);

  /* ── Recent events from orders ── */
  const recentEvents: RecentEvent[] = useMemo(() => {
    if (!data) return [];
    return data.orders.slice(0, 10).map((o) => ({
      id: o.order_request_id,
      time: o.created_at
        ? new Date(o.created_at).toLocaleTimeString("ko-KR", { hour12: false })
        : "-",
      type: "ORDER",
      description: `${o.side === "buy" ? "매수" : "매도"} 주문`,
      symbol: o.symbol ?? "-",
      status: o.status === "filled" || o.status === "acknowledged" ? "SUCCESS" : "PENDING",
    }));
  }, [data]);

  /* ── Pending reconciliations from recon runs ── */
  const pendingRecons: PendingRecon[] = useMemo(() => {
    if (!data?.reconRuns) return [];
    return data.reconRuns
      .filter((r) => r.status !== "completed")
      .map((r) => ({
        id: r.run_id,
        type: r.order_mismatches && r.order_mismatches > 0 ? "ORDER_MISMATCH" : "POSITION_MISMATCH",
        account: r.account_id,
        createdAt: r.started_at ?? "-",
      }));
  }, [data]);

  /* ── Loading / Error / Empty ── */
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

  if (!data || data.accounts.length === 0) {
    return (
      <div className="p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-[#0f172a]">운영 대시보드</h1>
          <p className="text-sm text-[#64748b] mt-1">시스템 상태 및 오늘의 운영 현황</p>
        </div>
        <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
          <p className="text-sm text-[#94a3b8]">계좌 데이터가 없습니다</p>
        </div>
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
      </div>
    );
  }

  const d = derived!;

  /* ── StatusCard helpers ── */
  const apiStatus = data.health?.status === "ok" ? "정상" : "미연동";
  const apiStatusVariant = data.health?.status === "ok" ? "healthy" as const : "error" as const;

  const dbStatus = data.health?.database === "connected" || data.health?.database === "ok"
    ? "연결됨"
    : "미연동";
  const dbStatusVariant = dbStatus === "연결됨" ? "healthy" as const : "error" as const;

  const readyzStatus = d.readyzOk ? "운영 준비" : "확인 필요";
  const readyzVariant = d.readyzOk ? "healthy" as const : "error" as const;

  const brokerStatus = d.brokerConnected
    ? d.brokerHealthy
      ? "여유"
      : "용량 부족"
    : "미연동";
  const brokerVariant = d.brokerConnected
    ? d.brokerHealthy
      ? "healthy" as const
      : "warning" as const
    : "error" as const;

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

  const decisionCount = (data.decisions ?? []).length;
  const orderCount = data.orders.length;

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
        <StatusCard title="API 상태" value={apiStatus} status={apiStatusVariant} subtitle="출처: GET /health" />
        <StatusCard title="DB 상태" value={dbStatus} status={dbStatusVariant} subtitle="출처: GET /health.database" />
        <StatusCard title="Ready 상태" value={readyzStatus} status={readyzVariant} subtitle="출처: GET /readyz" />
        <StatusCard
          title="브로커 용량"
          value={brokerStatus}
          status={brokerVariant}
          subtitle={d.brokerConnected ? `${d.brokerEntry?.broker_name ?? "브로커"}` : "미연동"}
        />
        <StatusCard
          title="마지막 스냅샷 동기화"
          value={snapshotStatus}
          status={snapshotVariant}
          subtitle={snapshotSubtitle}
        />
        <StatusCard
          title="미해결 정합성"
          value={reconStatus}
          status={reconVariant}
          subtitle={d.incompleteReconCount > 0 || d.activeLocksCount > 0 ? "수동 확인 필요" : "정상"}
        />
        <StatusCard
          title="오늘 AI 결정"
          value={`${decisionCount}건`}
          status="neutral"
          subtitle={
            decisionCount > 0
              ? `출처: GET /agent-runs${d.recentAgentFailures > 0 ? ` (실패 ${d.recentAgentFailures})` : ""}`
              : "데이터 없음"
          }
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
          title="미실현 손익"
          value={formatCurrency(d.totalUnrealizedPnl)}
          status={d.totalUnrealizedPnl >= 0 ? "healthy" : "warning"}
          subtitle={
            d.totalPositions > 0
              ? "출처: /positions unrealized_pnl"
              : "포지션 없음"
          }
        />
        <StatusCard
          title="당일 성과"
          value="N/A"
          status="neutral"
          subtitle="계산 불가 (별도 지표 필요)"
        />
      </div>

      {/* Recent Events Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">최근 주문 타임라인</h2>
          <button
            onClick={() => navigate("/operations/orders")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            전체 보기
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {recentEvents.length > 0 ? (
          <DataTable columns={eventColumns} data={recentEvents} idKey="id" />
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">최근 주문 내역이 없습니다</p>
          </div>
        )}
      </div>

      {/* Pending Reconciliations Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">미해결 정합성 상태</h2>
          <button
            onClick={() => navigate("/reconciliation")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            정합성 점검
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {pendingRecons.length > 0 ? (
          <DataTable columns={reconColumns} data={pendingRecons} idKey="id" />
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">미해결 정합성 상태 없음</p>
          </div>
        )}
      </div>
    </div>
  );
}
