/* ───────────────────────────────────────────
 * Pure helper: derive operational alerts
 *
 * UI-only computation.  No side effects, no API calls.
 * Shared between OperationsAlertsView and OperationsDashboardView.
 * ─────────────────────────────────────────── */
import type { HealthResponse, OrderSummary, SnapshotSyncRunSummary, SchedulerStatusResponse, AlignmentDetail } from "../types/api";
import { formatKstDateTime } from "./utils";

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
  reconSummary: { active_locks_count: number; incomplete_recon_count: number; activeIssueCount: number; historicalFailedCount: number } | null;
  reconSummaryError: boolean;
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
  // ── Scheduler health ──
  schedulerHealth: HealthResponse['scheduler'];
  // ── Market session data (for fallback source detection) ──
  sessionData: SchedulerStatusResponse | null;
  // ── Failed API names (for ALT-SYS-001) ──
  apiErrors?: { apiName: string; message: string }[];
  // ── Account-level alignment detail ──
  alignmentDetails?: Array<{
    account_id: string;
    detail: AlignmentDetail;
  }>;
}

/* ── Priority sort order ── */
export const LEVEL_PRIORITY: Record<string, number> = {
  "긴급": 1,
  "주의": 2,
  "경고": 3,
  "정보": 4,
};

/* ── Helpers ── */

function isStale(timestamp: string | null, maxMinutes: number): boolean {
  if (!timestamp) return true;
  const elapsed = (Date.now() - new Date(timestamp).getTime()) / 60000;
  return elapsed > maxMinutes;
}

/* ── Session-aware helpers ── */

/** 거래일/비거래일 판정: sessionData 우선, schedulerHealth fallback */
function isNonTradingDay(input: AlertRuleInput): boolean {
  if (input.sessionData?.data?.is_trading_day !== undefined) {
    return !input.sessionData.data.is_trading_day;
  }
  if (input.schedulerHealth?.is_trading_day !== undefined) {
    return !input.schedulerHealth.is_trading_day;
  }
  return false; // 기본값: 거래일로 간주 (alert 억제보다 발생이 안전)
}

/** 장후(After-Hours) 판정: sessionData.market_phase 우선, snapshotSyncRun.after_hours 보조 */
function isAfterHours(input: AlertRuleInput): boolean {
  if (input.sessionData?.data?.market_phase !== undefined && input.sessionData.data.market_phase !== null) {
    const phase: string = input.sessionData.data.market_phase;
    return phase.includes("장후") || phase.includes("after") || phase.includes("after-hours");
  }
  if (input.snapshotSyncRun?.after_hours !== undefined) {
    return input.snapshotSyncRun.after_hours === true;
  }
  return false;
}

