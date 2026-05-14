import { useState, useEffect, useMemo } from "react";
import type { PositionSnapshotView } from "../types/api";
import { DataTable, type Column } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { WarningBanner } from "./common/WarningBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { X, AlertCircle, RefreshCw } from "lucide-react";
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

/* ── Types ── */
interface AlertItem {
  id: string;
  level: "긴급" | "주의" | "경고" | "정보";
  title: string;
  description: string;
  time: string;
  status: "OPEN" | "RESOLVED";
}

interface OperationNote {
  id: string;
  date: string;
  action: string;
  status: string;
}

/* ── Static data (backend API 없음) ── */
const operationNotes: OperationNote[] = [
  { id: "NOTE-001", date: "2026-05-13", action: "오전 장 개장 전 포지션 정리", status: "완료" },
  { id: "NOTE-002", date: "2026-05-13", action: "API 토큰 갱신", status: "완료" },
  { id: "NOTE-003", date: "2026-05-14", action: "Pre-Market 점검 필요", status: "대기" },
];

const preMarketChecklist = [
  { id: 1, item: "KIS 환경 상태 확인 (paper/live)" },
  { id: 2, item: "Token cache 유효성 확인" },
  { id: 3, item: "스냅샷 신선도 확인" },
  { id: 4, item: "브로커 용량 상태 확인" },
];

/* ── Alert derivation rules ── */
interface AlertRuleInput {
  health: HealthResponse | null;
  healthError: boolean;
  orders: OrderSummary[];
  ordersError: boolean;
  reconSummary: { active_locks_count: number; incomplete_recon_count: number } | null;
  reconSummaryError: boolean;
  reconRuns: ReconciliationRunSummary[];
  reconRunsError: boolean;
  agentRuns: { status?: string }[];
  agentRunsError: boolean;
  positionsCount: number;
  positionsError: boolean;
  // ── Snapshot sync run ──
  snapshotSyncRun: SnapshotSyncRunSummary | null;
  snapshotSyncError: boolean;
  // ── Position / Cash snapshot_at for time discrepancy check ──
  latestPositionSnapshotAt: string | null;
  latestCashSnapshotAt: string | null;
}

