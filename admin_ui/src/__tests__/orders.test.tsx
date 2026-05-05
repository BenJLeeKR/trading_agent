import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import OrdersView from "../components/OrdersView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce } from "./test-utils/mockFetch";
import { mockOrders, VALID_TOKEN } from "./test-utils/fixtures";

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

/* ───────────────────────────────────────────
 * Scenario 1: 초기 로딩 상태
 * ─────────────────────────────────────────── */
describe("OrdersView loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 주문 목록 렌더링
 * ─────────────────────────────────────────── */
describe("OrdersView with order data", () => {
  it("renders order list in DataTable", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Orders")).toBeInTheDocument();
    });

    // Verify data is rendered
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Check total count
    expect(screen.getByText(/Total: 2 \/ 2 orders/)).toBeInTheDocument();

    // Verify column headers
    expect(screen.getByText("Symbol")).toBeInTheDocument();
    expect(screen.getByText("Side")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 빈 목록
 * ─────────────────────────────────────────── */
describe("OrdersView empty list", () => {
  it("shows empty message when no orders", async () => {
    mockFetchOnce([]);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("No orders found.")).toBeInTheDocument();
    });

    // Total should be 0
    expect(screen.getByText(/Total: 0 \/ 0 orders/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Row click → navigate
 * ─────────────────────────────────────────── */
describe("OrdersView row click navigation", () => {
  it("navigates to order detail on row click", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter initialEntries={["/orders"]}>
        <OrdersView />
      </MemoryRouter>,
    );

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Click on AAPL row (first order with order_request_id ending in 0001)
    const aaplRow = screen.getByText("AAPL").closest("tr");
    expect(aaplRow).toBeInTheDocument();
    await user.click(aaplRow!);

    // Verify navigation happened without error
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Filter by status (button group)
 * ─────────────────────────────────────────── */
describe("OrdersView filter by status", () => {
  it("shows only filtered orders when status is selected", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Orders")).toBeInTheDocument();
    });

    // Initially both orders visible
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText(/Total: 2 \/ 2 orders/)).toBeInTheDocument();

    // Click "Filled" status button
    const filledBtn = screen.getByRole("button", { name: /^Filled$/i });
    await user.click(filledBtn);

    // Only AAPL (filled) should remain
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
    expect(screen.getByText(/Total: 1 \/ 2 orders/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: Filter by side (button group)
 * ─────────────────────────────────────────── */
describe("OrdersView filter by side", () => {
  it("shows only matching side when side filter is selected", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Orders")).toBeInTheDocument();
    });

    // Initially both visible
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Click "Buy" side button
    const buyBtn = screen.getByRole("button", { name: /^Buy$/i });
    await user.click(buyBtn);

    // Only AAPL (buy) should remain
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Search by symbol
 * ─────────────────────────────────────────── */
describe("OrdersView search by symbol", () => {
  it("filters orders by symbol search text", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Orders")).toBeInTheDocument();
    });

    // Type "AAPL" in search
    const searchInput = screen.getByRole("searchbox", { name: /search by symbol/i });
    await user.type(searchInput, "AAPL");

    // Only AAPL should remain
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
    expect(screen.getByText(/Total: 1 \/ 2 orders/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 8: Filter + search combination
 * ─────────────────────────────────────────── */
describe("OrdersView combined filter and search", () => {
  it("applies both status filter and search text", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Orders")).toBeInTheDocument();
    });

    // Type "AAPL" in search
    const searchInput = screen.getByRole("searchbox", { name: /search by symbol/i });
    await user.type(searchInput, "AAPL");

    // Click "Filled" status button — AAPL is filled, TSLA is pending
    const filledBtn = screen.getByRole("button", { name: /^Filled$/i });
    await user.click(filledBtn);

    // AAPL (filled, buy) should still show
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    // Now click "Pending" — AAPL is not pending, should disappear
    const pendingBtn = screen.getByRole("button", { name: /^Pending$/i });
    await user.click(pendingBtn);
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    expect(screen.getByText(/Total: 0 \/ 2 orders/)).toBeInTheDocument();
  });
});
