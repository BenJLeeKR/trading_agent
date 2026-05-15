import { useCallback, useEffect, useMemo, useState } from "react";
import { formatKrw, formatKstDateTime, formatKstTime } from "@/lib/utils";
import BrokerCapacityPanel from "./BrokerCapacityPanel";
import { useNavigate } from "react-router-dom";
import type {
  AccountSummary,
  PositionSnapshotView,
  CashBalanceSnapshotView,
  OrderSummary,
  BlockingLockStatus,
  ReconciliationRunSummary,
  ReconciliationSummary,
} from "../types/api";
import {
  getClients,
  getAccounts,
  getPositions,
  getCashBalance,
  getOrders,
  getReconciliationSummary,
} from "../api/client";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ArrowRight, Users, Wallet, BarChart3, ShoppingCart, Lock, RefreshCw } from "lucide-react";


/* ── MetricCard ── */
function MetricCard({
  icon,
  title,
  value,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  value: string | number;
  subtitle?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
      <div className="flex items-center gap-3 mb-2">
        <div className="text-[#64748b]">{icon}</div>
        <span className="text-sm font-medium text-[#64748b]">{title}</span>
      </div>
      <p className="text-2xl font-semibold text-[#0f172a]">{value}</p>
      {subtitle && (
        <p className="text-xs text-[#94a3b8] mt-1">{subtitle}</p>
      )}
    </div>
  );
}

/* ── DashboardSummary ── */
interface DashboardSummary {
  totalAccounts: number;
  activeAccounts: number;
  lockedAccounts: number;
  totalAvailableCash: number;
  totalSettledCash: number;
  accountsWithPositions: number;
  totalPositionCount: number;
}

function computeSummary(
  accounts: AccountSummary[],
  positionsMap: Map<string, PositionSnapshotView[]>,
  cashMap: Map<string, CashBalanceSnapshotView | null>,
): DashboardSummary {
  let totalAvailableCash = 0;
  let totalSettledCash = 0;
  let accountsWithPositions = 0;
  let totalPositionCount = 0;
  let activeAccounts = 0;
  let lockedAccounts = 0;

  for (const acct of accounts) {
    if (acct.status === "active") activeAccounts++;
    else if (acct.status === "locked") lockedAccounts++;

    const cash = cashMap.get(acct.account_id);
    if (cash) {
      totalAvailableCash += cash.available_cash ?? 0;
      totalSettledCash += cash.settled_cash ?? 0;
    }

    const positions = positionsMap.get(acct.account_id);
    if (positions && positions.length > 0) {
      accountsWithPositions++;
      totalPositionCount += positions.length;
    }
  }

  return {
    totalAccounts: accounts.length,
    activeAccounts,
    lockedAccounts,
    totalAvailableCash,
    totalSettledCash,
    accountsWithPositions,
    totalPositionCount,
  };
}