function deriveAlerts(input: AlertRuleInput): AlertItem[] {
  const alerts: AlertItem[] = [];
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);

  // Rule 1: API 상태 이상 (긴급)
  if (input.healthError || !input.health || input.health.status !== "ok") {
    alerts.push({
      id: "ALT-SYS-001",
      level: "긴급",
      title: "API 상태 이상",
      description: input.healthError
        ? "API 서버 응답 없음 (Health endpoint 연결 실패)"
        : `API 상태: ${input.health?.status ?? "unknown"}`,
      time: now,
      status: "OPEN",
    });
  }

  // Rule 2: 스냅샷 동기화 지연 (긴급)
  if (!input.reconRunsError && input.reconRuns.length > 0) {
    const sorted = [...input.reconRuns].sort(
      (a, b) => new Date(b.started_at ?? 0).getTime() - new Date(a.started_at ?? 0).getTime()
    );
    const latest = sorted[0];
    if (latest?.started_at) {
      const elapsed = Date.now() - new Date(latest.started_at).getTime();
      if (elapsed > 5 * 60 * 1000) {
        alerts.push({
          id: "ALT-SNAP-001",
          level: "긴급",
          title: "스냅샷 동기화 지연",
          description: `마지막 스냅샷 동기화가 5분 이상 갱신되지 않았습니다. (마지막: ${latest.started_at})`,
          time: now,
          status: "OPEN",
        });
      }
    }
  } else if (input.reconRunsError || input.reconRuns.length === 0) {
    alerts.push({
      id: "ALT-SNAP-002",
      level: "긴급",
      title: "스냅샷 없음",
      description: input.reconRunsError
        ? "스냅샷 동기화 이력을 불러올 수 없습니다."
        : "스냅샷 동기화 실행 이력이 없습니다. 시스템 상태를 확인하세요.",
      time: now,
      status: "OPEN",
    });
  }

  // Rule 3: 제출 대기 주문 존재 (긴급)
  if (!input.ordersError) {
    const pendingSubmit = input.orders.filter((o) => o.status === "submitted").length;
    if (pendingSubmit > 0) {
      alerts.push({
        id: "ALT-ORD-001",
        level: "긴급",
        title: "제출 대기 주문 존재",
        description: `브로커에 미제출된 주문이 ${pendingSubmit}건 있습니다. 즉시 확인하세요.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // Rule 4: 조정 필요 상태 존재 (주의)
  if (!input.ordersError) {
    const reconcileRequired = input.orders.filter((o) => o.status === "reconcile_required").length;
    if (reconcileRequired > 0) {
      alerts.push({
        id: "ALT-ORD-002",
        level: "주의",
        title: "조정 필요 상태 존재",
        description: `브로커 확정 불가 상태인 주문이 ${reconcileRequired}건 있습니다. 수동 확인이 필요합니다.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // Rule 5: 에이전트 실행 실패 (주의)
  if (!input.agentRunsError) {
    const failures = input.agentRuns.filter(
      (r) => r.status === "failed" || r.status === "error"
    ).length;
    if (failures > 0) {
      alerts.push({
        id: "ALT-AGENT-001",
        level: "주의",
        title: "에이전트 실행 실패",
        description: `AI 에이전트 실행 중 ${failures}건의 오류가 발생했습니다. 에이전트 실행 화면에서 확인하세요.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // Rule 6: 활성 락 존재 (주의)
  if (!input.reconSummaryError && input.reconSummary) {
    if (input.reconSummary.active_locks_count > 0) {
      alerts.push({
        id: "ALT-RECON-001",
        level: "주의",
        title: "활성 락 존재",
        description: `정합성 프로세스가 ${input.reconSummary.active_locks_count}개 계좌를 잠금 상태로 유지 중입니다.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // Rule 7: 주문-포지션 lineage 불일치 (경고)
  if (!input.ordersError && !input.positionsError) {
    if (input.orders.length === 0 && input.positionsCount > 0) {
      alerts.push({
        id: "ALT-LINEAGE-001",
        level: "경고",
        title: "주문-포지션 lineage 불일치",
        description: `주문 내역이 없으나 ${input.positionsCount}개의 포지션이 존재합니다. 데이터 정합성을 확인하세요.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // ── Snapshot Sync Alert Rules ──

  // SNAP-SYNC-001: status='partial' → 주의
  if (!input.snapshotSyncError && input.snapshotSyncRun) {
    if (input.snapshotSyncRun.status === "partial") {
      alerts.push({
        id: "SNAP-SYNC-001",
        level: "주의",
        title: "스냅샷 부분 성공",
        description: `스냅샷 동기화가 부분적으로만 완료되었습니다. (성공: ${input.snapshotSyncRun.succeeded_accounts}/${input.snapshotSyncRun.total_accounts} 계좌, 오류: ${input.snapshotSyncRun.error_count}건)`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // SNAP-SYNC-002: status='failed' → 긴급
  if (!input.snapshotSyncError && input.snapshotSyncRun) {
    if (input.snapshotSyncRun.status === "failed") {
      alerts.push({
        id: "SNAP-SYNC-002",
        level: "긴급",
        title: "스냅샷 동기화 실패",
        description: `최근 스냅샷 동기화가 실패했습니다. (실패 계좌: ${input.snapshotSyncRun.failed_accounts}/${input.snapshotSyncRun.total_accounts})`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // SNAP-SYNC-003a: API 오류 → 긴급
  if (input.snapshotSyncError) {
    alerts.push({
      id: "SNAP-SYNC-003a",
      level: "긴급",
      title: "스냅샷 동기화 상태 조회 실패",
      description: "스냅샷 동기화 상태를 조회할 수 없습니다. API 연결을 확인하세요.",
      time: now,
      status: "OPEN",
    });
  }

  // SNAP-SYNC-003b: run 없음 → 긴급
  if (!input.snapshotSyncError && !input.snapshotSyncRun) {
    alerts.push({
      id: "SNAP-SYNC-003b",
      level: "긴급",
      title: "스냅샷 동기화 이력 없음",
      description: "스냅샷 동기화 실행 이력이 없습니다. 시스템 상태를 확인하세요.",
      time: now,
      status: "OPEN",
    });
  }

  // SNAP-TIME-001: position/cash snapshot_at 차이 > 10분 → 경고
  if (input.latestPositionSnapshotAt && input.latestCashSnapshotAt) {
    const posTime = new Date(input.latestPositionSnapshotAt).getTime();
    const cashTime = new Date(input.latestCashSnapshotAt).getTime();
    const diffMs = Math.abs(posTime - cashTime);
    if (diffMs > 10 * 60 * 1000) {
      const diffMin = Math.round(diffMs / 60000);
      alerts.push({
        id: "SNAP-TIME-001",
        level: "경고",
        title: "현금/포지션 스냅샷 시각 불일치",
        description: `포지션 스냅샷과 현금 스냅샷의 갱신 시각이 ${diffMin}분 차이납니다. 데이터 정합성을 확인하세요.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // Rule 8: 모든 조건 정상 (정보)
  if (alerts.length === 0) {
    alerts.push({
      id: "ALT-OK-001",
      level: "정보",
      title: "시스템 정상",
      description: "모든 시스템이 정상 운영 중입니다. 이상 징후가 감지되지 않았습니다.",
      time: now,
      status: "RESOLVED",
    });
  }

  return alerts;
}

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
  const [levelFilter, setLevelFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);

  const fetchAlerts = async () => {
    setLoading(true);
    setError(null);

    try {
      // ── 시스템 상태 / 주문 / 정합성 요약 / 에이전트 (account_id 불필요) ──
      const [healthResult, ordersResult, reconSummaryResult, agentRunsResult] =
        await Promise.all([
          getHealth().then((h) => ({ data: h, error: false })).catch(() => ({ data: null as HealthResponse | null, error: true })),
          getOrders().then((o) => ({ data: o, error: false })).catch(() => ({ data: [] as OrderSummary[], error: true })),
          getReconciliationSummary().then((r) => ({ data: r, error: false })).catch(() => ({ data: null, error: true })),
          getAgentRuns().then((a) => ({ data: a, error: false })).catch(() => ({ data: [] as { status?: string }[], error: true })),
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
      });

      setAlerts(newAlerts);
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

  const filteredAlerts = useMemo(() => {
    return alerts.filter((alert) => {
      return !levelFilter || alert.level === levelFilter;
    });
  }, [alerts, levelFilter]);

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

      <div className="grid grid-cols-12 gap-6">
        {/* Alerts List */}
        <div className={selectedAlert ? "col-span-7" : "col-span-12"}>
          {/* Filter Buttons */}
          <div className="flex items-center gap-2 mb-4">
            <button
              onClick={() => setLevelFilter("")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === ""
                  ? "bg-[#3b82f6] text-white border-[#3b82f6]"
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#3b82f6]"
              }`}
            >
              전체
            </button>
            <button
              onClick={() => setLevelFilter("긴급")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === "긴급"
                  ? "bg-[#dc2626] text-white border-[#dc2626]"
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#dc2626]"
              }`}
            >
              긴급
            </button>
            <button
              onClick={() => setLevelFilter("주의")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === "주의"
                  ? "bg-[#f59e0b] text-white border-[#f59e0b]"
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#f59e0b]"
              }`}
            >
              주의
            </button>
            <button
              onClick={() => setLevelFilter("정보")}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                levelFilter === "정보"
                  ? "bg-[#3b82f6] text-white border-[#3b82f6]"
                  : "bg-white text-[#64748b] border-[#e2e8f0] hover:border-[#3b82f6]"
              }`}
            >
              정보
            </button>
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
              <p className="text-sm text-[#94a3b8]">선택한 수준의 알림이 없습니다</p>
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

      {/* Operation Notes Section */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-[#0f172a]">운영 메모</h2>
        <DataTable columns={noteColumns} data={operationNotes} idKey="id" />
      </div>

      {/* Pre-Market Checklist */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertCircle className="h-5 w-5 text-[#3b82f6]" />
          <h3 className="text-lg font-semibold text-[#0f172a]">내일 Pre-Market 확인 사항</h3>
        </div>
        <ul className="space-y-2">
          {preMarketChecklist.map((item) => (
            <li key={item.id} className="flex items-center gap-2 text-sm text-[#475569]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#3b82f6]" />
              {item.item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
