/* ───────────────────────────────────────────
 * Pure helper: derive operational alerts
 *
 * UI-only computation.  No side effects, no API calls.
 * Shared between OperationsAlertsView and OperationsDashboardView.
 * ─────────────────────────────────────────── */
import type { HealthResponse, OrderSummary, ReconciliationRunSummary, SnapshotSyncRunSummary } from "../types/api";

/* ── Public types ────────────────────────── */

export interface AlertItem {
  id: string;
  level: "긴급" | "주의" | "경고" | "정보";
  title: string;
  description: string;
  time: string;
  status: "OPEN" | "RESOLVED";
}

export interface AlertRuleInput {
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
  // ── Failed API names (for ALT-SYS-001) ──
  apiErrors?: { apiName: string; message: string }[];
}

/* ── Priority sort order ── */
export const LEVEL_PRIORITY: Record<string, number> = {
  "긴급": 1,
  "주의": 2,
  "경고": 3,
  "정보": 4,
};

/* ── Pure function: derive alerts ── */
export function deriveAlerts(input: AlertRuleInput): AlertItem[] {
  const alerts: AlertItem[] = [];
  const now = new Date().toISOString().replace("T", " ").slice(0, 19);

  // Rule 1: API 상태 이상 (긴급)
  if (input.healthError || !input.health || input.health.status !== "ok") {
    const failedApis = input.apiErrors?.length
      ? input.apiErrors.map((e) => e.apiName).join(", ")
      : "GET /health";
    alerts.push({
      id: "ALT-SYS-001",
      level: "긴급",
      title: "API 상태 이상",
      description: `API 응답 없음: ${failedApis}`,
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
        description: "브로커 확정 상태 확인이 필요한 주문이 있습니다.",
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

  // Rule 7: 주문-포지션 lineage 불일치 (주의 — UI 통일: "경고" → "주의")
  if (!input.ordersError && !input.positionsError) {
    if (input.orders.length === 0 && input.positionsCount > 0) {
      alerts.push({
        id: "ALT-LINEAGE-001",
        level: "주의",
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
        description: "일부 스냅샷이 최신이 아닐 수 있습니다.",
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

  // SNAP-TIME-001: position/cash snapshot_at 차이 > 10분 → 주의 (UI 통일: "경고" → "주의")
  if (input.latestPositionSnapshotAt && input.latestCashSnapshotAt) {
    const posTime = new Date(input.latestPositionSnapshotAt).getTime();
    const cashTime = new Date(input.latestCashSnapshotAt).getTime();
    const diffMs = Math.abs(posTime - cashTime);
    if (diffMs > 10 * 60 * 1000) {
      const diffMin = Math.round(diffMs / 60000);
      alerts.push({
        id: "SNAP-TIME-001",
        level: "주의",
        title: "현금/포지션 스냅샷 시각 불일치",
        description: `포지션 스냅샷과 현금 스냅샷의 갱신 시각이 ${diffMin}분 차이납니다. 데이터 정합성을 확인하세요.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // Rule 8: 모든 조건 정상 (정보 → 정상 표시용)
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
