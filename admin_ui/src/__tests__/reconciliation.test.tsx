import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReconciliationView from "../components/ReconciliationView";
import * as client from "../api/client";
import {
  mockReconcileRequiredWithPosition,
  mockReconcileRequiredNoPosition,
  mockReconcileRequiredPositionMatched,
  mockPositionForReconcile,
  mockPositionForReconcilePartial,
  mockBrokerOrderForReconcile,
  RECONCILE_ACCOUNT_ID,
  mockReconciliationRuns,
  mockReconciliationSummary,
  mockLocks,
} from "./test-utils/fixtures";
import type {
  OrderSummary,
  PositionSnapshotView,
  BrokerOrderView,
  ReconciliationRunSummary,
  BlockingLockStatus,
} from "../types/api";

/* ── Helper: mock getOrders / getPositions / getBrokerOrders ── */

function mockApi(
  overrides?: {
    orders?: OrderSummary[];
    positions?: PositionSnapshotView[];
    brokerOrders?: BrokerOrderView[];
    runs?: ReconciliationRunSummary[];
    locks?: BlockingLockStatus[];
  },
) {
  const orders = overrides?.orders ?? [];
  const positions = overrides?.positions ?? [];
  const brokerOrders = overrides?.brokerOrders ?? [];
  const runs = overrides?.runs ?? [];
  const locks = overrides?.locks ?? [];

  vi.spyOn(client, "getOrders").mockResolvedValue(orders);
  vi.spyOn(client, "getPositions").mockResolvedValue(positions);
  vi.spyOn(client, "getBrokerOrders").mockResolvedValue(brokerOrders);
  vi.spyOn(client, "getAccounts").mockResolvedValue([]);
  vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runs);
  vi.spyOn(client, "getReconciliationLocks").mockResolvedValue(locks);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

/* ── Tests ────────────────────────────────── */

