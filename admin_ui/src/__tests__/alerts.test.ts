import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { deriveAlerts, type AlertItem, type AlertRuleInput } from "../lib/alerts";
import type {
  HealthResponse,
  SnapshotSyncRunSummary,
  SchedulerStatus,
  SchedulerStatusResponse,
  MarketSessionSummary,
} from "../types/api";

/* ───────────────────────────────────────────
 * Helpers
 * ─────────────────────────────────────────── */

/** Fixed "now" for all tests — 2026-05-16T06:00:00Z (KST 15:00) */
const NOW = "2026-05-16T06:00:00.000Z";

function makeHealth(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: "ok",
    version: "1.0.0",
    timestamp: NOW,
    database: "connected",
    runtime_mode: "postgres",
    snapshot_sync_detail: null,
    snapshot_sync_stale: null,
    snapshot_sync_last_successful_run_at: null,
    snapshot_sync_consecutive_failures: null,
    scheduler: null,
    ...overrides,
  };
}

function makeSyncRun(overrides: Partial<SnapshotSyncRunSummary> = {}): SnapshotSyncRunSummary {
  return {
    snapshot_sync_run_id: "test-run-0000-0000-000000000001",
    trigger_type: "manual",
    scope: "full",
    dry_run: false,
    total_accounts: 5,
    succeeded_accounts: 5,
    partial_accounts: 0,
    failed_accounts: 0,
    skipped_accounts: 0,
    positions_synced_total: 50,
    positions_skipped_total: 0,
    cash_synced_count: 5,
    error_count: 0,
    status: "completed",
    started_at: "2026-05-16T05:50:00Z",
    completed_at: "2026-05-16T05:55:00Z",
    after_hours: false,
    env_filter: null,
    status_filter: null,
    summary_json: null,
    ...overrides,
  };
}

function makeScheduler(overrides: Partial<SchedulerStatus> = {}): SchedulerStatus {
  return {
    last_heartbeat_at: "2026-05-16T05:55:00Z",
    is_trading_day: true,
    checked_at: "2026-05-16T05:55:00Z",
    healthy: true,
    ...overrides,
  };
}

