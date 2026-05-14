import { useState, useEffect, useMemo } from "react";
import type { PositionSnapshotView } from "../types/api";
import { DataTable, type Column } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { WarningBanner } from "./common/WarningBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { X, AlertCircle, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import {
  getHealth,
  getOrders,
  getReconciliationSummary,
  getReconciliationRuns,
  getAgentRuns,
  getClients,
  getAccounts,
  getPositions,
  getCashBalance,
  getSnapshotSyncRuns,
} from "../api/client";
import type {
  HealthResponse,
  OrderSummary,
  ReconciliationRunSummary,
  ClientDetail,
  SnapshotSyncRunSummary,
} from "../types/api";
import { deriveAlerts, LEVEL_PRIORITY, type AlertItem, type AlertRuleInput } from "../lib/alerts";

/* ── Types ── */
interface OperationNote {
  id: string;
  date: string;
  action: string;
  status: string;
}

/* ── Static data (backend API 없음, 예시) ── */
const operationNotes: OperationNote[] = [
  { id: "NOTE-001", date: "2026-05-13", action: "오전 장 개장 전 포지션 정리", status: "완료" },
  { id: "NOTE-002", date: "2026-05-13", action: "API 토큰 갱신", status: "완료" },
];

const preMarketChecklist = [
  { id: 1, item: "KIS 환경 상태 확인 (paper/live)" },
  { id: 2, item: "Token cache 유효성 확인" },
  { id: 3, item: "스냅샷 신선도 확인" },
  { id: 4, item: "브로커 용량 상태 확인" },
];

/* ── Filter mode ── */
type FilterMode = "action_needed" | "" | "긴급" | "주의" | "정보" | "정상";

/* ── Columns ── */
const alertColumns: Column<AlertItem>[] = [
  {
    key: "level",
    header: "수준",
    width: "80px",
    render: (row: AlertItem) => {
      const variants: Record<string, "error" | "warning" | "info" | "neutral"> = {
        긴급: "error",
        주의: "warning",
        경고: "info",
        정보: "info",
      };
      return <StatusBadge variant={variants[row.level] || "neutral"}>{row.level}</StatusBadge>;
    },
  },
  { key: "title", header: "제목" },
  { key: "time", header: "발생 시간", width: "150px" },
  {
    key: "status",
    header: "상태",
    width: "100px",
    render: (row: AlertItem) => (
      <StatusBadge variant={row.status === "OPEN" ? "warning" : "success"}>
        {row.status === "OPEN" ? "미해결" : "해결됨"}
      </StatusBadge>
    ),
  },
];

const noteColumns: Column<OperationNote>[] = [
  { key: "date", header: "날짜", width: "120px" },
  { key: "action", header: "조치 내용" },
  {
    key: "status",
    header: "상태",
    width: "80px",
    render: (row: OperationNote) => (
      <StatusBadge variant={row.status === "완료" ? "success" : "warning"}>{row.status}</StatusBadge>
    ),
  },
];

