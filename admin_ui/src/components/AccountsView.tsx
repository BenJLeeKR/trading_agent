import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  AccountSummary,
  ClientDetail,
  AlignmentStatus,
  AlignmentDetail,
  PositionSnapshotView,
  CashBalanceSnapshotView,
  SnapshotSyncRunSummary,
} from "../types/api";
import { getClients, getAccounts, getAccountSnapshots, getSnapshotSyncRuns } from "../api/client";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { FilterBar } from "./common/FilterBar";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import type { Column } from "./common/DataTable";
import { AlertCircle, Lock, Wallet, TrendingUp, TrendingDown, X, Users } from "lucide-react";
import { formatKrw, formatKstElapsed, formatKstDateTime } from "@/lib/utils";

/* ───────────────────────────────────────────
 * Helpers
 * ─────────────────────────────────────────── */

function formatQty(val: number | null | undefined): string {
  if (val == null) return "—";
  if (Number.isNaN(val)) return "—";
  return val.toLocaleString();
}

function truncateUuid(uuid: string): string {
  return uuid.length > 8 ? uuid.slice(0, 8) + "…" : uuid;
}


/* ───────────────────────────────────────────
 * AccountsView
 * ─────────────────────────────────────────── */
export default function AccountsView() {
  const [clients, setClients] = useState<ClientDetail[]>([]);
  const [selectedClient, setSelectedClient] = useState<ClientDetail | null>(null);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [positions, setPositions] = useState<PositionSnapshotView[]>([]);
  const [cashBalance, setCashBalance] = useState<CashBalanceSnapshotView | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [snapshotAlignment, setSnapshotAlignment] = useState<AlignmentStatus | null>(null);
  const [snapshotSyncRunId, setSnapshotSyncRunId] = useState<string | null>(null);
  const [alignmentDetail, setAlignmentDetail] = useState<AlignmentDetail>("unknown");
  const [alignmentDetailDescription, setAlignmentDetailDescription] = useState<string | null>(null);

  const [latestSyncRun, setLatestSyncRun] = useState<SnapshotSyncRunSummary | null>(null);
  const [syncRunError, setSyncRunError] = useState(false);
  const [showSnapshotHistory, setShowSnapshotHistory] = useState(false);
  const navigate = useNavigate();

  // Filter state
  const [searchText, setSearchText] = useState("");
  const [envFilter, setEnvFilter] = useState("");

  // ── Fetch latest snapshot sync run ──────────────────────────────
  useEffect(() => {
    getSnapshotSyncRuns(1)
      .then((runs) => {
        if (runs.length > 0) {
          setLatestSyncRun(runs[0]);
        }
      })
      .catch(() => {
        setSyncRunError(true);
      });
  }, []);

  // ── Fetch clients → accounts ───────────────────────────────────
  useEffect(() => {
    setLoading(true);
    setError(null);

    getClients()
      .then((allClients) => {
        setClients(allClients);
        if (allClients.length === 0) {
          setAccounts([]);
          setLoading(false);
          return;
        }
        // Auto-select first client
        const first = allClients[0];
        setSelectedClient(first);
        return getAccounts(first.client_id);
      })
      .then((accts) => {
        if (accts) setAccounts(accts);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "계좌를 불러오지 못했습니다";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, []);

  // ── Fetch positions / cash balance on account selection ─────────
  // 단일 /account-snapshots/latest 호출로 변경 → cash/position 시점 정합성 보장
  useEffect(() => {
    if (!selectedAccount) {
      setPositions([]);
      setCashBalance(null);
      setSnapshotAlignment(null);
      setSnapshotSyncRunId(null);
      setAlignmentDetail("unknown");
      setAlignmentDetailDescription(null);
      return;
    }
    setDetailLoading(true);
    getAccountSnapshots(selectedAccount)
      .then((data) => {
        setPositions(data.positions);
        setCashBalance(data.cash_balance);
        setSnapshotAlignment(data.alignment_status);
        setSnapshotSyncRunId(data.snapshot_sync_run_id ?? null);
        setAlignmentDetail(data.alignment_detail ?? "unknown");
        setAlignmentDetailDescription(data.alignment_detail_description ?? null);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "계좌 상세를 불러오지 못했습니다";
        setError(msg);
        setSnapshotAlignment(null);
        setSnapshotSyncRunId(null);
        setAlignmentDetail("unknown");
        setAlignmentDetailDescription(null);
      })
      .finally(() => setDetailLoading(false));
  }, [selectedAccount]);

  // ── Snapshot dedup: instrument별 최신 snapshot 1건 ──────────────
  // 수량 0인 종목(전량 매도 후 잔여 row)은 현재 포지션에서 제외
  const latestPositions = useMemo(() => {
    const map = new Map<string, PositionSnapshotView>();
    for (const pos of positions) {
      if (pos.quantity <= 0) continue; // 수량 0 스냅샷 제외
      const existing = map.get(pos.instrument_id);
      if (!existing || pos.snapshot_at > existing.snapshot_at) {
        map.set(pos.instrument_id, pos);
      }
    }
    return Array.from(map.values());
  }, [positions]);

  // ── Derived data ────────────────────────────────────────────────
  const filteredAccounts = useMemo(() => {
    return accounts.filter((a) => {
      const matchEnv = !envFilter || a.environment === envFilter;
      const matchSearch =
        !searchText ||
        (a.account_masked ?? "").toLowerCase().includes(searchText.toLowerCase()) ||
        (a.account_alias ?? "").toLowerCase().includes(searchText.toLowerCase());
      return matchEnv && matchSearch;
    });
  }, [accounts, searchText, envFilter]);

  const safeSelectedAccount = useMemo(() => {
    if (!selectedAccount) return null;
    return filteredAccounts.some((a) => a.account_id === selectedAccount)
      ? selectedAccount
      : null;
  }, [selectedAccount, filteredAccounts]);

  const selectedAccountDetail = safeSelectedAccount
    ? accounts.find((a) => a.account_id === safeSelectedAccount)
    : null;

  // Summary cards derived values (always based on latest snapshot per instrument)
  // ── KIS 우선: total_asset (tot_evlu_amt)이 있으면 KIS 총평가금액 사용, 없으면 fallback 계산 ──
  const totalValue = useMemo(() => {
    if (cashBalance?.total_asset != null) {
      return cashBalance.total_asset;
    }
    // Fallback: position market value + settled cash
    const posValue = latestPositions.reduce(
      (sum, p) => sum + p.quantity * p.market_price,
      0,
    );
    const cash = cashBalance?.settled_cash ?? 0;
    return posValue + cash;
  }, [latestPositions, cashBalance]);

  // ── KIS 우선: total_unrealized_pnl (evlu_pfls_smtl_amt)이 있으면 KIS 평가손익 사용, 없으면 fallback 계산 ──
  const totalPnl = useMemo(() => {
    if (cashBalance?.total_unrealized_pnl != null) {
      return cashBalance.total_unrealized_pnl;
    }
    return latestPositions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0);
  }, [latestPositions, cashBalance]);

  // ── Column definitions ──────────────────────────────────────────
  const accountColumns: Column<AccountSummary>[] = [
    {
      key: "account_code",
      header: "계좌",
      render: (r) => {
        const code = r.account_code;
        const alias = r.account_alias;
        const masked = r.account_masked;
        const label = code || alias || masked || "—";
        const title = [code, alias, masked].filter(Boolean).join(" · ") || undefined;
        return (
          <span title={title} className="text-sm font-medium text-[#0f172a]">
            {label}
          </span>
        );
      },
    },
    {
      key: "broker_account_code",
      header: "계좌번호",
      render: (r) => {
        const code = r.broker_account_code;
        const masked = r.account_masked;
        const label = code || masked || "—";
        const title = [code, masked].filter(Boolean).join(" · ") || undefined;
        return (
          <span title={title} className="text-xs font-mono text-[#64748b]">
            {label}
          </span>
        );
      },
    },
    {
      key: "environment",
      header: "환경",
      render: (r) => (
        <StatusBadge variant={r.environment === "live" ? "warning" : "info"}>
          {r.environment.toUpperCase()}
        </StatusBadge>
      ),
    },
    {
      key: "status",
      header: "상태",
      render: (r) => {
        const variant =
          r.status === "active"
            ? "success"
            : r.status === "locked"
              ? "error"
              : r.status === "pending"
                ? "warning"
                : "info";
        return <StatusBadge variant={variant}>{r.status.toUpperCase()}</StatusBadge>;
      },
    },
  ];

  const positionColumns: Column<PositionSnapshotView>[] = [
    {
      key: "symbol",
      header: "종목",
      render: (r) => (
        <span className="text-sm font-medium text-[#0f172a]">
          {r.symbol ?? truncateUuid(r.instrument_id)}
        </span>
      ),
    },
    {
      key: "instrument_name",
      header: "종목명",
      render: (r) => (
        <span className="text-sm text-[#334155]">
          {r.instrument_name || "—"}
        </span>
      ),
    },
    { key: "quantity", header: "수량", render: (r) => formatQty(r.quantity) },
    {
      key: "average_price",
      header: "평균단가",
      render: (r) => formatKrw(r.average_price),
    },
    {
      key: "purchase_amount",
      header: "매입금액",
      render: (r) => (r.purchase_amount != null ? formatKrw(r.purchase_amount) : "—"),
    },
    {
      key: "market_price",
      header: "현재가",
      render: (r) => formatKrw(r.market_price),
    },
    {
      key: "evaluation_amount",
      header: "평가금액",
      render: (r) => (r.evaluation_amount != null ? formatKrw(r.evaluation_amount) : "—"),
    },
    {
      key: "unrealized_pnl",
      header: "미실현 손익",
      render: (r) => {
        const pnl = r.unrealized_pnl ?? 0;
        return (
          <span
            className={`text-xs font-semibold ${pnl >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"}`}
          >
            {pnl >= 0 ? "+" : ""}
            {formatKrw(pnl)}
          </span>
        );
      },
    },
    { key: "snapshot_at", header: "스냅샷 시각", render: (r) => formatKstDateTime(r.snapshot_at) },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <button
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/orders?symbol=${encodeURIComponent(r.symbol ?? "")}`);
          }}
          className="text-xs text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors whitespace-nowrap"
        >
          관련 주문 보기 →
        </button>
      ),
    },
  ];

  // ── Render ──────────────────────────────────────────────────────
  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0f172a]">계좌</h1>
          <p className="text-sm text-[#64748b] mt-1">
            계좌 상태, 포지션, 현금 잔고 조회
          </p>
          <p className="text-xs text-[#94a3b8] mt-0.5">
            내부 데이터베이스 계좌 메타데이터
          </p>
        </div>
        {/* Selected client indicator */}
        {selectedClient && (
          <div className="flex items-center gap-2 bg-white rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm">
            <Users className="h-4 w-4 text-[#64748b]" />
            <span className="text-[#64748b]">클라이언트:</span>
            <span className="font-medium text-[#0f172a]">
              {selectedClient.name}
            </span>
            <span className="text-[#94a3b8]">({selectedClient.client_code})</span>
          </div>
        )}
      </div>

      {/* Snapshot Sync Run Summary Bar */}
      {!syncRunError && latestSyncRun && (
        <div className="bg-white rounded-xl border border-[#e2e8f0] px-4 py-3 flex items-center gap-3 text-sm">
          <AlertCircle className="h-4 w-4 text-[#64748b]" />
          <span className="text-[#64748b]">스냅샷 동기화:</span>
          <StatusBadge
            variant={
              latestSyncRun.status === "completed"
                ? "success"
                : latestSyncRun.status === "partial"
                  ? "warning"
                  : latestSyncRun.status === "failed"
                    ? "error"
                    : "info"
            }
          >
            {latestSyncRun.status === "completed"
              ? "정상"
              : latestSyncRun.status === "partial"
                ? "부분 성공"
                : latestSyncRun.status === "failed"
                  ? "실패"
                  : latestSyncRun.status}
          </StatusBadge>
          <span className="text-[#94a3b8]">
            {latestSyncRun.succeeded_accounts}/{latestSyncRun.total_accounts} 계좌
          </span>
          {(() => {
            const sj = latestSyncRun.summary_json as Record<string, number> | null;
            if (!sj) return null;
            const parts: string[] = [];
            const preCheck = sj["VTTC8908R_pre_check"] ?? 0;
            const budgetExhausted = sj["VTTC8908R_budget_exhausted"] ?? 0;
            const apiFailure = sj["VTTC8908R_api_failure"] ?? 0;
            const afterHoursSkip = sj["after_hours_skip"] ?? 0;
            if (preCheck > 0) parts.push(`pre-check fallback ${preCheck}회`);
            if (budgetExhausted > 0) parts.push(`budget exhausted ${budgetExhausted}회`);
            if (apiFailure > 0) parts.push(`API 실패 fallback ${apiFailure}회`);
            if (afterHoursSkip > 0) parts.push(`장후 skip ${afterHoursSkip}회`);
            if (parts.length === 0) return null;
            return (
              <span className="text-[#f59e0b] text-xs ml-1">
                {parts.join(" | ")}
              </span>
            );
          })()}
          {latestSyncRun.started_at && (
            <span className="text-[#94a3b8] text-xs ml-auto">
              {formatKstElapsed(latestSyncRun.started_at)}
            </span>
          )}
        </div>
      )}

      {/* Empty state when no clients exist */}
      {clients.length === 0 ? (
        <div className="flex items-center justify-center bg-white rounded-xl border border-[#e2e8f0] p-12">
          <div className="text-center">
            <Users className="h-8 w-8 text-[#94a3b8] mx-auto mb-2" />
            <p className="text-sm text-[#64748b]">클라이언트가 없습니다. 표시할 계좌가 없습니다.</p>
          </div>
        </div>
      ) : (
        <div>
          {/* Accounts List */}
          <div className="mb-4">
            <FilterBar
              searchPlaceholder="계좌 별칭 또는 번호 검색..."
              searchValue={searchText}
              onSearchChange={setSearchText}
              filters={[
                {
                  key: "env",
                  label: "환경",
                  options: [
                    { label: "모의", value: "paper" },
                    { label: "실전", value: "live" },
                  ],
                  value: envFilter,
                  onChange: setEnvFilter,
                },
              ]}
              onClearAll={() => {
                setSearchText("");
                setEnvFilter("");
              }}
            />
            <DataTable
              columns={accountColumns}
              data={filteredAccounts}
              onRowClick={(row) => setSelectedAccount(row.account_id)}
              selectedId={safeSelectedAccount}
              idKey="account_id"
              emptyMessage="이 클라이언트의 계좌가 없습니다."
            />
          </div>

          {/* Account Detail Panel */}
          {safeSelectedAccount && selectedAccountDetail && (
            <div className="space-y-4 mt-6">
              {/* Locked warning */}
              {selectedAccountDetail.status === "locked" && (
                <div className="flex items-center gap-2 bg-[#fef2f2] border border-[#f87171] rounded-lg px-4 py-3">
                  <Lock className="h-4 w-4 text-[#dc2626]" />
                  <strong className="text-sm text-[#dc2626]">계좌 잠금</strong>
                  <span className="text-sm text-[#dc2626]">
                    거래 및 수정이 제한됩니다.
                  </span>
                </div>
              )}

              {/* Account Detail card */}
              <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-[#0f172a]">계좌 메타데이터</h3>
                  <button
                    onClick={() => setSelectedAccount(null)}
                    className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <dl className="grid grid-cols-2 gap-4">
                  <div>
                    <dt className="text-sm text-[#64748b]">계좌 코드</dt>
                    <dd className="text-sm font-mono text-[#0f172a] mt-0.5">
                      {selectedAccountDetail.account_code ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">별칭</dt>
                    <dd className="text-sm font-medium text-[#0f172a] mt-0.5">
                      {selectedAccountDetail.account_alias ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">계좌번호</dt>
                    <dd className="text-sm font-mono text-[#0f172a] mt-0.5">
                      {selectedAccountDetail.account_masked ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">브로커 코드</dt>
                    <dd className="text-sm font-mono text-[#0f172a] mt-0.5">
                      {selectedAccountDetail.broker_account_code ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">환경</dt>
                    <dd className="mt-0.5">
                      <StatusBadge
                        variant={
                          selectedAccountDetail.environment === "live"
                            ? "warning"
                            : "info"
                        }
                      >
                        {selectedAccountDetail.environment.toUpperCase()}
                      </StatusBadge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-[#64748b]">상태</dt>
                    <dd className="mt-0.5">
                      <StatusBadge
                        variant={
                          selectedAccountDetail.status === "active"
                            ? "success"
                            : "warning"
                        }
                      >
                        {selectedAccountDetail.status.toUpperCase()}
                      </StatusBadge>
                    </dd>
                  </div>
                </dl>

                {/* Technical IDs — muted section for UUIDs and raw refs */}
                <div className="mt-6 pt-4 border-t border-[#e2e8f0]">
                  <h4 className="text-xs font-medium text-[#94a3b8] uppercase tracking-wider mb-2">
                    기술 ID
                  </h4>
                  <dl className="grid grid-cols-3 gap-3">
                    <div>
                      <dt className="text-xs text-[#94a3b8]">계좌 ID</dt>
                      <dd className="text-xs font-mono text-[#94a3b8] mt-0.5" title={selectedAccountDetail.account_id}>
                        {truncateUuid(selectedAccountDetail.account_id)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-[#94a3b8]">브로커 계좌 ID</dt>
                      <dd className="text-xs font-mono text-[#94a3b8] mt-0.5" title={selectedAccountDetail.broker_account_id}>
                        {truncateUuid(selectedAccountDetail.broker_account_id)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-[#94a3b8]">클라이언트 ID</dt>
                      <dd className="text-xs font-mono text-[#94a3b8] mt-0.5" title={selectedAccountDetail.client_id}>
                        {truncateUuid(selectedAccountDetail.client_id)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-[#94a3b8]">브로커 참조</dt>
                      <dd className="text-xs font-mono text-[#94a3b8] mt-0.5" title={selectedAccountDetail.broker_account_ref ?? undefined}>
                        {selectedAccountDetail.broker_account_ref ?? "—"}
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>

              {/* Broker Snapshot section label */}
              <div className="flex items-center gap-2">
                <div className="h-px flex-1 bg-[#e2e8f0]" />
                <span className="text-xs font-medium text-[#94a3b8] uppercase tracking-wider">
                  브로커 스냅샷
                </span>
                <div className="h-px flex-1 bg-[#e2e8f0]" />
              </div>

              {/* ── Snapshot alignment status badge (alignment_detail 기반) ── */}
              {snapshotAlignment && alignmentDetail ? (
                <div className="flex items-center gap-3 text-xs">
                  {alignmentDetail === "same_run" ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-[#ecfdf5] text-[#16a34a] px-2.5 py-1 font-medium"
                      title="포지션과 현금 잔고가 동일 sync-run에서 캡처되어 완전히 정합된 상태입니다"
                    >
                      ✓ 동기화 완료
                    </span>
                  ) : alignmentDetail === "after_hours_cash_updated" ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-[#eff6ff] text-[#2563eb] px-2.5 py-1 font-medium"
                      title="포지션은 정규장 기준, 현금은 after-hours 업데이트 기준입니다. after-hours에는 정상"
                    >
                      ↻ 장후 현금 업데이트
                    </span>
                  ) : alignmentDetail === "cash_only" ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-[#fef9c3] text-[#b45309] px-2.5 py-1 font-medium"
                      title="현금 잔고 데이터만 조회되었습니다. 포지션 데이터가 없어 트레이딩 불가"
                    >
                      ₩ 현금만 조회
                    </span>
                  ) : alignmentDetail === "partial_position_only" ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-[#fff7ed] text-[#c2410c] px-2.5 py-1 font-medium"
                      title="포지션 데이터만 조회되었습니다. 현금 잔고 데이터가 없습니다"
                    >
                      ⊞ 포지션만 조회
                    </span>
                  ) : alignmentDetail === "timestamp_proximity" ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-[#fef2f2] text-[#dc2626] px-2.5 py-1 font-medium"
                      title="FK 연결 없이 timestamp 근사치로 정합된 legacy 데이터입니다. 정확도 낮음"
                    >
                      ⚠ 시간 근사 정합
                    </span>
                  ) : snapshotAlignment === "aligned" ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-[#ecfdf5] text-[#16a34a] px-2.5 py-1 font-medium"
                      title="포지션과 현금 잔고가 동일 sync-run에서 캡처되어 완전히 정합된 상태입니다"
                    >
                      ✓ 동기화 완료
                    </span>
                  ) : snapshotAlignment === "partial" ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-[#fef9c3] text-[#b45309] px-2.5 py-1 font-medium"
                      title="포지션 또는 현금 잔고 중 일부만 조회되었습니다"
                    >
                      ? 부분 조회
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-[#f1f5f9] text-[#64748b] px-2.5 py-1 font-medium">
                      ? 정보 없음
                    </span>
                  )}
                  {/* 보조 설명 문구 */}
                  {alignmentDetailDescription && (
                    <span className="ml-2 text-xs text-gray-500">
                      {alignmentDetailDescription}
                    </span>
                  )}
                  {/* snapshot_sync_run_id 표시 */}
                  {snapshotSyncRunId && (
                    <span
                      className="text-[#94a3b8] font-mono"
                      title={`Sync Run ID: ${snapshotSyncRunId}`}
                    >
                      run: {truncateUuid(snapshotSyncRunId)}
                    </span>
                  )}
                </div>
              ) : null}

              {detailLoading ? (
                <LoadingSpinner text="계좌 상세 로딩 중..." />
              ) : (
                <>
                  {/* Summary cards */}
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="p-1.5 rounded-lg bg-[#eef2ff] text-[#6366f1]">
                          <Wallet className="h-4 w-4" />
                        </div>
                      </div>
                      <p className="text-2xl font-semibold text-[#0f172a]">
                        {formatKrw(totalValue)}
                      </p>
                      <p className="text-xs text-[#64748b] mt-1">총 자산</p>
                    </div>
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="p-1.5 rounded-lg bg-[#ecfdf5] text-[#10b981]">
                          <Wallet className="h-4 w-4" />
                        </div>
                      </div>
                      <p className="text-2xl font-semibold text-[#0f172a]">
                        {cashBalance
                          ? formatKrw(cashBalance.settlement_amount ?? cashBalance.settled_cash)
                          : "—"}
                      </p>
                      <p className="text-xs text-[#64748b] mt-1">현금 잔고</p>
                    </div>
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div
                          className={`p-1.5 rounded-lg ${
                            totalPnl >= 0
                              ? "bg-[#ecfdf5] text-[#10b981]"
                              : "bg-[#fef2f2] text-[#ef4444]"
                          }`}
                        >
                          {totalPnl >= 0 ? (
                            <TrendingUp className="h-4 w-4" />
                          ) : (
                            <TrendingDown className="h-4 w-4" />
                          )}
                        </div>
                      </div>
                      <p
                        className={`text-2xl font-semibold ${
                          totalPnl >= 0 ? "text-[#16a34a]" : "text-[#dc2626]"
                        }`}
                      >
                        {totalPnl >= 0 ? "+" : ""}
                        {formatKrw(totalPnl)}
                      </p>
                      <p className="text-xs text-[#64748b] mt-1">미실현 손익</p>
                    </div>
                  </div>

                  {/* Cash balance detail */}
                  {cashBalance && (
                    <div className="bg-white rounded-xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="text-sm font-medium text-[#0f172a]">
                          브로커 스냅샷 — 현금 잔고
                        </h4>
                        <span className="text-xs text-[#94a3b8]">
                          스냅샷: {formatKstElapsed(cashBalance.snapshot_at)}
                        </span>
                      </div>
                      <div className="flex gap-6 text-sm flex-wrap">
                        <div>
                          <span className="text-[#64748b]">예수금: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {formatKrw(cashBalance.available_cash)}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">결제완료: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {formatKrw(cashBalance.settled_cash)}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">미결제: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {formatKrw(cashBalance.unsettled_cash)}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">통화: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {cashBalance.currency}
                          </span>
                        </div>
                        <div>
                          <span className="text-[#64748b]">출처: </span>
                          <span className="font-semibold text-[#0f172a]">
                            {cashBalance.source_of_truth}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Positions table */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <h4 className="text-sm font-medium text-[#0f172a]">
                        브로커 스냅샷 — 포지션
                      </h4>
                      <div className="flex items-center gap-3">
                        {positions.length > latestPositions.length && (
                          <button
                            onClick={() => setShowSnapshotHistory((v) => !v)}
                            className="text-xs text-[#3b82f6] hover:text-[#2563eb] font-medium transition-colors"
                          >
                            {showSnapshotHistory
                              ? "최신 포지션만 보기"
                              : `스냅샷 이력 보기 (${positions.length}건)`}
                          </button>
                        )}
                        {positions.length > 0 && (
                          <span className="text-xs text-[#94a3b8]">
                            스냅샷: {formatKstElapsed(positions[0].snapshot_at)}
                          </span>
                        )}
                      </div>
                    </div>
                    <DataTable
                      columns={positionColumns}
                      data={showSnapshotHistory ? positions : latestPositions}
                      idKey="position_snapshot_id"
                      emptyMessage="이 계좌의 포지션이 없습니다."
                      compact
                    />
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