describe("ReconciliationView reconcile_required section", () => {
  it("shows empty state when no reconcile_required orders exist", async () => {
    mockApi({ orders: [] });

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("조정이 필요한 주문이 없습니다.")).toBeTruthy();
    });
  });

  it("shows reconcile_required orders in the table", async () => {
    mockApi({
      orders: [mockReconcileRequiredWithPosition],
      positions: [mockPositionForReconcile],
    });

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeTruthy();
      expect(screen.getByText("반영됨")).toBeTruthy();
    });
  });

  it("shows positionReflected=true with price/quantity match → info variant", async () => {
    mockApi({
      orders: [mockReconcileRequiredPositionMatched],
      positions: [mockPositionForReconcile],
    });

    render(<ReconciliationView />);

    await waitFor(() => {
      // requested_price=50000, position average_price=50000, tolerance <= 1
      // quantity: 100 >= 100 → sufficient
      expect(screen.getByText("포지션 반영됨 · 수량/단가 정합")).toBeTruthy();
    });
  });

  it("shows positionReflected=false → warning variant", async () => {
    mockApi({
      orders: [mockReconcileRequiredNoPosition],
      positions: [], // no matching position
    });

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("조정 필요 · 포지션 미반영")).toBeTruthy();
    });
  });

  it("shows summary card with correct counts", async () => {
    mockApi({
      orders: [
        mockReconcileRequiredWithPosition,
        mockReconcileRequiredNoPosition,
      ],
      positions: [mockPositionForReconcile],
    });

    render(<ReconciliationView />);

    await waitFor(() => {
      // total=2, reflected=1 (only AAPL has position)
      expect(screen.getByText("2")).toBeTruthy(); // total
      expect(screen.getByText("1")).toBeTruthy(); // reflected
    });
  });

  it("loads broker info on expand", async () => {
    mockApi({
      orders: [mockReconcileRequiredWithPosition],
      positions: [mockPositionForReconcile],
      brokerOrders: [mockBrokerOrderForReconcile],
    });

    render(<ReconciliationView />);

    // Wait for table to render
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeTruthy();
    });

    // Click expand button
    const expandButtons = screen.getAllByTitle("브로커 정보 보기");
    await userEvent.click(expandButtons[0]);

    // Wait for broker info to appear
    await waitFor(() => {
      expect(screen.getByText("KIS")).toBeTruthy();
      expect(screen.getByText("KIS-NATIVE-001")).toBeTruthy();
    });
  });

  it("shows warning banner when more than 5 reconcile_required orders", async () => {
    const manyOrders: OrderSummary[] = Array.from(
      { length: 6 },
      (_, i) => ({
        ...mockReconcileRequiredWithPosition,
        order_request_id: `many-${i}`,
        symbol: `SYM${i}`,
      }),
    );

    mockApi({ orders: manyOrders, positions: [] });

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText(/조정 필요 주문 6건/)).toBeTruthy();
    });
  });

  /* ── Section-level loading tests ──────────── */

  it("shows runs/locks loading spinner independently from reconcile loading", async () => {
    // Make runs/locks slow, but orders resolve fast
    vi.spyOn(client, "getReconciliationRuns").mockImplementation(
      () => new Promise(() => {}), // never resolves
    );
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([
      mockReconcileRequiredWithPosition,
    ]);
    vi.spyOn(client, "getPositions").mockResolvedValue([mockPositionForReconcile]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    // runs/locks area should show loading spinner
    expect(screen.getByText("정합성 데이터 로딩 중...")).toBeTruthy();

    // reconcile section should NOT show its loading spinner (it resolves fast)
    // Instead, it should resolve and show orders
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeTruthy();
    });
  });

  /* ── 3-way error tests ────────────────────── */

  it("shows runs error banner but locks section still renders", async () => {
    vi.spyOn(client, "getReconciliationRuns").mockRejectedValue(
      new Error("Runs API error"),
    );
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue(mockLocks);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      // Runs error banner should appear
      expect(screen.getByText("Runs API error")).toBeTruthy();
      // Locks section should still render — active lock is visible
      expect(screen.getByText("Manual review required")).toBeTruthy();
    });
  });

  it("shows locks error banner but runs section still renders", async () => {
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(mockReconciliationRuns);
    vi.spyOn(client, "getReconciliationLocks").mockRejectedValue(
      new Error("Locks API error"),
    );
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      // Locks error banner should appear
      expect(screen.getByText("Locks API error")).toBeTruthy();
      // Runs section should still render
      expect(screen.getByText("완료")).toBeTruthy(); // from mockReconciliationRuns status badge
    });
  });

  /* ── Summary semantics tests ──────────────── */

  it("shows loading spinner instead of summary card while reconcile loading", async () => {
    // Make orders slow so reconcile loading stays true
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockImplementation(
      () => new Promise(() => {}), // never resolves
    );
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    // Wait for runs/locks to resolve (empty)
    await waitFor(() => {
      expect(screen.getByText("차단 잠금이 없습니다.")).toBeTruthy();
    });

    // Reconcile section should show loading spinner, NOT summary card
    expect(screen.getByText("조정 필요 주문 로딩 중...")).toBeTruthy();
    // Summary card text should NOT be visible (no misleading "0")
    expect(screen.queryByText("조정 필요 주문")).toBeNull();
  });

  it("shows partial data warning when reconcile error with existing data", async () => {
    // Orders available but positions fail
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([
      mockReconcileRequiredWithPosition,
    ]);
    vi.spyOn(client, "getPositions").mockRejectedValue(
      new Error("Positions fetch failed"),
    );
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      // Partial data warning should appear
      expect(screen.getByText("데이터 일부 누락")).toBeTruthy();
      // Orders should still be visible (we have reconcileCases from orders alone)
      expect(screen.getByText("AAPL")).toBeTruthy();
    });
  });

  /* ── Regression: broker lazy load unchanged ── */

  it("loads broker info on expand (regression check)", async () => {
    mockApi({
      orders: [mockReconcileRequiredWithPosition],
      positions: [mockPositionForReconcile],
      brokerOrders: [mockBrokerOrderForReconcile],
    });

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeTruthy();
    });

    const expandButtons = screen.getAllByTitle("브로커 정보 보기");
    await userEvent.click(expandButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("KIS")).toBeTruthy();
      expect(screen.getByText("KIS-NATIVE-001")).toBeTruthy();
    });
  });
});