/* ── Component ── */
export default function OperationsAlertsView() {
  const [selectedAlert, setSelectedAlert] = useState<AlertItem | null>(null);
  const [levelFilter, setLevelFilter] = useState<FilterMode>("action_needed");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [snapshotSyncRun, setSnapshotSyncRun] = useState<SnapshotSyncRunSummary | null>(null);
  const [notesCollapsed, setNotesCollapsed] = useState(true);

  const fetchAlerts = async () => {
    setLoading(true);
    setError(null);

    // API 실패 기록용
    const apiErrors: { apiName: string; message: string }[] = [];

    try {
      // ── 시스템 상태 / 주문 / 정합성 요약 / 에이전트 (account_id 불필요) ──
      const [healthResult, ordersResult, reconSummaryResult, agentRunsResult] =
        await Promise.all([
          getHealth()
            .then((h) => ({ data: h, error: false }))
            .catch((e) => {
              apiErrors.push({ apiName: "GET /health", message: String(e) });
              return { data: null as HealthResponse | null, error: true };
            }),
          getOrders()
            .then((o) => ({ data: o, error: false }))
            .catch((e) => {
              apiErrors.push({ apiName: "GET /orders", message: String(e) });
              return { data: [] as OrderSummary[], error: true };
            }),
          getReconciliationSummary()
            .then((r) => ({ data: r, error: false }))
            .catch((e) => {
              apiErrors.push({ apiName: "GET /reconciliation/summary", message: String(e) });
              return { data: null, error: true };
            }),
          getAgentRuns()
            .then((a) => ({ data: a, error: false }))
            .catch((e) => {
              apiErrors.push({ apiName: "GET /agent-runs", message: String(e) });
              return { data: [] as { status?: string }[], error: true };
            }),
        ]);

      // ── 클라이언트 → 계좌 (Dashboard.tsx와 동일한 패턴) ──
      let accounts: { account_id: string }[] = [];
      let accountsError = false;
      try {
        const clients: ClientDetail[] = await getClients();
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
            accountsError = true;
          }
        }
      } catch (e) {
        accountsError = true;
      }

      // ── 정합성 실행 이력 (account_id 있을 때만 호출) ──
      let reconRunsResult: { data: ReconciliationRunSummary[]; error: boolean } = { data: [], error: false };
      const firstAccountId = accounts.length > 0 ? accounts[0].account_id : null;
      if (firstAccountId) {
        try {
          const runs = await getReconciliationRuns(firstAccountId);
          reconRunsResult = { data: runs, error: false };
        } catch {
          reconRunsResult = { data: [], error: true };
        }
      }

      // ── Positions count for lineage check (dedup + quantity>0) ──
      let positionsCount = 0;
      let positionsError = false;
      if (accounts.length > 0) {
        const posResults = await Promise.allSettled(
          accounts.map((a) => getPositions(a.account_id))
        );
        const dedupPositions = new Map<string, PositionSnapshotView>();
        posResults.forEach((r) => {
          if (r.status === "fulfilled") {
            for (const pos of r.value) {
              const existing = dedupPositions.get(pos.instrument_id);
              // instrument_id 기준 최신 snapshot_at 유지
              if (!existing || pos.snapshot_at > existing.snapshot_at) {
                dedupPositions.set(pos.instrument_id, pos);
              }
            }
          } else {
            positionsError = true;
          }
        });
        // quantity > 0인 포지션만 카운트
        positionsCount = Array.from(dedupPositions.values()).filter(
          (p) => (p.quantity ?? 0) > 0
        ).length;
      }

      // ── Snapshot sync run (최신 1건) ──
      let snapshotSyncRun: SnapshotSyncRunSummary | null = null;
      let snapshotSyncError = false;
      try {
        const runs = await getSnapshotSyncRuns(1);
        if (runs.length > 0) {
          snapshotSyncRun = runs[0];
        }
      } catch {
        snapshotSyncError = true;
      }

      // ── Position / Cash snapshot_at (최신 시각) ──
      let latestPositionSnapshotAt: string | null = null;
      let latestCashSnapshotAt: string | null = null;
      if (accounts.length > 0) {
        // Positions
        const posResults = await Promise.allSettled(
          accounts.map((a) => getPositions(a.account_id))
        );
        const dedupPositions = new Map<string, PositionSnapshotView>();
        posResults.forEach((r) => {
          if (r.status === "fulfilled") {
            for (const pos of r.value) {
              const existing = dedupPositions.get(pos.instrument_id);
              if (!existing || pos.snapshot_at > existing.snapshot_at) {
                dedupPositions.set(pos.instrument_id, pos);
              }
            }
          }
        });
        for (const pos of dedupPositions.values()) {
          if (!latestPositionSnapshotAt || pos.snapshot_at > latestPositionSnapshotAt) {
            latestPositionSnapshotAt = pos.snapshot_at;
          }
        }

        // Cash (각 계좌별 단일 CashBalanceSnapshotView 또는 null)
        const cashResults = await Promise.allSettled(
          accounts.map((a) => getCashBalance(a.account_id))
        );
        cashResults.forEach((r) => {
          if (r.status === "fulfilled" && r.value) {
            if (!latestCashSnapshotAt || r.value.snapshot_at > latestCashSnapshotAt) {
              latestCashSnapshotAt = r.value.snapshot_at;
            }
          }
        });
      }

      const newAlerts = deriveAlerts({
        health: healthResult.data,
        healthError: healthResult.error,
        orders: ordersResult.data,
        ordersError: ordersResult.error,
        reconSummary: reconSummaryResult.data as { active_locks_count: number; incomplete_recon_count: number } | null,
        reconSummaryError: reconSummaryResult.error,
        reconRuns: reconRunsResult.data,
        reconRunsError: reconRunsResult.error,
        agentRuns: agentRunsResult.data,
        agentRunsError: agentRunsResult.error,
        positionsCount,
        positionsError,
        snapshotSyncRun,
        snapshotSyncError,
        latestPositionSnapshotAt,
        latestCashSnapshotAt,
        apiErrors,
      });

      setAlerts(newAlerts);
      setSnapshotSyncRun(snapshotSyncRun);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "알림 데이터를 불러오지 못했습니다";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  const urgentCount = alerts.filter((a) => a.level === "긴급" && a.status === "OPEN").length;

  // Lineage warning: orders=0, positions>0
  const hasLineageWarning = useMemo(() => {
    return alerts.some((a) => a.id === "ALT-LINEAGE-001" && a.status === "OPEN");
  }, [alerts]);

  const filteredAlerts = useMemo(() => {
    return alerts
      .filter((alert) => {
        // Lineage 경고는 목록에서 제외 (상단 배너로 표시)
        if (hasLineageWarning && alert.id === "ALT-LINEAGE-001") return false;

        if (levelFilter === "action_needed") {
          return alert.level === "긴급" || alert.level === "주의";
        }
        if (levelFilter === "") return true; // 전체
        if (levelFilter === "정상") {
          return alert.level === "정보" && alert.status === "RESOLVED";
        }
        return alert.level === levelFilter;
      })
      .sort((a, b) => {
        const priorityDiff = (LEVEL_PRIORITY[a.level] ?? 99) - (LEVEL_PRIORITY[b.level] ?? 99);
        if (priorityDiff !== 0) return priorityDiff;
        // 동일 레벨: time 역순 (최신 먼저)
        return b.time.localeCompare(a.time);
      });
  }, [alerts, levelFilter, hasLineageWarning]);

  /* ── Loading / Error ── */
  if (loading) return <LoadingSpinner text="알림 데이터 분석 중..." />;

  if (error) {
    return (
      <div className="p-6 space-y-4">
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
        <button
          onClick={fetchAlerts}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-[#3b82f6] rounded-lg hover:bg-[#2563eb] transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          다시 시도
        </button>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">운영 경고</h1>
        <p className="text-sm text-[#64748b] mt-1">수동 개입 필요 신호 및 운영 메모</p>
      </div>

      {/* Urgent Warning Banner */}
      {urgentCount > 0 && (
        <WarningBanner
          variant="error"
          title={`즉시 확인 필요: ${urgentCount}건`}
          message="긴급 경고가 발생했습니다. 즉시 확인하고 조치하세요."
        />
      )}

      {/* Lineage Warning Banner (prominent at top) */}
      {hasLineageWarning && (
        <WarningBanner
          variant="warning"
          title="주문-포지션 불일치"
          message="주문 내역이 없으나 포지션이 존재합니다. 데이터 정합성을 확인하세요."
        />
      )}

      <div className="grid grid-cols-12 gap-6">
        {/* Alerts List */}
        <div className={selectedAlert ? "col-span-7" : "col-span-12"}>
          {/* Filter Buttons */}
          <div className="flex items-center gap-2 mb-4">
            {[
              { key: "action_needed" as FilterMode, label: "조치 필요" },
              { key: "" as FilterMode, label: "전체" },
              { key: "긴급" as FilterMode, label: "긴급" },
              { key: "주의" as FilterMode, label: "주의" },
              { key: "정보" as FilterMode, label: "정보" },
              { key: "정상" as FilterMode, label: "정상" },
            ].map((btn) => (
              <button
                key={btn.key}
                onClick={() => setLevelFilter(btn.key)}
                className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                  levelFilter === btn.key
                    ? btn.key === "action_needed"
                      ? "bg-[#3b82f6] text-white border-[#3b82f6]"
                      : btn.key === "긴급"
                        ? "bg-[#dc2626] text-white border-[#dc2626]"
                        : btn.key === "주의"
                          ? "bg-[#f59e0b] text-white border-[#f59e0b]"
                          : btn.key === "정보" || btn.key === "정상"
                            ? "bg-[#3b82f6] text-white border-[#3b82f6]"
                            : "bg-[#3b82f6] text-white border-[#3b82f6]"
                    : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#3b82f6]"
                }`}
              >
                {btn.label}
              </button>
            ))}
          </div>

          {filteredAlerts.length > 0 ? (
            <DataTable
              columns={alertColumns}
              data={filteredAlerts}
              onRowClick={setSelectedAlert}
              selectedId={selectedAlert?.id}
              idKey="id"
            />
          ) : (
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
              <p className="text-sm text-[#94a3b8]">
                {levelFilter === "action_needed"
                  ? "현재 조치가 필요한 운영 경고가 없습니다"
                  : "선택한 수준의 알림이 없습니다"}
              </p>
            </div>
          )}
        </div>

        {/* Alert Detail Panel */}
        {selectedAlert && (
          <div className="col-span-5 space-y-4">
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-[#0f172a]">경고 상세</h3>
                <button
                  onClick={() => setSelectedAlert(null)}
                  className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">ID</dt>
                  <dd className="text-sm font-mono text-[#0f172a]">{selectedAlert.id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">수준</dt>
                  <dd>
                    <StatusBadge
                      variant={
                        selectedAlert.level === "긴급"
                          ? "error"
                          : selectedAlert.level === "주의"
                            ? "warning"
                            : "info"
                      }
                    >
                      {selectedAlert.level}
                    </StatusBadge>
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">제목</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedAlert.title}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">상태</dt>
                  <dd>
                    <StatusBadge variant={selectedAlert.status === "OPEN" ? "warning" : "success"}>
                      {selectedAlert.status === "OPEN" ? "미해결" : "해결됨"}
                    </StatusBadge>
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">발생 시간</dt>
                  <dd className="text-sm text-[#0f172a]">{selectedAlert.time}</dd>
                </div>
                <div className="pt-2 border-t border-[#e2e8f0]">
                  <dt className="text-sm text-[#64748b] mb-1">설명</dt>
                  <dd className="text-sm text-[#0f172a]">{selectedAlert.description}</dd>
                </div>
              </dl>
            </div>
          </div>
        )}
      </div>

      {/* ── Pre-Market Snapshot Sync Status (동적, API 기반) ── */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertCircle className="h-5 w-5 text-[#3b82f6]" />
          <h3 className="text-lg font-semibold text-[#0f172a]">Pre-Market 스냅샷 동기화 실행</h3>
        </div>
        {(() => {
          if (!snapshotSyncRun) {
            return (
              <div className="text-sm text-[#64748b]">
                오늘 Pre-Market 실행 이력 없음
                <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-[#fef3c7] text-[#92400e]">
                  수동 확인 필요
                </span>
              </div>
            );
          }
          // KST 날짜 확인 (started_at은 ISO 8601 UTC)
          const runDateKST = (() => {
            const d = new Date(snapshotSyncRun.started_at);
            const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
            return kst.toISOString().slice(0, 10);
          })();
          const todayKST = (() => {
            const now = new Date();
            const kst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
            return kst.toISOString().slice(0, 10);
          })();
          if (runDateKST !== todayKST) {
            return (
              <div className="text-sm text-[#64748b]">
                오늘 Pre-Market 실행 이력 없음 (마지막 실행: {runDateKST})
                <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-[#fef3c7] text-[#92400e]">
                  수동 확인 필요
                </span>
              </div>
            );
          }
          const statusLabel =
            snapshotSyncRun.status === "completed"
              ? { text: "완료", variant: "success" as const }
              : snapshotSyncRun.status === "partial"
                ? { text: "주의", variant: "warning" as const }
                : snapshotSyncRun.status === "failed"
                  ? { text: "긴급", variant: "error" as const }
                  : { text: snapshotSyncRun.status, variant: "info" as const };
          return (
            <div className="flex items-center justify-between">
              <div className="text-sm text-[#0f172a]">
                <span className="font-medium">Pre-Market 스냅샷 동기화 실행</span>
                <span className="ml-2 text-[#64748b]">
                  ({new Date(snapshotSyncRun.started_at).toLocaleString("ko-KR")})
                </span>
              </div>
              <StatusBadge variant={statusLabel.variant}>{statusLabel.text}</StatusBadge>
            </div>
          );
        })()}
      </div>

      {/* ── Pre-Market Checklist (참고, 정적 예시) ── */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertCircle className="h-5 w-5 text-[#3b82f6]" />
          <h3 className="text-lg font-semibold text-[#0f172a]">Pre-Market 확인 리스트 (참고)</h3>
        </div>
        <ul className="space-y-2">
          {preMarketChecklist.map((item) => (
            <li key={item.id} className="flex items-center gap-2 text-sm text-[#475569]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#3b82f6]" />
              {item.item}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-[#94a3b8]">
          ※ 위 항목은 백엔드 API 미연동 상태의 참고 리스트입니다. 실제 확인 로직은 TODO/Backlog 항목입니다.
        </p>
      </div>

      {/* ── Operation Notes (정적 예시, 접힘 가능) ── */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <button
          onClick={() => setNotesCollapsed(!notesCollapsed)}
          className="flex items-center justify-between w-full text-left"
        >
          <h2 className="text-lg font-semibold text-[#0f172a]">운영 메모 (예시)</h2>
          {notesCollapsed ? (
            <ChevronDown className="h-5 w-5 text-[#64748b]" />
          ) : (
            <ChevronUp className="h-5 w-5 text-[#64748b]" />
          )}
        </button>
        {!notesCollapsed && (
          <div className="mt-4 space-y-3">
            <DataTable columns={noteColumns} data={operationNotes} idKey="id" />
            <p className="text-xs text-[#94a3b8]">
              ※ 위 항목은 정적 예시 데이터입니다. 백엔드 API 미연동 상태에서는 샘플 데이터가 표시됩니다.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