/* ── Dashboard component ── */
export default function Dashboard() {
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [positionsMap, setPositionsMap] = useState<Map<string, PositionSnapshotView[]>>(new Map());
  const [cashMap, setCashMap] = useState<Map<string, CashBalanceSnapshotView | null>>(new Map());
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [locks, setLocks] = useState<BlockingLockStatus[]>([]);
  const [reconRuns, setReconRuns] = useState<ReconciliationRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const navigate = useNavigate();

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Step 1: fetch all clients
      const clients = await getClients();
      if (clients.length === 0) {
        setAccounts([]);
        setPositionsMap(new Map());
        setCashMap(new Map());
        setOrders([]);
        setLocks([]);
        setReconRuns([]);
        setLoadedAt(new Date());
        setLoading(false);
        return;
      }

      // Step 2: fetch accounts for each client
      const allAccounts: AccountSummary[] = [];
      for (const client of clients) {
        const clientAccounts = await getAccounts(client.client_id);
        allAccounts.push(...clientAccounts);
      }
      setAccounts(allAccounts);

      // Step 3: fetch positions + cash for each account (parallel)
      const posPromises = allAccounts.map((a) =>
        getPositions(a.account_id).then(
          (p) => [a.account_id, p] as [string, PositionSnapshotView[]],
        ),
      );
      const cashPromises = allAccounts.map((a) =>
        getCashBalance(a.account_id).then(
          (c) => [a.account_id, c] as [string, CashBalanceSnapshotView | null],
        ),
      );

      const [posResults, cashResults] = await Promise.all([
        Promise.all(posPromises),
        Promise.all(cashPromises),
      ]);

      setPositionsMap(new Map(posResults));
      setCashMap(new Map(cashResults));

      // Step 4: fetch orders + reconciliation summary (aggregate, no account_id needed)
      const [ordersData, reconSummary] = await Promise.all([
        getOrders(),
        getReconciliationSummary(),
      ]);
      setOrders(ordersData);
      setLocks(reconSummary.recent_active_locks);
      setReconRuns(reconSummary.recent_incomplete_runs);
      setLoadedAt(new Date());
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "대시보드 데이터를 불러오지 못했습니다";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const summary = useMemo(
    () => computeSummary(accounts, positionsMap, cashMap),
    [accounts, positionsMap, cashMap],
  );

  // Compute derived metrics for top cards
  const recentOrdersCount = orders.length;
  const activeLocksCount = locks.filter((l) => !l.is_expired).length;
  const incompleteReconCount = reconRuns.filter(
    (r) => r.status !== "completed",
  ).length;

  /* ── loading / error ── */
  if (loading) return <LoadingSpinner />;
  if (error)
    return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  /* ── empty state ── */
  if (accounts.length === 0) {
    return (
      <div className="p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-[#0f172a]">개요</h1>
          <p className="text-sm text-[#64748b] mt-1">
            계좌 및 포지션 요약
          </p>
          {loadedAt && (
            <p className="text-xs text-[#94a3b8] mt-0.5">
              {formatKstTime(loadedAt.toISOString())}에 업데이트됨
            </p>
          )}
        </div>
        <div className="bg-white rounded-xl border border-[#e2e8f0] p-12 text-center">
          <Users className="h-12 w-12 text-[#94a3b8] mx-auto mb-4" />
          <h2 className="text-lg font-semibold text-[#0f172a] mb-2">
            계좌가 없습니다
          </h2>
          <p className="text-sm text-[#64748b] mb-6">
            시스템에 등록된 계좌가 아직 없습니다.
          </p>
          <button
            onClick={() => navigate("/accounts")}
            className="inline-flex items-center gap-2 px-4 py-2 bg-[#3b82f6] text-white rounded-lg text-sm font-medium hover:bg-[#2563eb] transition-colors"
          >
            계좌로 이동
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  /* ── main render ── */
  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">개요</h1>
        <p className="text-sm text-[#64748b] mt-1">
          계좌 및 포지션 요약
        </p>
        {loadedAt && (
          <p className="text-xs text-[#94a3b8] mt-0.5">
            {formatKstTime(loadedAt.toISOString())}에 업데이트됨
          </p>
        )}
      </div>

      {/* Summary Metric Cards — 6 columns */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <MetricCard
          icon={<Users className="h-5 w-5" />}
          title="전체 계좌"
          value={summary.totalAccounts}
          subtitle={`활성 ${summary.activeAccounts} · 잠금 ${summary.lockedAccounts}`}
        />
        <MetricCard
          icon={<Wallet className="h-5 w-5" />}
          title="가용 현금"
          value={formatKrw(summary.totalAvailableCash)}
          subtitle={`결제완료: ${formatKrw(summary.totalSettledCash)}`}
        />
        <MetricCard
          icon={<BarChart3 className="h-5 w-5" />}
          title="포지션"
          value={summary.totalPositionCount}
          subtitle={`${summary.accountsWithPositions}개 계좌 보유 중`}
        />
        <MetricCard
          icon={<ShoppingCart className="h-5 w-5" />}
          title="최근 주문"
          value={recentOrdersCount}
          subtitle={recentOrdersCount > 0 ? "시스템 전체 주문 수" : "주문 없음"}
        />
        <MetricCard
          icon={<Lock className="h-5 w-5" />}
          title="활성 잠금"
          value={activeLocksCount}
          subtitle="전체 계좌 기준"
        />
        <MetricCard
          icon={<RefreshCw className="h-5 w-5" />}
          title="미완료 정합성"
          value={incompleteReconCount}
          subtitle="전체 계좌 기준"
        />
      </div>

      {/* Account Quick List */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">계좌</h2>
          <button
            onClick={() => navigate("/accounts")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            전체 계좌 보기
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                <th className="text-left px-4 py-3 font-medium text-[#64748b]">
                  계좌
                </th>
                <th className="text-left px-4 py-3 font-medium text-[#64748b]">
                  상태
                </th>
                <th className="text-left px-4 py-3 font-medium text-[#64748b]">
                  환경
                </th>
                <th className="text-right px-4 py-3 font-medium text-[#64748b]">
                  포지션
                </th>
                <th className="text-right px-4 py-3 font-medium text-[#64748b]">
                  가용 현금
                </th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((acct) => {
                const positions = positionsMap.get(acct.account_id) ?? [];
                const cash = cashMap.get(acct.account_id);
                return (
                  <tr
                    key={acct.account_id}
                    className="border-b border-[#e2e8f0] last:border-b-0 hover:bg-[#f8fafc] cursor-pointer transition-colors"
                    onClick={() => navigate(`/accounts`)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex flex-col">
                        <span className="font-medium text-[#0f172a]">
                          {acct.account_alias ?? acct.account_code ?? "—"}
                        </span>
                        <span className="text-xs text-[#94a3b8] font-mono">
                          {acct.broker_account_code ?? acct.account_masked ?? "—"}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        variant={
                          acct.status === "active"
                            ? "success"
                            : acct.status === "locked"
                              ? "warning"
                              : "error"
                        }
                      >
                        {acct.status.toUpperCase()}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs font-mono text-[#64748b] uppercase">
                        {acct.environment}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[#0f172a]">
                      {positions.length}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[#0f172a]">
                      {cash ? formatKrw(cash.available_cash) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent Orders Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">최근 주문</h2>
          <button
            onClick={() => navigate("/orders")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            전체 주문 보기
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {orders.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <ShoppingCart className="h-8 w-8 text-[#94a3b8] mx-auto mb-2" />
            <p className="text-sm text-[#64748b]">주문이 없습니다.</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">주문</th>
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">심볼</th>
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">매매</th>
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">상태</th>
                  <th className="text-right px-4 py-3 font-medium text-[#64748b]">수량</th>
                  <th className="text-right px-4 py-3 font-medium text-[#64748b]">생성일</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr
                    key={order.order_request_id}
                    className="border-b border-[#e2e8f0] last:border-b-0 hover:bg-[#f8fafc] cursor-pointer transition-colors"
                    onClick={() => navigate(`/orders`)}
                  >
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-[#64748b]">
                        {order.order_request_id.slice(0, 8)}…
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-[#0f172a]">
                      {order.symbol ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        variant={
                          order.side === "buy"
                            ? "success"
                            : order.side === "sell"
                              ? "error"
                              : "info"
                        }
                      >
                        {order.side.toUpperCase()}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        variant={
                          order.status === "filled"
                            ? "success"
                            : order.status === "pending" || order.status === "submitted"
                              ? "warning"
                              : "error"
                        }
                      >
                        {order.status.toUpperCase()}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[#0f172a]">
                      {order.requested_quantity}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-[#64748b]">
                      {order.created_at
                        ? formatKstDateTime(order.created_at)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Active Locks Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">활성 잠금</h2>
          <button
            onClick={() => navigate("/reconciliation")}
            className="flex items-center gap-1 text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
          >
            전체 잠금 보기
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
        {locks.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <Lock className="h-8 w-8 text-[#94a3b8] mx-auto mb-2" />
            <p className="text-sm text-[#64748b]">활성 잠금이 없습니다.</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">잠금 키</th>
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">유형</th>
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">심볼</th>
                  <th className="text-left px-4 py-3 font-medium text-[#64748b]">전략</th>
                  <th className="text-right px-4 py-3 font-medium text-[#64748b]">만료</th>
                </tr>
              </thead>
              <tbody>
                {locks.map((lock) => (
                  <tr
                    key={lock.lock_id}
                    className="border-b border-[#e2e8f0] last:border-b-0 hover:bg-[#f8fafc] transition-colors"
                  >
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-[#64748b]">
                        {lock.lock_key}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        variant={
                          lock.lock_type === "manual"
                            ? "warning"
                            : lock.lock_type === "reconciliation"
                              ? "error"
                              : "info"
                        }
                      >
                        {lock.lock_type.toUpperCase()}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3 font-medium text-[#0f172a]">
                      {lock.symbol}
                    </td>
                    <td className="px-4 py-3 text-xs text-[#64748b]">
                      {lock.strategy_code}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-[#64748b]">
                      {formatKstDateTime(lock.expires_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Broker Capacity Panel — independent fetch, read-only */}
      <BrokerCapacityPanel />
    </div>
  );
}