/* ───────────────────────────────────────────
 * UI Policy Finalization: ReconciliationView
 * ─────────────────────────────────────────── */

/* ── Helper: dummy run factory ── */
function makeRun(
  overrides: Partial<ReconciliationRunSummary>,
): ReconciliationRunSummary {
  return {
    reconciliation_run_id: "rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrr01",
    account_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1",
    trigger_type: "manual",
    status: "completed",
    started_at: "2026-05-05T00:00:00Z",
    completed_at: "2026-05-05T00:00:05Z",
    mismatch_count: 0,
    isActive: false,
    failure_reason: null,
    summary_error: null,
    order_count: 0,
    ...overrides,
  };
}

describe("ReconciliationView getStatusBadge", () => {
  it("completed + isActive=false → ✅ 완료, text-green-600", async () => {
    const runs = [makeRun({ status: "completed", isActive: false })];
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runs);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    const { container } = render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("✅ 완료")).toBeTruthy();
    });

    const badge = container.querySelector(".text-green-600");
    expect(badge).toBeTruthy();
    expect(badge?.textContent).toContain("✅ 완료");
  });

  it("started + isActive=false → 🔄 진행 중, text-blue-600", async () => {
    const runs = [makeRun({ status: "started", isActive: false })];
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runs);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    const { container } = render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("🔄 진행 중")).toBeTruthy();
    });

    const badge = container.querySelector(".text-blue-600");
    expect(badge).toBeTruthy();
    expect(badge?.textContent).toContain("🔄 진행 중");
  });

  it("failed + isActive=true → 🔴 조치 필요, text-red-600", async () => {
    const runs = [makeRun({ status: "failed", isActive: true })];
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runs);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    const { container } = render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("🔴 조치 필요")).toBeTruthy();
    });

    const badge = container.querySelector(".text-red-600");
    expect(badge).toBeTruthy();
    expect(badge?.textContent).toContain("🔴 조치 필요");
  });

  it("failed + isActive=false → 📋 과거 이력, text-gray-400", async () => {
    const runs = [makeRun({ status: "failed", isActive: false })];
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runs);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    const { container } = render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("📋 과거 이력")).toBeTruthy();
    });

    const badge = container.querySelector(".text-gray-400");
    expect(badge).toBeTruthy();
    expect(badge?.textContent).toContain("📋 과거 이력");
  });

  it("partial + isActive=true → 🔴 조치 필요", async () => {
    const runs = [makeRun({ status: "partial", isActive: true })];
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runs);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("🔴 조치 필요")).toBeTruthy();
    });
  });

  it("partial + isActive=false → 📋 과거 이력", async () => {
    const runs = [makeRun({ status: "partial", isActive: false })];
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runs);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("📋 과거 이력")).toBeTruthy();
    });
  });
});

describe("Active Issues section", () => {
  it("shows active issue warning when active issues exist", async () => {
    const activeRun = makeRun({
      status: "failed",
      isActive: true,
      mismatch_count: 2,
    });
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([activeRun]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(
        screen.getByText(/정합성 run/),
      ).toBeTruthy();
      expect(
        screen.getByText(/해결되지 않은 주문/),
      ).toBeTruthy();
    });
  });

  it("shows all-clear message when no active issues exist", async () => {
    const completedRun = makeRun({ status: "completed", isActive: false });
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([completedRun]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(
        screen.getByText("✅ 현재 해결되지 않은 정합성 문제가 없습니다."),
      ).toBeTruthy();
    });
  });

  it("shows isActive badge in active issues list", async () => {
    const activeRun = makeRun({
      status: "failed",
      isActive: true,
      mismatch_count: 1,
    });
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([activeRun]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      // The active issue section heading should show the count
      expect(
        screen.getByText(/조치 필요한 정합성 문제/),
      ).toBeTruthy();
    });
  });
});

