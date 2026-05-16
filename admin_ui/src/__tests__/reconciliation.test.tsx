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
