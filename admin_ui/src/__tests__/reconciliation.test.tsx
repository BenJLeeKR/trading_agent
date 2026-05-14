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
} from "./test-utils/fixtures";
import type { OrderSummary, PositionSnapshotView, BrokerOrderView } from "../types/api";

/* ── Helper: mock getOrders / getPositions / getBrokerOrders ── */

function mockApi(
  overrides?: {
    orders?: OrderSummary[];
    positions?: PositionSnapshotView[];
    brokerOrders?: BrokerOrderView[];
  },
) {
  const orders = overrides?.orders ?? [];
  const positions = overrides?.positions ?? [];
  const brokerOrders = overrides?.brokerOrders ?? [];

  vi.spyOn(client, "getOrders").mockResolvedValue(orders);
  vi.spyOn(client, "getPositions").mockResolvedValue(positions);
  vi.spyOn(client, "getBrokerOrders").mockResolvedValue(brokerOrders);
  vi.spyOn(client, "getAccounts").mockResolvedValue([]);
  vi.spyOn(client, "getReconciliationRuns").mockResolvedValue([]);
  vi.spyOn(client, "getReconciliationLocks").mockResolvedValue([]);
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
});