describe("Historical row dimming", () => {
  it("applies opacity-50 to historical active runs via rowClassName", async () => {
    const historicalRun = makeRun({
      status: "failed",
      isActive: false,
    });
    const completedRun = makeRun({
      reconciliation_run_id: "rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrr99",
      status: "completed",
      isActive: false,
    });
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([
      historicalRun,
      completedRun,
    ]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("📋 과거 이력")).toBeTruthy();
    });

    // The DataTable applies rowClassName — check that at least one row has opacity-50
    const dimmedRows = document.querySelectorAll("tr.opacity-50");
    expect(dimmedRows.length).toBeGreaterThanOrEqual(1);
  });

  it("does not apply opacity-50 to completed runs", async () => {
    const completedRun = makeRun({ status: "completed", isActive: false });
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([completedRun]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("✅ 완료")).toBeTruthy();
    });

    const dimmedRows = document.querySelectorAll("tr.opacity-50");
    expect(dimmedRows.length).toBe(0);
  });
});

describe("Table legend", () => {
  it("renders legend with Active, Historical, and Completed descriptions", async () => {
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      // "🔴 Active Issues Only" 토글 버튼과 충돌 방지를 위해 더 구체적인 패턴 사용
      expect(
        screen.getByText(/🔴 Active:/),
      ).toBeTruthy();
      expect(
        screen.getByText(/📋 과거 이력/),
      ).toBeTruthy();
      expect(
        screen.getByText(/✅ 완료/),
      ).toBeTruthy();
    });
  });
});

describe("Run Detail panel historical note", () => {
  it("shows historical note for historical failed runs", async () => {
    const historicalRun = makeRun({
      status: "failed",
      isActive: false,
    });
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([historicalRun]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    // Wait for data table to render then click to select the run
    await waitFor(() => {
      expect(screen.getByText("📋 과거 이력")).toBeTruthy();
    });

    // Click the row to open detail panel
    const row = document.querySelector("tr.cursor-pointer") as HTMLElement | null;
    if (row) {
      row.click();
    }

    await waitFor(() => {
      expect(
        screen.getByText(/연결 주문은 모두 정리되었습니다/),
      ).toBeTruthy();
    });
  });

  it("does NOT show historical note for active runs", async () => {
    const activeRun = makeRun({
      status: "failed",
      isActive: true,
    });
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([activeRun]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("🔴 조치 필요")).toBeTruthy();
    });

    // Click the row to open detail panel
    const row = document.querySelector("tr.cursor-pointer") as HTMLElement | null;
    if (row) {
      row.click();
    }

    await waitFor(() => {
      // Active run detail should NOT show the historical note
      expect(
        screen.queryByText(/연결 주문은 모두 정리되었습니다/),
      ).toBeNull();
    });
  });
});

/* ── Historical Failed Runs (collapsible section) ──── */