function makeSession(overrides: Partial<MarketSessionSummary> = {}): MarketSessionSummary {
  return {
    id: 1,
    run_date: "2026-05-16",
    is_trading_day: true,
    opnd_yn: null,
    bzdy_yn: null,
    tr_day_yn: null,
    market_phase: "OPEN",
    raw_opnd_yn: null,
    raw_mkop_cls_code: null,
    raw_antc_mkop_cls_code: null,
    source: "kis_market_state_ws",
    reason: null,
    checked_at: "2026-05-16T05:55:00Z",
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function makeSessionResponse(overrides: Partial<SchedulerStatusResponse> = {}): SchedulerStatusResponse {
  return {
    status: "ok",
    data: makeSession(),
    healthy: true,
    stale_seconds: null,
    ...overrides,
  };
}

/** Default minimal input with all required fields populated at reasonable defaults */
function defaultInput(overrides: Partial<AlertRuleInput> = {}): AlertRuleInput {
  return {
    health: makeHealth(),
    healthError: false,
    orders: [],
    ordersError: false,
    reconSummary: { active_locks_count: 0, incomplete_recon_count: 0, activeIssueCount: 0, historicalFailedCount: 0 },
    reconSummaryError: false,
    agentRuns: [],
    agentRunsError: false,
    positionsCount: 0,
    positionsError: false,
    snapshotSyncRun: makeSyncRun(),
    snapshotSyncError: false,
    latestPositionSnapshotAt: "2026-05-16T05:55:00Z",
    latestCashSnapshotAt: "2026-05-16T05:55:00Z",
    schedulerHealth: makeScheduler(),
    sessionData: makeSessionResponse(),
    apiErrors: [],
    ...overrides,
  };
}

/** Find an alert by id in the result array */
function findAlert(alerts: AlertItem[], id: string): AlertItem | undefined {
  return alerts.find((a) => a.id === id);
}

/* ───────────────────────────────────────────
 * Test Suite: Snapshot Sync Rules
 * ─────────────────────────────────────────── */

describe("deriveAlerts — Snapshot Sync Rules", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /* ── TC-01: Snapshot fresh → no snapshot alerts ── */
  it("TC-01: snapshot fresh (<5min) → SNAP-SYNC-STALE-001 미발생, SNAP-SYNC-003b 미발생", () => {
    const input = defaultInput({
      snapshotSyncRun: makeSyncRun({
        completed_at: "2026-05-16T05:58:00Z", // 2 min ago → fresh
      }),
    });
    const alerts = deriveAlerts(input);

    expect(findAlert(alerts, "SNAP-SYNC-STALE-001")).toBeUndefined();
    expect(findAlert(alerts, "SNAP-SYNC-003b")).toBeUndefined();
    // System should be healthy → ALT-OK-001
    expect(findAlert(alerts, "ALT-OK-001")).toBeDefined();
  });

  /* ── TC-02: No snapshot sync run → SNAP-SYNC-003b ── */
  it("TC-02: snapshot sync run 없음 → SNAP-SYNC-003b 발생 (긴급)", () => {
    const input = defaultInput({
      snapshotSyncRun: null,
      snapshotSyncError: false,
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "SNAP-SYNC-003b");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("긴급");
    expect(alert!.title).toContain("스냅샷 동기화 이력");
  });

  /* ── TC-03: Snapshot sync run stale (>5min) → SNAP-SYNC-STALE-001 ── */
  it("TC-03: snapshot stale (>5분) → SNAP-SYNC-STALE-001 발생 (긴급)", () => {
    const input = defaultInput({
      snapshotSyncRun: makeSyncRun({
        completed_at: "2026-05-16T05:50:00Z", // 10 min ago → stale
      }),
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "SNAP-SYNC-STALE-001");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("긴급");
    expect(alert!.title).toContain("스냅샷 동기화 지연");
  });

  /* ── TC-04: After-hours + position/cash diff large → SNAP-TIME-001 미발생 ── */
  it("TC-04: after-hours cash-only + position/cash 10분 초과 차이 → SNAP-TIME-001 미발생 (면제)", () => {
    const input = defaultInput({
      // sessionData가 없으면 snapshotSyncRun.after_hours를 fallback으로 사용
      sessionData: null,
      snapshotSyncRun: makeSyncRun({
        after_hours: true,
        completed_at: "2026-05-16T05:58:00Z", // fresh
      }),
      // position/cash diff > 10 min
      latestPositionSnapshotAt: "2026-05-16T05:00:00Z", // 60 min ago
      latestCashSnapshotAt: "2026-05-16T05:55:00Z",     // 5 min ago
    });
    const alerts = deriveAlerts(input);

    // after-hours 면제 → SNAP-TIME-001 미발생
    expect(findAlert(alerts, "SNAP-TIME-001")).toBeUndefined();
  });

  /* ── TC-05: Regular hours + position/cash diff >10min → SNAP-TIME-001 ── */
  it("TC-05: 일반 장 + position/cash 10분 초과 차이 → SNAP-TIME-001 발생 (긴급)", () => {
    const input = defaultInput({
      snapshotSyncRun: makeSyncRun({
        after_hours: false,
        completed_at: "2026-05-16T05:58:00Z",
      }),
      latestPositionSnapshotAt: "2026-05-16T05:00:00Z", // 60 min ago
      latestCashSnapshotAt: "2026-05-16T05:55:00Z",     // 5 min ago
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "SNAP-TIME-001");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("긴급");
    expect(alert!.title).toContain("시각 불일치");
  });
});

/* ───────────────────────────────────────────
 * Test Suite: Alignment Detail Rules
 * ─────────────────────────────────────────── */

describe("deriveAlerts — Alignment Detail Rules", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /* ── SNAP-ALIGN-001: partial_position_only → 주의 ── */
  it("SNAP-ALIGN-001: partial_position_only 계좌 존재 → 주의 alert 발생", () => {
    const input = defaultInput({
      alignmentDetails: [
        { account_id: "ac-1111", detail: "partial_position_only" },
        { account_id: "ac-2222", detail: "same_run" },
      ],
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "SNAP-ALIGN-001");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("주의");
    expect(alert!.title).toContain("포지션 데이터만 조회");
    expect(alert!.description).toContain("ac-1111");
  });

  /* ── SNAP-ALIGN-002: timestamp_proximity → 정보 ── */
  it("SNAP-ALIGN-002: timestamp_proximity 계좌 존재 → 정보 alert 발생", () => {
    const input = defaultInput({
      alignmentDetails: [
        { account_id: "ac-3333", detail: "timestamp_proximity" },
      ],
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "SNAP-ALIGN-002");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("정보");
    expect(alert!.title).toContain("시간 근사 정합");
    expect(alert!.description).toContain("ac-3333");
  });

  /* ── SNAP-ALIGN-003: cash_only → 주의 ── */
  it("SNAP-ALIGN-003: cash_only 계좌 존재 → 주의 alert 발생", () => {
    const input = defaultInput({
      alignmentDetails: [
        { account_id: "ac-4444", detail: "cash_only" },
      ],
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "SNAP-ALIGN-003");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("주의");
    expect(alert!.title).toContain("현금 데이터만 조회");
    expect(alert!.description).toContain("ac-4444");
  });

  /* ── 정상 상태: 해당 detail 없음 → alert 미발생 ── */
  it("SNAP-ALIGN: 문제 상태 계좌 없음 → SNAP-ALIGN alert 미발생", () => {
    const input = defaultInput({
      alignmentDetails: [
        { account_id: "ac-5555", detail: "same_run" },
        { account_id: "ac-6666", detail: "after_hours_cash_updated" },
      ],
    });
    const alerts = deriveAlerts(input);

    expect(findAlert(alerts, "SNAP-ALIGN-001")).toBeUndefined();
    expect(findAlert(alerts, "SNAP-ALIGN-002")).toBeUndefined();
    expect(findAlert(alerts, "SNAP-ALIGN-003")).toBeUndefined();
  });

  /* ── alignmentDetails가 undefined일 때 → alert 미발생 ── */
  it("SNAP-ALIGN: alignmentDetails=undefined → SNAP-ALIGN alert 미발생", () => {
    const input = defaultInput({
      alignmentDetails: undefined,
    });
    const alerts = deriveAlerts(input);

    expect(findAlert(alerts, "SNAP-ALIGN-001")).toBeUndefined();
    expect(findAlert(alerts, "SNAP-ALIGN-002")).toBeUndefined();
    expect(findAlert(alerts, "SNAP-ALIGN-003")).toBeUndefined();
  });

  /* ── 다수 계좌 description에 account_id truncation 검증 ── */
  it("SNAP-ALIGN: 3개 초과 계좌는 외 N개로 표시", () => {
    const input = defaultInput({
      alignmentDetails: [
        { account_id: "ac-0001", detail: "cash_only" },
        { account_id: "ac-0002", detail: "cash_only" },
        { account_id: "ac-0003", detail: "cash_only" },
        { account_id: "ac-0004", detail: "cash_only" },
      ],
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "SNAP-ALIGN-003");
    expect(alert).toBeDefined();
    expect(alert!.description).toContain("외 1개");
  });
});

/* ───────────────────────────────────────────
 * Test Suite: Scheduler Rules
 * ─────────────────────────────────────────── */

describe("deriveAlerts — Scheduler Rules", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /* ── TC-06: Scheduler unhealthy → ALT-SCHED-001 ── */
  it("TC-06: scheduler healthy===false → ALT-SCHED-001 발생 (긴급)", () => {
    const input = defaultInput({
      schedulerHealth: makeScheduler({ healthy: false }),
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "ALT-SCHED-001");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("긴급");
    expect(alert!.title).toContain("운영 스케줄러 비정상");
  });

  /* ── TC-07: Scheduler healthy → ALT-SCHED-001 미발생 ── */
  it("TC-07: scheduler healthy===true → ALT-SCHED-001 미발생", () => {
    const input = defaultInput({
      schedulerHealth: makeScheduler({ healthy: true }),
    });
    const alerts = deriveAlerts(input);

    expect(findAlert(alerts, "ALT-SCHED-001")).toBeUndefined();
  });

  /* ── TC-08: Scheduler stale (>30min) → ALT-SCHED-002 ── */
  it("TC-08: scheduler heartbeat 30분 초과 stale → ALT-SCHED-002 발생 (주의)", () => {
    const input = defaultInput({
      schedulerHealth: makeScheduler({
        healthy: true,
        last_heartbeat_at: "2026-05-16T05:00:00Z", // 60 min ago → stale
      }),
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "ALT-SCHED-002");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("주의");
    expect(alert!.title).toContain("응답 없음");
  });

  /* ── TC-09: Scheduler fresh → ALT-SCHED-002 미발생 ── */
  it("TC-09: scheduler heartbeat fresh → ALT-SCHED-002 미발생", () => {
    const input = defaultInput({
      schedulerHealth: makeScheduler({
        last_heartbeat_at: "2026-05-16T05:58:00Z", // 2 min ago → fresh
      }),
    });
    const alerts = deriveAlerts(input);

    expect(findAlert(alerts, "ALT-SCHED-002")).toBeUndefined();
  });

  /* ── TC-10: Fallback source → ALT-SCHED-004 ── */
  it("TC-10: session data.source=fallback → ALT-SCHED-004 발생 (주의)", () => {
    const input = defaultInput({
      sessionData: makeSessionResponse({
        data: makeSession({ source: "fallback" }),
      }),
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "ALT-SCHED-004");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("주의");
    expect(alert!.title).toContain("Fallback");
  });

  /* ── No scheduler health data → scheduler alerts 미발생 ── */
  it("schedulerHealth=null → scheduler alert 미발생", () => {
    const input = defaultInput({
      schedulerHealth: null,
    });
    const alerts = deriveAlerts(input);

    expect(findAlert(alerts, "ALT-SCHED-001")).toBeUndefined();
    expect(findAlert(alerts, "ALT-SCHED-002")).toBeUndefined();
  });
});

/* ───────────────────────────────────────────
 * Test Suite: Existing Rules Regression
 * ─────────────────────────────────────────── */

describe("deriveAlerts — Existing Rules Regression", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /* ALT-SYS-001: health error */
  it("healthError=true → ALT-SYS-001 발생 (긴급)", () => {
    const input = defaultInput({
      healthError: true,
      health: null,
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "ALT-SYS-001");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("긴급");
  });

  /* ALT-ORD-001: pending submit orders */
  it("pending_submit 주문 존재 → ALT-ORD-001 발생 (긴급)", () => {
    const input = defaultInput({
      orders: [
        {
          order_request_id: "test-order-001",
          client_order_id: "client-ref-001",
          account_id: "test-account-001",
          side: "buy",
          order_type: "limit",
          status: "submitted",
          requested_quantity: 100,
          requested_price: null,
          symbol: "AAPL",
          instrument_name: null,
          correlation_id: "corr-001",
          trade_decision_id: null,
          created_at: "2026-05-16T05:50:00Z",
          updated_at: null,
          version: 1,
        },
      ],
    });
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "ALT-ORD-001");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("긴급");
  });

  /* ALT-OK-001: all healthy */
  it("모든 조건 정상 → ALT-OK-001 발생 (정보/RESOLVED)", () => {
    const input = defaultInput();
    const alerts = deriveAlerts(input);

    const alert = findAlert(alerts, "ALT-OK-001");
    expect(alert).toBeDefined();
    expect(alert!.level).toBe("정보");
    expect(alert!.status).toBe("RESOLVED");
  });
});

/* ───────────────────────────────────────────
* Test Suite: Reconciliation Alert Rules
*/
describe("deriveAlerts — Reconciliation Alert Rules", () => {
beforeEach(() => {
  // 기본 input: 모든 reconSummary 필드 0으로 정상 상태
  // reconSummaryError 없음, ALT-RECON-001/002 모두 미발생 조건
});

/* ALT-RECON-002: activeIssueCount > 0 → 긴급 */
it("activeIssueCount > 0 → ALT-RECON-002 발생 (긴급)", () => {
  const input = defaultInput({
    reconSummary: {
      active_locks_count: 0,
      incomplete_recon_count: 0,
      activeIssueCount: 3,
      historicalFailedCount: 0,
    },
  });
  const alerts = deriveAlerts(input);

  const alert = findAlert(alerts, "ALT-RECON-002");
  expect(alert).toBeDefined();
  expect(alert!.level).toBe("긴급");
  expect(alert!.title).toBe("정합성 문제 발생");
  expect(alert!.description).toContain("3건");
  expect(alert!.status).toBe("OPEN");
});

/* ALT-RECON-002: activeIssueCount === 0 → 미발생 */
it("activeIssueCount === 0 → ALT-RECON-002 미발생", () => {
  const input = defaultInput({
    reconSummary: {
      active_locks_count: 0,
      incomplete_recon_count: 0,
      activeIssueCount: 0,
      historicalFailedCount: 0,
    },
  });
  const alerts = deriveAlerts(input);

  const alert = findAlert(alerts, "ALT-RECON-002");
  expect(alert).toBeUndefined();
});

/* ALT-RECON-002: historicalFailedCount만 있고 activeIssueCount === 0 → 미발생 (noise 정책) */
it("historicalFailedCount > 0 + activeIssueCount === 0 → ALT-RECON-002 미발생 (noise 정책)", () => {
  const input = defaultInput({
    reconSummary: {
      active_locks_count: 0,
      incomplete_recon_count: 0,
      activeIssueCount: 0,
      historicalFailedCount: 5,
    },
  });
  const alerts = deriveAlerts(input);

  const alert = findAlert(alerts, "ALT-RECON-002");
  expect(alert).toBeUndefined();
});
});