/* ── Pure function: derive alerts ── */
export function deriveAlerts(input: AlertRuleInput): AlertItem[] {
  const alerts: AlertItem[] = [];
  const now = formatKstDateTime(new Date().toISOString());

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

  // Rule 2: (제거됨) ALT-SNAP-001/002 — reconRuns 기반 스냅샷 alert
  // → SNAP-SYNC-STALE-001 및 SNAP-SYNC-003b로 대체됨

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

  // Rule 6a: 활성 정합성 문제 (긴급) — ALT-RECON-002
  if (!input.reconSummaryError && input.reconSummary) {
    if (input.reconSummary.activeIssueCount > 0) {
      alerts.push({
        id: "ALT-RECON-002",
        level: "긴급",
        title: "정합성 문제 발생",
        description: `${input.reconSummary.activeIssueCount}건의 정합성 run이 아직 해결되지 않았습니다`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // Rule 6b: 활성 락 존재 (주의)
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

  // Rule 7: 주문-포지션 lineage 불일치 (주의)
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

  // ── Snapshot Sync Alert Rules (snapshotSyncRun 기반) ──

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

  // SNAP-SYNC-STALE-001: snapshotSyncRun 기반 스냅샷 동기화 지연
  // 세션 상태(비영업일/장후/정규장)에 따라 threshold 및 severity 변경
  if (!input.snapshotSyncError && input.snapshotSyncRun) {
    const shouldActivate = (() => {
      if (isNonTradingDay(input)) return false;
      if (!input.snapshotSyncRun!.completed_at) return true;
      if (isAfterHours(input)) return isStale(input.snapshotSyncRun!.completed_at, 15);
      return isStale(input.snapshotSyncRun!.completed_at, 5);
    })();

    if (shouldActivate) {
      alerts.push({
        id: "SNAP-SYNC-STALE-001",
        level: isAfterHours(input) ? "주의" : "긴급",
        title: "스냅샷 동기화 지연",
        description: !input.snapshotSyncRun.completed_at
          ? "스냅샷 동기화 기록 없음"
          : isAfterHours(input)
            ? `마지막 스냅샷: ${formatKstDateTime(input.snapshotSyncRun.completed_at)} (장후 15분 임계)`
            : `마지막 스냅샷: ${formatKstDateTime(input.snapshotSyncRun.completed_at)} (정규장 5분 임계)`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // SNAP-TIME-001: 현금/포지션 스냅샷 시각 불일치
  // 세션 상태(비영업일/장후)에 따라 면제 처리
  if (input.latestPositionSnapshotAt && input.latestCashSnapshotAt) {
    const shouldActivate = (() => {
      if (isNonTradingDay(input)) return false;
      if (isAfterHours(input)) return false;
      const posTime = new Date(input.latestPositionSnapshotAt!).getTime();
      const cashTime = new Date(input.latestCashSnapshotAt!).getTime();
      return Math.abs(posTime - cashTime) > 10 * 60 * 1000;
    })();

    if (shouldActivate) {
      const posTime = new Date(input.latestPositionSnapshotAt).getTime();
      const cashTime = new Date(input.latestCashSnapshotAt).getTime();
      const diffMin = Math.round(Math.abs(posTime - cashTime) / 60000);
      alerts.push({
        id: "SNAP-TIME-001",
        level: "긴급",
        title: "현금/포지션 스냅샷 시각 불일치",
        description: `현금 ${formatKstDateTime(input.latestCashSnapshotAt)} / 포지션 ${formatKstDateTime(input.latestPositionSnapshotAt)} (${diffMin}분 차이)`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // SNAP-BUDGET-001: budget fallback 발생 (VTTC8908R_pre_check > 0) → 주의
  if (!input.snapshotSyncError && input.snapshotSyncRun?.summary_json) {
    const sj = input.snapshotSyncRun.summary_json as Record<string, number>;
    const preCheck = sj["VTTC8908R_pre_check"] ?? 0;
    const budgetExhausted = sj["VTTC8908R_budget_exhausted"] ?? 0;
    const apiFailure = sj["VTTC8908R_api_failure"] ?? 0;
    const totalBudgetFallback = preCheck + budgetExhausted + apiFailure;
    if (totalBudgetFallback > 0) {
      const detailParts: string[] = [];
      if (preCheck > 0) detailParts.push(`pre-check ${preCheck}회`);
      if (budgetExhausted > 0) detailParts.push(`budget exhausted ${budgetExhausted}회`);
      if (apiFailure > 0) detailParts.push(`API 실패 ${apiFailure}회`);
      alerts.push({
        id: "SNAP-BUDGET-001",
        level: "주의",
        title: "스냅샷 Budget Fallback 발생",
        description: `총 ${totalBudgetFallback}회 fallback: ${detailParts.join(", ")}. orderable_cash가 KIS API 응답 대신 fallback 값으로 설정되었습니다.`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // SNAP-BUDGET-002: after_hours_skip > 0 → 정보
  if (!input.snapshotSyncError && input.snapshotSyncRun?.summary_json) {
    const sj = input.snapshotSyncRun.summary_json as Record<string, number>;
    const afterHoursSkip = sj["after_hours_skip"] ?? 0;
    if (afterHoursSkip > 0) {
      alerts.push({
        id: "SNAP-BUDGET-002",
        level: "정보",
        title: "장후 스냅샷 skip",
        description: `${afterHoursSkip}개 계좌가 장후(after-hours) 상태로 스냅샷이 생략되었습니다.`,
        time: now,
        status: afterHoursSkip > 0 ? "OPEN" : "RESOLVED",
      });
    }
  }

  // ── Alignment Detail Alert Rules ──

  // SNAP-ALIGN-001: partial_position_only → 주의
  if (input.alignmentDetails) {
    const partialPosOnly = input.alignmentDetails.filter(
      (a) => a.detail === "partial_position_only"
    );
    if (partialPosOnly.length > 0) {
      const ids = partialPosOnly.map((a) => a.account_id);
      const displayed = ids.slice(0, 3);
      const remainder = ids.length - 3;
      let desc = displayed.join(", ");
      if (remainder > 0) desc += ` 외 ${remainder}개`;
      alerts.push({
        id: "SNAP-ALIGN-001",
        level: "주의",
        title: "포지션 데이터만 조회된 계좌가 있습니다",
        description: `계좌: ${desc}`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // SNAP-ALIGN-002: timestamp_proximity → 정보
  if (input.alignmentDetails) {
    const tsProximity = input.alignmentDetails.filter(
      (a) => a.detail === "timestamp_proximity"
    );
    if (tsProximity.length > 0) {
      const ids = tsProximity.map((a) => a.account_id);
      const displayed = ids.slice(0, 3);
      const remainder = ids.length - 3;
      let desc = displayed.join(", ");
      if (remainder > 0) desc += ` 외 ${remainder}개`;
      alerts.push({
        id: "SNAP-ALIGN-002",
        level: "정보",
        title: "시간 근사 정합된 계좌가 있습니다 (legacy 데이터)",
        description: `계좌: ${desc}`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // SNAP-ALIGN-003: cash_only → 주의
  if (input.alignmentDetails) {
    const cashOnly = input.alignmentDetails.filter(
      (a) => a.detail === "cash_only"
    );
    if (cashOnly.length > 0) {
      const ids = cashOnly.map((a) => a.account_id);
      const displayed = ids.slice(0, 3);
      const remainder = ids.length - 3;
      let desc = displayed.join(", ");
      if (remainder > 0) desc += ` 외 ${remainder}개`;
      alerts.push({
        id: "SNAP-ALIGN-003",
        level: "주의",
        title: "현금 데이터만 조회된 계좌가 있습니다",
        description: `계좌: ${desc}`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // ── Scheduler Alert Rules ──

  const scheduler = input.schedulerHealth;

  // ALT-SCHED-001: scheduler unhealthy (긴급)
  if (scheduler && scheduler.healthy === false) {
    alerts.push({
      id: "ALT-SCHED-001",
      level: "긴급",
      title: "운영 스케줄러 비정상",
      description: "Scheduler 상태가 unhealthy입니다. 즉시 확인이 필요합니다.",
      time: now,
      status: "OPEN",
    });
  }

  // ALT-SCHED-002: scheduler stale (주의)
  if (scheduler && scheduler.last_heartbeat_at !== null) {
    if (isStale(scheduler.last_heartbeat_at, 30)) {
      alerts.push({
        id: "ALT-SCHED-002",
        level: "주의",
        title: "운영 스케줄러 응답 없음 (Stale)",
        description: `마지막 heartbeat: ${formatKstDateTime(scheduler.last_heartbeat_at)}`,
        time: now,
        status: "OPEN",
      });
    }
  }

  // ALT-SCHED-004: fallback source 사용 중 (주의)
  const sessionSource = input.sessionData?.data?.source;
  if (sessionSource === 'fallback' || sessionSource === 'gate_error_fallback') {
    alerts.push({
      id: "ALT-SCHED-004",
      level: "주의",
      title: "운영 스케줄러 Fallback 소스 사용 중",
      description: "KIS API 대체 소스 사용 중입니다. 연결 상태를 확인하세요.",
      time: now,
      status: "OPEN",
    });
  }

  // 모든 조건 정상 (정보)
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