describe("Historical Failed Runs collapsible section", () => {
  it("renders collapsed historical section when historicalFailedCount > 0", async () => {
    // historicalFailedCount is derived from runs.filter(r => !r.isActive && r.status !== "completed")
    const runsWithHistorical = [
      makeRun({ status: "failed", isActive: false }),
      makeRun({ status: "failed", isActive: false }),
      makeRun({ status: "partial", isActive: false }),
    ];
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue(runsWithHistorical);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);
    vi.spyOn(client, "getReconciliationSummary").mockResolvedValue(mockReconciliationSummary);

    render(<ReconciliationView />);

    await waitFor(() => {
      // JSX {historicalFailedCount} inserts a separate text node, so use regex
      expect(screen.getByText(/📋 과거 실패 이력 \(3건\)/)).toBeInTheDocument();
    });
  });

  it("lazy-loads historical failed runs when expanded", async () => {
    const user = userEvent.setup();
    const historicalRuns = [
      makeRun({
        reconciliation_run_id: "hhhhhhhh-hhhh-hhhh-hhhh-hhhhhhhhhh01",
        status: "failed",
        isActive: false,
        failure_reason: "broker 오류: timeout",
        summary_error: "Connection timeout",
      }),
    ];
    // First call (initial load): return one run to make historicalFailedCount = 1
    // Second call (historical fetch, includeHistorical=true): return detailed historical runs
    const runsSpy = vi.spyOn(client, "getReconciliationRuns");
    runsSpy.mockResolvedValueOnce([makeRun({ status: "failed", isActive: false })]);
    runsSpy.mockResolvedValueOnce(historicalRuns);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);
    vi.spyOn(client, "getReconciliationSummary").mockResolvedValue(mockReconciliationSummary);

    render(<ReconciliationView />);

    // Use getByRole to find the button by its role and partial text content
    await waitFor(() => {
      expect(screen.getByText(/📋 과거 실패 이력 \(1건\)/)).toBeInTheDocument();
    });

    // Click to expand
    await user.click(screen.getByText(/📋 과거 실패 이력 \(1건\)/));

    await waitFor(() => {
      // Historical runs should now be visible with failure_reason
      expect(screen.getByText("broker 오류: timeout")).toBeInTheDocument();
    });

    // Verify API was called with includeHistorical=true
    const calls = runsSpy.mock.calls;
    const historicalCall = calls.find(c => c[1] === true);
    expect(historicalCall).toBeTruthy();
  });

  it("shows historical run detail with summary_error when selected", async () => {
    const user = userEvent.setup();
    const historicalRuns = [
      makeRun({
        reconciliation_run_id: "hhhhhhhh-hhhh-hhhh-hhhh-hhhhhhhhhh01",
        status: "failed",
        isActive: false,
        failure_reason: "broker 오류: timeout",
        summary_error: "Connection timeout\nRetry failed",
      }),
    ];

    vi.spyOn(client, "getReconciliationRuns")
      .mockResolvedValueOnce([makeRun({ status: "failed", isActive: false })])
      .mockResolvedValueOnce(historicalRuns);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);
    vi.spyOn(client, "getReconciliationSummary").mockResolvedValue(mockReconciliationSummary);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText(/📋 과거 실패 이력 \(1건\)/)).toBeInTheDocument();
    });

    // Expand
    await user.click(screen.getByText(/📋 과거 실패 이력 \(1건\)/));

    await waitFor(() => {
      expect(screen.getByText("broker 오류: timeout")).toBeInTheDocument();
    });

    // Click detail button to view summary_error
    const detailButtons = screen.getAllByText(/상세/);
    await user.click(detailButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/Connection timeout/)).toBeInTheDocument();
      expect(screen.getByText(/Retry failed/)).toBeInTheDocument();
    });
  });

  it("does not show historical section when historicalFailedCount is 0", async () => {
    // Default makeRun() has isActive: false, status: "completed" → filtered out (status === "completed" excludes it)
    // So with completed runs, historicalFailedCount = 0
    vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([
      makeRun({ status: "completed", isActive: false }),
    ]);
    vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
    vi.spyOn(client, "getOrders").mockResolvedValue([]);
    vi.spyOn(client, "getPositions").mockResolvedValue([]);
    vi.spyOn(client, "getAccounts").mockResolvedValue([]);
    vi.spyOn(client, "getBrokerOrders").mockResolvedValue([]);
    vi.spyOn(client, "getReconciliationSummary").mockResolvedValue(mockReconciliationSummary);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.queryByText(/과거 실패 이력/)).not.toBeInTheDocument();
    });
  });
});
