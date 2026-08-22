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
import { formatKrw, formatKstDateTime, formatKstElapsed, getKstTodayString, toNumeric } from "../lib/utils";
import { REALIZED_PNL_CUMULATIVE_START_DATE } from "./AccountsView";
import {
  getHealth,
  getReadyz,
  getClients,
  getAccounts,
  getOrders,
  getAccountSnapshots,
  getReconciliationSummary,
  getSnapshotSyncRuns,
  getLatestMarketSession,
  getLatestOperationsDay,
  getRecentFailures,
  getFailureSummary,
  getBuyBlockSummary,
  getIndexMembershipStaleness,
  getRealizedPnlSummary,
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
  MarketSessionSummary,
  OperationsDayRunSummary,
  OperationsDayStatusResponse,
  RecentFailureItem,
  FailureSummary,
  IndexMembershipStalenessResponse,
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

/**
 * 1단계(핵심) 병렬 호출만으로 채워지는 최소 데이터 — 화면 shell과 상단 카드
 * 대부분이 이 데이터에만 의존한다. 계좌 상태(계좌→스냅샷)/snapshot-sync-runs/
 * buy-block-summary/최근 제출 실패는 각자 독립 effect로 분리되어 이 데이터를
 * 기다리지 않는다(단, 계좌 상태는 여기 포함된 clients 목록이 있어야 시작할
 * 수 있어서 core 완료 직후 별도로 시작된다).
 */
interface CoreData {
  clients: ClientDetail[];
  // GET /clients 자체가 실패했는지 여부. clients가 빈 배열이라는 사실만으로는
  // "클라이언트가 실제로 0개"인지 "조회 자체가 실패해 빈 배열로 대체됐는지"를
  // 구분할 수 없어, 계좌 상태 effect가 "계좌 없음"(empty)과 "조회 실패"(error)를
  // 헷갈리지 않도록 별도로 표시한다.
  clientsFetchFailed: boolean;
  health: HealthResponse | null;
  readyz: Record<string, string> | null;
  reconSummary: ReconciliationSummary | null;
  reconRuns: ReconciliationRunSummary[];
  orders: OrderSummary[];
  sessionData: SchedulerStatusResponse | null;
  operationsDayData: OperationsDayStatusResponse | null;
}

/* ── Helpers ── */
function formatPercent(val: number | null | undefined): string {
  if (val == null) return "N/A";
  const prefix = val >= 0 ? "+" : "";
  return `${prefix}${val.toFixed(2)}%`;
}

/** RealizedPnlView.tsx/AccountsView.tsx의 pnlClass/formatSignedKrw와 동일한 표시 규칙. */
function formatSignedKrw(val: number): string {
  return `${val >= 0 ? "+" : ""}${formatKrw(val)}`;
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

  // ── 여러 독립 fetch가 공유하는 에러 배너용 목록 ──
  const [apiErrors, setApiErrors] = useState<ApiErrorEntry[]>([]);
  const addApiError = (apiName: string, err: unknown) => {
    setApiErrors((prev) => [...prev, { apiName, message: String(err) }]);
  };

  // ── 1단계(core): 화면 shell + 상단 카드 대부분에 필요한 최소 데이터 ──
  const [coreLoading, setCoreLoading] = useState(true);
  const [coreFetchError, setCoreFetchError] = useState<string | null>(null);
  const [coreData, setCoreData] = useState<CoreData | null>(null);

  // ── 계좌 상태(계좌 목록 → 계좌 스냅샷) — core와 독립된 자체 loading/error ──
  const [accountStatusLoading, setAccountStatusLoading] = useState(true);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [positionsMap, setPositionsMap] = useState<Map<string, PositionSnapshotView[]>>(new Map());
  const [cashMap, setCashMap] = useState<Map<string, CashBalanceSnapshotView | null>>(new Map());
  // 계좌 목록 자체를 하나도 못 가져왔거나, 가져온 계좌 전부의 스냅샷 조회가
  // 실패한 경우(전체 실패) — "0건/정상"처럼 보이지 않도록 별도로 구분한다.
  const [accountStatusFatalError, setAccountStatusFatalError] = useState<string | null>(null);
  // 계좌 스냅샷 중 일부만 실패한 경우(부분 실패) 건수.
  const [accountStatusFailedCount, setAccountStatusFailedCount] = useState(0);

  // ── 총손익 — AccountsView.tsx "계좌 상세"의 총손익 카드와 정의를 그대로
  // 맞춘다: 계좌별 (미실현 손익 + 실현손익 누적[REALIZED_PNL_CUMULATIVE_
  // START_DATE~오늘] − 현재 포지션 매수 수수료 합계)를 계좌별로 계산한 뒤
  // 전체 계좌에 대해 합산한다. 미실현 손익/매수 수수료는 이미 계좌 상태
  // fan-out(positionsMap/cashMap)에서 받아온 데이터를 그대로 재사용하므로
  // 추가 API 호출이 필요 없다 — 실현손익 누적만 별도 API
  // (`/performance/realized-pnl/summary`)로 계좌별 fire-and-forget 병행
  // 조회한다(accountStatusLoading을 기다리지 않는다).
  // 계좌별 실현손익 누적(성공한 계좌만 담김 — 실패한 계좌는 key 자체가 없음).
  const [realizedPnlByAccount, setRealizedPnlByAccount] = useState<Map<string, number>>(new Map());
  const [realizedPnlLoading, setRealizedPnlLoading] = useState(true);

  // ── snapshot-sync-runs — 계좌 fan-out과 무관, 독립적으로 fetch ──
  const [snapshotSyncRuns, setSnapshotSyncRuns] = useState<SnapshotSyncRunSummary[]>([]);
  const [snapshotSyncLoading, setSnapshotSyncLoading] = useState(true);
  const [snapshotSyncError, setSnapshotSyncError] = useState<string | null>(null);

  // ── UNIV-4: 지수 편입 staleness — 경고 배너 전용, 독립적으로 fetch ──
  const [indexMembershipStaleness, setIndexMembershipStaleness] =
    useState<IndexMembershipStalenessResponse | null>(null);

  // ── 오늘 BUY 차단 ──
  const [buyBlockSummary, setBuyBlockSummary] = useState<BuyBlockSummary | null>(null);
  const [buyBlockSummaryLoading, setBuyBlockSummaryLoading] = useState(true);
  const [buyBlockSummaryError, setBuyBlockSummaryError] = useState<string | null>(null);

  // ── 최근 제출 실패 ──
  const [failureSummary, setFailureSummary] = useState<FailureSummary | null>(null);
  const [failureSummaryLoading, setFailureSummaryLoading] = useState(true);
  const [recentFailures, setRecentFailures] = useState<RecentFailureItem[]>([]);
  const [failuresLoading, setFailuresLoading] = useState(true);
  const [failuresError, setFailuresError] = useState<string | null>(null);

  // 1단계: health/readyz/reconciliation-summary/orders(오늘)/clients/session/
  // operations-day 7개는 서로 데이터 의존성이 없어 Promise.all로 동시에
  // 부르고, 이 7개만 끝나면 화면 shell과 상단 카드 대부분을 그린다.
  // 계좌 상태/snapshot-sync-runs/buy-block-summary/최근 제출 실패는 각자
  // 독립된 effect로 분리해 이 1단계 완료를 기다리지 않는다 — 예전에는
  // 이들이 계좌 스냅샷 fan-out 뒤에 순차로 묶여 있어(서로 의존성이 없는데도)
  // 화면 전체 loading을 불필요하게 늘렸다.
  const fetchCore = async () => {
    setCoreLoading(true);
    setCoreFetchError(null);
    try {
      let clientsFetchFailed = false;
      const [health, readyz, reconSummary, orders, clients, sessionData, operationsDayData] =
        await Promise.all([
          getHealth().catch((e) => {
            addApiError("GET /health", e);
            return null;
          }),
          getReadyz().catch((e) => {
            addApiError("GET /readyz", e);
            return null;
          }),
          getReconciliationSummary().catch((e) => {
            addApiError("GET /reconciliation/summary", e);
            return null;
          }),
          // "오늘의 운영 현황" 대시보드이므로 이 화면이 쓰는 주문 목록(최근
          // 5건 요약 등)은 애초에 오늘 것만 필요하다 — date 필터 없이 부르면
          // 전체 이력을 스캔해 today 필터보다 눈에 띄게 느렸다(실측: 무필터
          // ~19-25ms vs date=today ~3ms).
          getOrders(undefined, undefined, getKstTodayString()).catch((e) => {
            addApiError("GET /orders?date=today", e);
            return [] as OrderSummary[];
          }),
          getClients().catch((e) => {
            addApiError("GET /clients", e);
            clientsFetchFailed = true;
            return [] as ClientDetail[];
          }),
          getLatestMarketSession().catch((e) => {
            addApiError("GET /market-sessions/latest", e);
            return null;
          }),
          getLatestOperationsDay().catch((e) => {
            addApiError("GET /market-sessions/operations-day/latest", e);
            return null;
          }),
        ]);

      // ── Reconciliation runs (summary의 recentActiveIssues — active-only) ──
      // NOTE: 별도 getReconciliationRuns API 호출 대신 이미 fetch된 summary
      //       응답의 recentActiveIssues를 사용한다(백엔드에서 active-only로
      //       필터링됨).
      const reconRuns: ReconciliationRunSummary[] = (reconSummary?.recentActiveIssues ?? []).slice(0, 5);

      setCoreData({
        clients,
        clientsFetchFailed,
        health,
        readyz,
        reconSummary: reconSummary as ReconciliationSummary | null,
        reconRuns,
        orders,
        sessionData: sessionData as SchedulerStatusResponse | null,
        operationsDayData: operationsDayData as OperationsDayStatusResponse | null,
      });
    } finally {
      setCoreLoading(false);
    }
  };

  // 계좌 상태(계좌 목록 → 계좌 스냅샷)는 core의 clients 결과가 있어야
  // 시작할 수 있지만, 이 조회 자체는 core의 나머지 6개 API나 화면 shell
  // 렌더링을 기다리게 만들지 않는다 — 별도 loading/error state로 "계좌
  // 상태" 영역과 "운영 경고" 카드에만 반영된다.
  // 총손익(실현손익 합계)은 계좌 스냅샷(포지션/현금) fan-out과 데이터
  // 의존성이 없는 별도 API라, fetchAccountStatus 안에서 await하지 않고
  // fire-and-forget으로 병행 실행한다 — accountStatusLoading이 끝나는
  // 시점과 무관하게 자체 loading/error로 표시된다.
  const fetchRealizedPnlTotal = async (accountsList: AccountSummary[]) => {
    setRealizedPnlLoading(true);
    try {
      if (accountsList.length === 0) {
        setRealizedPnlByAccount(new Map());
        return;
      }
      // AccountsView.tsx "계좌 상세" 총손익 카드와 동일한 누적 시작일.
      const startDate = REALIZED_PNL_CUMULATIVE_START_DATE;
      const endDate = getKstTodayString();
      const results = await Promise.allSettled(
        accountsList.map((a) =>
          getRealizedPnlSummary(a.account_id, { startDate, endDate }).then((r) => ({
            accountId: a.account_id,
            netSum: toNumeric(r.realized_pnl_net_sum),
          })),
        ),
      );
      const nextMap = new Map<string, number>();
      let failedCount = 0;
      results.forEach((r) => {
        if (r.status === "fulfilled") nextMap.set(r.value.accountId, r.value.netSum);
        else failedCount += 1;
      });
      if (failedCount > 0) {
        addApiError("GET /performance/realized-pnl/summary", "일부 계좌 실현손익 조회 실패");
      }
      setRealizedPnlByAccount(nextMap);
    } finally {
      setRealizedPnlLoading(false);
    }
  };

  const fetchAccountStatus = async (clients: ClientDetail[], clientsFetchFailed: boolean) => {
    setAccountStatusLoading(true);
    setAccountStatusFatalError(null);
    setAccountStatusFailedCount(0);
    try {
      if (clients.length === 0) {
        setAccounts([]);
        setPositionsMap(new Map());
        setCashMap(new Map());
        fetchRealizedPnlTotal([]);
        // clients가 빈 배열인 이유가 "클라이언트가 실제로 0개"인지 "GET
        // /clients 자체가 실패해 빈 배열로 대체됐는지"를 구분한다 — 후자를
        // "계좌 없음"(empty)으로 보여주면 API 실패가 정상 데이터처럼 보인다.
        if (clientsFetchFailed) {
          setAccountStatusFatalError("계좌 목록을 불러오지 못했습니다");
        }
        return;
      }

      const clientResults = await Promise.allSettled(
        clients.map((c) => getAccounts(c.client_id)),
      );
      const nextAccounts: AccountSummary[] = [];
      let clientFailureCount = 0;
      clientResults.forEach((r) => {
        if (r.status === "fulfilled") nextAccounts.push(...r.value);
        else clientFailureCount += 1;
      });
      if (clientFailureCount > 0) {
        addApiError("GET /accounts", "일부 클라이언트 계좌 조회 실패");
      }
      setAccounts(nextAccounts);
      fetchRealizedPnlTotal(nextAccounts);

      if (nextAccounts.length === 0) {
        setPositionsMap(new Map());
        setCashMap(new Map());
        if (clientFailureCount > 0 && clientFailureCount === clients.length) {
          setAccountStatusFatalError("계좌 목록을 불러오지 못했습니다");
        }
        return;
      }

      const snapshotResults = await Promise.allSettled(
        nextAccounts.map((a) =>
          getAccountSnapshots(a.account_id).then((snapshot) => ({
            accountId: a.account_id,
            positions: snapshot.positions,
            cash: snapshot.cash_balance,
          })),
        ),
      );
      const nextPositionsMap = new Map<string, PositionSnapshotView[]>();
      const nextCashMap = new Map<string, CashBalanceSnapshotView | null>();
      let snapshotFailureCount = 0;
      snapshotResults.forEach((r) => {
        if (r.status === "fulfilled") {
          nextPositionsMap.set(r.value.accountId, r.value.positions);
          nextCashMap.set(r.value.accountId, r.value.cash);
        } else {
          snapshotFailureCount += 1;
        }
      });
      if (snapshotFailureCount > 0) {
        addApiError("GET /account-snapshots/latest", "일부 계좌 스냅샷 조회 실패");
      }
      setPositionsMap(nextPositionsMap);
      setCashMap(nextCashMap);
      setAccountStatusFailedCount(snapshotFailureCount);
      if (snapshotFailureCount === nextAccounts.length) {
        setAccountStatusFatalError("모든 계좌의 스냅샷 조회에 실패했습니다");
      }
    } finally {
      setAccountStatusLoading(false);
    }
  };

  const fetchSnapshotSyncRuns = async () => {
    setSnapshotSyncLoading(true);
    setSnapshotSyncError(null);
    try {
      const runs = await getSnapshotSyncRuns(10);
      setSnapshotSyncRuns(runs);
    } catch (e) {
      setSnapshotSyncError(String(e));
      addApiError("GET /snapshot-sync-runs", "스냅샷 동기화 이력 조회 실패");
    } finally {
      setSnapshotSyncLoading(false);
    }
  };

  const fetchIndexMembershipStaleness = async () => {
    try {
      const result = await getIndexMembershipStaleness();
      setIndexMembershipStaleness(result);
    } catch (e) {
      addApiError("GET /instruments/index-membership/staleness", e);
    }
  };

  const fetchBuyBlockSummary = async () => {
    setBuyBlockSummaryLoading(true);
    setBuyBlockSummaryError(null);
    try {
      const result = await getBuyBlockSummary();
      setBuyBlockSummary(result);
    } catch (e) {
      setBuyBlockSummaryError(String(e));
      addApiError("GET /orders/buy-block-summary", e);
    } finally {
      setBuyBlockSummaryLoading(false);
    }
  };

  const fetchFailures = async () => {
    setFailuresLoading(true);
    setFailureSummaryLoading(true);
    setFailuresError(null);
    try {
      const [failuresData, summaryData] = await Promise.all([
        getRecentFailures(5, getKstTodayString()).catch((e) => {
          setFailuresError(String(e));
          return [] as RecentFailureItem[];
        }),
        getFailureSummary().catch((e) => {
          addApiError("GET /orders/failure-summary", e);
          return null;
        }),
      ]);
      setRecentFailures(failuresData);
      setFailureSummary(summaryData);
    } finally {
      setFailuresLoading(false);
      setFailureSummaryLoading(false);
    }
  };

  useEffect(() => {
    fetchCore();
  }, []);
  useEffect(() => {
    fetchSnapshotSyncRuns();
  }, []);
  useEffect(() => {
    fetchIndexMembershipStaleness();
  }, []);
  useEffect(() => {
    fetchBuyBlockSummary();
  }, []);
  useEffect(() => {
    fetchFailures();
  }, []);
  // 계좌 상태는 core의 clients 결과가 준비된 직후에만 시작한다(core 전체
  // 완료를 기다리는 게 아니라, coreData가 채워지는 시점에 바로 뒤이어).
  useEffect(() => {
    if (!coreData) return;
    fetchAccountStatus(coreData.clients, coreData.clientsFetchFailed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coreData]);

  const refetchAll = () => {
    setApiErrors([]);
    fetchCore();
    fetchSnapshotSyncRuns();
    fetchIndexMembershipStaleness();
    fetchBuyBlockSummary();
    fetchFailures();
    // fetchAccountStatus는 coreData가 갱신되면 위 useEffect가 다시 실행한다.
  };

  /* ── 계좌 상태 파생값(총자산/가용 현금/현재 포지션) ── */
  const accountDerived = useMemo(() => {
    // ── Position dedup: instrument_id 기준 최신 snapshot (AccountsView와 동일 기준) ──
    const latestPositionMap = new Map<string, PositionSnapshotView>();
    for (const positions of positionsMap.values()) {
      for (const p of positions) {
        const existing = latestPositionMap.get(p.instrument_id);
        if (!existing || p.snapshot_at > existing.snapshot_at) {
          latestPositionMap.set(p.instrument_id, p);
        }
      }
    }
    const totalPositions = Array.from(latestPositionMap.values()).filter(
      (p) => (p.quantity ?? 0) > 0
    ).length;

    // ── Cash balance: orderable_amount 우선, fallback available_cash ──
    let totalAvailableCash = 0;
    let cashUsedFallback = false;
    // ── 총자산: cash_balance.total_asset 합산. 이 필드는 KIS output2의
    //    tot_evlu_amt(총평가금액)를 그대로 담는 optional 필드라(types/api.ts
    //    CashBalanceSnapshotView 참고), 특정 스냅샷에는 값이 없을 수 있다 —
    //    그 경우 0으로 조용히 합산하지 않고 "미확인 계좌 수"로 별도 집계해
    //    합계가 실제보다 적어 보이는 착시를 방지한다.
    let totalAssetSum = 0;
    let totalAssetMissingCount = 0;
    for (const cash of cashMap.values()) {
      if (cash) {
        const val = cash.orderable_amount ?? cash.available_cash;
        if (val !== null && val !== undefined) {
          totalAvailableCash += val;
        }
        if (cash.orderable_amount === null || cash.orderable_amount === undefined) {
          cashUsedFallback = true;
        }
        if (cash.total_asset !== null && cash.total_asset !== undefined) {
          totalAssetSum += cash.total_asset;
        } else {
          totalAssetMissingCount += 1;
        }
      }
    }

    // Snapshot freshness: position/cash snapshot_at 최신값 (reconciliation run 아님)
    let latestSnapshotAt: string | null = null;
    for (const positions of positionsMap.values()) {
      for (const p of positions) {
        if (p.snapshot_at && (!latestSnapshotAt || p.snapshot_at > latestSnapshotAt)) {
          latestSnapshotAt = p.snapshot_at;
        }
      }
    }
    for (const cash of cashMap.values()) {
      if (cash?.snapshot_at && (!latestSnapshotAt || cash.snapshot_at > latestSnapshotAt)) {
        latestSnapshotAt = cash.snapshot_at;
      }
    }

    return {
      totalPositions,
      totalAvailableCash,
      cashUsedFallback,
      totalAssetSum,
      totalAssetMissingCount,
      latestSnapshotAt,
    };
  }, [positionsMap, cashMap]);

  // ── 총손익 — AccountsView.tsx "계좌 상세" 총손익 카드와 동일한 정의를
  // 계좌별로 계산해 합산한다: 미실현 손익(cash_balance.total_unrealized_pnl
  // 우선, 없으면 포지션 unrealized_pnl 합) + 실현손익 누적
  // (realizedPnlByAccount) − 현재 포지션 매수 수수료 합계
  // (remaining_buy_fee_pool). 실현손익 조회에 실패한 계좌는 map에 key가
  // 없으므로 계산에서 제외한다(부분 실패 시 성공한 계좌만 반영).
  const totalPnlDerived = useMemo(() => {
    let sum = 0;
    let includedCount = 0;
    for (const [accountId, realizedSum] of realizedPnlByAccount.entries()) {
      const positions = positionsMap.get(accountId) ?? [];
      const latestPositionMap = new Map<string, PositionSnapshotView>();
      for (const p of positions) {
        if ((p.quantity ?? 0) <= 0) continue;
        const existing = latestPositionMap.get(p.instrument_id);
        if (!existing || p.snapshot_at > existing.snapshot_at) {
          latestPositionMap.set(p.instrument_id, p);
        }
      }
      const latestPositions = Array.from(latestPositionMap.values());
      const cash = cashMap.get(accountId);
      const unrealizedPnl =
        cash?.total_unrealized_pnl != null
          ? cash.total_unrealized_pnl
          : latestPositions.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0);
      const feePool = latestPositions.reduce((s, p) => s + (p.remaining_buy_fee_pool ?? 0), 0);
      sum += unrealizedPnl + realizedSum - feePool;
      includedCount += 1;
    }
    return { sum, includedCount };
  }, [realizedPnlByAccount, positionsMap, cashMap]);

  /* ── core 파생값(스케줄러/세션/정합성 등) ── */
  const coreDerived = useMemo(() => {
    if (!coreData) return null;

    const incompleteReconCount = coreData.reconSummary?.incomplete_recon_count ?? 0;
    const activeLocksCount = coreData.reconSummary?.active_locks_count ?? 0;
    const activeIssueCount = coreData.reconSummary?.activeIssueCount ?? 0;
    const historicalFailedCount = coreData.reconSummary?.historicalFailedCount ?? 0;

    const readyzOk =
      coreData.readyz && Object.values(coreData.readyz).every((v) => v === "ok");

    const session = coreData.sessionData?.data;
    const operationsDay = coreData.operationsDayData?.data;
    const operationsDayHealthy = coreData.operationsDayData?.healthy ?? false;
    const operationsDayStaleSeconds = coreData.operationsDayData?.stale_seconds;
    const sessionHealthy = coreData.sessionData?.healthy ?? false;
    const sessionStaleSeconds = coreData.sessionData?.stale_seconds;
    const sessionFetchError = apiErrors.find((e) => e.apiName === "GET /market-sessions/latest");
    const operationsDayFetchError = apiErrors.find(
      (e) => e.apiName === "GET /market-sessions/operations-day/latest",
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
    const phaseVariant: "success" | "warning" | "error" | "info" | "neutral" =
      session?.market_phase === "OPEN" ? "success" :
      session?.market_phase === "PRE_MARKET" ? "warning" :
      session?.market_phase === "CLOSING" ? "warning" :
      session?.market_phase === "AFTER_HOURS" ? "info" :
      session?.market_phase === "HALT" ? "error" : "neutral";

    return {
      incompleteReconCount,
      activeLocksCount,
      activeIssueCount,
      historicalFailedCount,
      readyzOk,
      session,
      sessionHealthy,
      sessionStaleSeconds,
      phaseVariant,
      schedulerState,
    };
  }, [coreData, apiErrors]);

  // ── "운영 경고"는 계좌 상태(포지션 수/최신 snapshot_at)와 snapshot-sync-runs
  //    상태까지 반영해야 정확하다 — 둘 중 하나라도 아직 로딩 중이면 "0건/정상"
  //    으로 착시를 주지 않도록 alertsReady가 true가 될 때까지 집계하지 않는다.
  const alertsReady = !!coreData && !accountStatusLoading && !snapshotSyncLoading;
  const alertsDerived = useMemo(() => {
    if (!alertsReady || !coreData) return null;

    const latestSyncRun = snapshotSyncRuns.length > 0 ? snapshotSyncRuns[0] : null;

    const alertInput = {
      health: coreData.health,
      healthError: apiErrors.some((e) => e.apiName === "GET /health"),
      orders: coreData.orders,
      ordersError: apiErrors.some((e) => e.apiName === "GET /orders"),
      reconSummary: coreData.reconSummary
        ? {
            active_locks_count: coreData.reconSummary.active_locks_count,
            incomplete_recon_count: coreData.reconSummary.incomplete_recon_count,
            activeIssueCount: coreData.reconSummary.activeIssueCount,
            historicalFailedCount: coreData.reconSummary.historicalFailedCount,
          }
        : null,
      reconSummaryError: apiErrors.some((e) => e.apiName === "GET /reconciliation/summary"),
      agentRuns: [],
      agentRunsError: false,
      positionsCount: accountDerived.totalPositions,
      positionsError: !!accountStatusFatalError,
      snapshotSyncRun: latestSyncRun,
      snapshotSyncError: !!snapshotSyncError,
      latestPositionSnapshotAt: accountDerived.latestSnapshotAt,
      latestCashSnapshotAt: accountDerived.latestSnapshotAt,
      schedulerHealth: coreData.health?.scheduler ?? null,
      sessionData: coreData.sessionData ?? null,
      apiErrors,
    };
    const alertItems = deriveAlerts(alertInput);
    const urgentCount = alertItems.filter((a) => a.level === "긴급" && a.status === "OPEN").length;
    const cautionCount = alertItems.filter((a) => a.level === "주의" && a.status === "OPEN").length;
    const recentAlertItems: CompactAlertItem[] = alertItems
      .filter((a) => (a.level === "긴급" || a.level === "주의") && a.status === "OPEN")
      .slice(0, 5)
      .map((a) => ({
        id: a.id,
        level: a.level as "긴급" | "주의",
        levelVariant: a.level === "긴급" ? ("error" as const) : ("warning" as const),
        title: a.title,
        description: a.description,
      }));

    return { urgentCount, cautionCount, recentAlertItems };
  }, [
    alertsReady,
    coreData,
    apiErrors,
    accountDerived,
    accountStatusFatalError,
    snapshotSyncRuns,
    snapshotSyncError,
  ]);

  /* ── Compact summary data (for SHOW_DASHBOARD_RECENT_SUMMARIES) ── */

  // Section A: 최근 주문/제출 내역 (created_at 내림차순 정렬 후 5개)
  const compactOrders: CompactOrderItem[] = useMemo(() => {
    if (!coreData) return [];
    return [...coreData.orders]
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
  }, [coreData]);

  // Section B: 최근 정합성 점검 (started_at 내림차순 정렬 후 5개)
  const compactReconciliationRuns: CompactReconciliationItem[] = useMemo(() => {
    if (!coreData) return [];
    return [...coreData.reconRuns]
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
  }, [coreData]);

  /* ── Loading / Error (core만 화면 shell을 막는다) ── */
  if (coreLoading) return <LoadingSpinner text="운영 데이터 로딩 중..." />;

  if (coreFetchError) {
    return (
      <div className="p-6 space-y-4">
        <ErrorBanner message={coreFetchError} onDismiss={() => setCoreFetchError(null)} />
        <button
          onClick={refetchAll}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-[#3b82f6] rounded-lg hover:bg-[#2563eb] transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          다시 시도
        </button>
      </div>
    );
  }

  if (!coreData || !coreDerived) {
    return (
      <div className="p-6">
        <ErrorBanner message="데이터를 불러오지 못했습니다" onDismiss={() => {}} />
      </div>
    );
  }

  const d = coreDerived;

  /* ── StatusCard helpers ── */
  const apiStatus = coreData.health?.status === "ok" ? "정상" : "미연동";
  const apiStatusVariant = coreData.health?.status === "ok" ? "healthy" as const : "error" as const;

  const dbStatus = coreData.health?.database === "connected" || coreData.health?.database === "ok"
    ? "연결됨"
    : "미연동";
  const dbStatusVariant = dbStatus === "연결됨" ? "healthy" as const : "error" as const;

  const readyzStatus = d.readyzOk ? "운영 준비" : "확인 필요";
  const readyzVariant = d.readyzOk ? "healthy" as const : "error" as const;

  // ── Snapshot sync StatusCard: sync run status primary, snapshot_at secondary ──
  // snapshot-sync-runs는 계좌 fan-out과 무관한 독립 fetch라, 이 카드는
  // snapshotSyncLoading 동안만 "로딩 중"이고 core 전체를 기다리지 않는다.
  const latestSyncRun = snapshotSyncRuns.length > 0 ? snapshotSyncRuns[0] : null;
  let snapshotStatus: string;
  let snapshotVariant: "healthy" | "warning" | "error" | "neutral";
  let snapshotSubtitle: string;

  if (snapshotSyncLoading) {
    snapshotStatus = "로딩 중...";
    snapshotVariant = "neutral";
    snapshotSubtitle = "스냅샷 동기화 이력을 불러오는 중...";
  } else if (snapshotSyncError) {
    snapshotStatus = "오류";
    snapshotVariant = "error";
    snapshotSubtitle = `API 오류: ${snapshotSyncError}`;
  } else if (!latestSyncRun) {
    snapshotStatus = "스냅샷 없음";
    snapshotVariant = "error";
    snapshotSubtitle = accountDerived.latestSnapshotAt
      ? `포지션/현금 snapshot_at: ${formatKstElapsed(accountDerived.latestSnapshotAt)}`
      : "동기화 이력 없음";
  } else {
    switch (latestSyncRun.status) {
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
        snapshotStatus = latestSyncRun.status;
        snapshotVariant = "warning";
    }
    const snapshotTimeStr = accountDerived.latestSnapshotAt
      ? `snapshot_at: ${formatKstElapsed(accountDerived.latestSnapshotAt)}`
      : "snapshot 데이터 없음";

    let budgetLabel = "";
    const sj = latestSyncRun.summary_json;
    if (sj) {
      const parts = formatSnapshotBudgetParts(
        parseSnapshotBudgetCounters(sj as Record<string, number>),
      );
      if (parts.length > 0) {
        budgetLabel = ` | ${parts.join(", ")}`;
      }
    }

    snapshotSubtitle = `${snapshotTimeStr} (${latestSyncRun.succeeded_accounts}/${latestSyncRun.total_accounts} 계좌 성공${budgetLabel})`;
  }

  const reconStatus = d.activeIssueCount > 0 || d.activeLocksCount > 0
    ? `${d.activeIssueCount + d.activeLocksCount}건`
    : "정상";
  const reconVariant = d.activeIssueCount > 0 || d.activeLocksCount > 0
    ? "warning" as const
    : "healthy" as const;

  // ── 운영 경고 카드 값 ──
  const alertsLoading = !alertsReady;
  const alertStatusVariant: "error" | "warning" | "healthy" | "neutral" = alertsLoading
    ? "neutral"
    : (alertsDerived!.urgentCount > 0 ? "error" : alertsDerived!.cautionCount > 0 ? "warning" : "healthy");

  // ── 계좌 상태 영역 표시 문구 ──
  const accountStatusHasData = accounts.length > 0 || cashMap.size > 0 || positionsMap.size > 0;

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

      {/* Warning Banner — UNIV-4: 지수 편입 데이터 staleness (read-only 감시, 독립 fetch) */}
      {indexMembershipStaleness?.is_stale && (
        <WarningBanner
          variant="warning"
          title="지수 편입(index membership) 데이터가 오래되었습니다"
          message={
            indexMembershipStaleness.latest_effective_from
              ? `마지막 반영: ${indexMembershipStaleness.latest_effective_from} (경과 ${indexMembershipStaleness.age_days}일, 기준 ${
                  indexMembershipStaleness.threshold_days != null
                    ? `${indexMembershipStaleness.threshold_days}일 override`
                    : `${indexMembershipStaleness.threshold_months ?? 6}개월`
                }). [RUNBOOK] index_membership_source_package_apply.md 절차로 갱신하세요.`
              : "지수 편입 데이터가 전혀 없습니다. [RUNBOOK] index_membership_source_package_apply.md 절차로 초기 반영하세요."
          }
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

      {/* Status Summary Cards — 6개만 남긴다(오늘 주문 제출/현재 포지션/
          가용 현금은 아래 "계좌 상태" 영역으로 이동하거나 제거) */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
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
          title="운영 경고"
          value={alertsLoading ? "집계 중..." : `긴급 ${alertsDerived!.urgentCount} / 주의 ${alertsDerived!.cautionCount}`}
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
        <StatusCard
          title="오늘 BUY 차단"
          value={
            buyBlockSummaryLoading
              ? "로딩 중..."
              : buyBlockSummaryError
                ? "오류"
                : buyBlockSummary
                  ? `${buyBlockSummary.blocked_count}건`
                  : "N/A"
          }
          status={
            buyBlockSummaryError
              ? "error"
              : buyBlockSummary
                ? buyBlockSummary.blocked_count > 0
                  ? "warning"
                  : "neutral"
                : "neutral"
          }
          subtitle={buyBlockSummaryError ? `API 오류: ${buyBlockSummaryError}` : ""}
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

      {/* ── 계좌 상태 영역 (총자산/가용 현금/현재 포지션) ──
          계좌 목록→계좌 스냅샷 fan-out은 core와 독립적으로 진행되므로,
          이 영역만 자체 loading/부분 실패/전체 실패 상태를 표시한다. */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-[#0f172a]">계좌 상태</h2>
        <Panel>
          {accountStatusLoading ? (
            <p className="text-sm text-[#64748b]">계좌 상태를 불러오는 중...</p>
          ) : accountStatusFatalError ? (
            <p className="text-sm text-[#991b1b]">
              {accountStatusFatalError} — 계좌/스냅샷 API 응답을 확인하세요.
            </p>
          ) : (
            <>
              {accountStatusFailedCount > 0 && (
                <p className="text-xs text-[#b91c1c] mb-3">
                  일부 계좌({accountStatusFailedCount}개) 스냅샷 조회 실패 — 아래 수치는 조회에 성공한 계좌만 반영합니다.
                </p>
              )}
              {!accountStatusHasData ? (
                <p className="text-sm text-[#64748b]">조회된 계좌가 없습니다.</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  <StatusCard
                    title="총자산"
                    value={
                      accountDerived.totalAssetSum > 0 || accountDerived.totalAssetMissingCount === 0
                        ? formatKrw(accountDerived.totalAssetSum)
                        : "N/A"
                    }
                    status="neutral"
                    subtitle={
                      accountDerived.totalAssetMissingCount > 0
                        ? `총자산 필드 없는 계좌 ${accountDerived.totalAssetMissingCount}건 제외 합계 (출처: cash_balance.total_asset)`
                        : "출처: cash_balance.total_asset 합계"
                    }
                  />
                  <StatusCard
                    title="가용 현금"
                    value={d && accountDerived.totalAvailableCash > 0 ? formatKrw(accountDerived.totalAvailableCash) : "N/A"}
                    status="neutral"
                    subtitle={
                      accountDerived.totalAvailableCash > 0
                        ? accountDerived.cashUsedFallback
                          ? "출처: /cash-balance (orderable_amount 없음, available_cash fallback)"
                          : "출처: /cash-balance (orderable_amount 합계)"
                        : "데이터 없음"
                    }
                  />
                  <StatusCard
                    title="현재 포지션"
                    value={`${accountDerived.totalPositions}종목`}
                    status="neutral"
                    subtitle={
                      accountDerived.totalPositions > 0
                        ? "출처: /positions (최신 스냅샷 기준, quantity>0)"
                        : "포지션 없음"
                    }
                  />
                  {/* 총손익 — AccountsView.tsx "계좌 상세" 총손익 카드와 동일한
                      정의(미실현 + 실현손익 누적 − 매수 수수료 pool)를 계좌별로
                      계산해 합산한다. 실현손익 누적만 별도 fetch라 계좌 스냅샷
                      fan-out과는 별개로 자체 loading/전체 실패/부분 실패 상태를
                      따로 표시한다. */}
                  {(() => {
                    const totalPnlLoading = realizedPnlLoading || accountStatusLoading;
                    const totalPnlAllFailed =
                      !totalPnlLoading && accounts.length > 0 && totalPnlDerived.includedCount === 0;
                    const totalPnlFailedCount = accounts.length - totalPnlDerived.includedCount;
                    return (
                      <StatusCard
                        title="총손익"
                        value={
                          totalPnlLoading
                            ? "조회 중..."
                            : totalPnlAllFailed
                              ? "조회 실패"
                              : formatSignedKrw(totalPnlDerived.sum)
                        }
                        // RealizedPnlView.tsx/AccountsView.tsx의 pnlClass(양수 초록/음수
                        // 빨강)와 동일하게 healthy(초록)/error(빨강)를 맞춘다 —
                        // "조회 실패"와는 value 텍스트와 badgeLabel("오류" 없음 vs
                        // "손실")로 구분되므로 같은 빨강이어도 헷갈리지 않는다.
                        status={
                          totalPnlLoading
                            ? "neutral"
                            : totalPnlAllFailed
                              ? "error"
                              : totalPnlDerived.sum >= 0
                                ? "healthy"
                                : "error"
                        }
                        badgeLabel={
                          totalPnlLoading || totalPnlAllFailed
                            ? undefined
                            : totalPnlDerived.sum >= 0
                              ? "이익"
                              : "손실"
                        }
                        subtitle={
                          totalPnlLoading
                            ? "출처: realized-pnl summary"
                            : totalPnlAllFailed
                              ? "모든 계좌 조회 실패"
                              : totalPnlFailedCount > 0
                                ? `${REALIZED_PNL_CUMULATIVE_START_DATE}~오늘 누적(계좌 ${totalPnlFailedCount}개 조회 실패, 성공한 계좌만 반영) · 출처: realized-pnl summary`
                                : `${REALIZED_PNL_CUMULATIVE_START_DATE}~오늘 누적 · 출처: realized-pnl summary`
                        }
                      />
                    );
                  })()}
                </div>
              )}
            </>
          )}
        </Panel>
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
                { key: "quantity", header: "수량", width: "80px", align: "right" },
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
                { key: "mismatchCount", header: "불일치건수", width: "90px", align: "right" },
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

          {/* ── Section C: 최근 운영 경고 ──
              alertsReady가 false인 동안은 "운영 경고 없음"(빈 데이터)처럼
              보이지 않도록 별도 안내 문구를 보여준다. */}
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
            {alertsLoading ? (
              <p className="text-sm text-[#64748b]">운영 경고를 집계하는 중...</p>
            ) : (
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
                data={alertsDerived!.recentAlertItems}
                idKey="id"
                compact
                emptyMessage="운영 경고 없음"
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
