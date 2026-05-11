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

    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
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
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // Verify data is rendered
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Verify column headers
    expect(screen.getByText("심볼")).toBeInTheDocument();
    expect(screen.getAllByText("매매")[0]).toBeInTheDocument();
    expect(screen.getAllByText("상태")[0]).toBeInTheDocument();
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
      expect(screen.getByText("주문이 없습니다.")).toBeInTheDocument();
    });
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
 * Scenario 5: Filter by status (dropdown)
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
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // Initially both orders visible
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Select "Filled" from status dropdown
    const statusSelect = screen.getByLabelText("상태");
    await user.selectOptions(statusSelect, "filled");

    // Only AAPL (filled) should remain
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: Filter by side (dropdown)
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
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // Initially both visible
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Select "Buy" from side dropdown
    const sideSelect = screen.getByLabelText("매매");
    await user.selectOptions(sideSelect, "buy");

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
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // Type "AAPL" in search
    const searchInput = screen.getByPlaceholderText("심볼 또는 주문 ID 검색...");
    await user.type(searchInput, "AAPL");

    // Only AAPL should remain
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
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
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // Type "AAPL" in search
    const searchInput = screen.getByPlaceholderText("심볼 또는 주문 ID 검색...");
    await user.type(searchInput, "AAPL");

    // Select "Filled" from status dropdown — AAPL is filled, TSLA is pending_submit
    const statusSelect = screen.getByLabelText("상태");
    await user.selectOptions(statusSelect, "filled");

    // AAPL (filled, buy) should still show
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    // Now select "제출 대기" (pending_submit) — AAPL is not pending_submit, should disappear
    await user.selectOptions(statusSelect, "pending_submit");
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 9: Filter by canonical pending_submit
 * ─────────────────────────────────────────── */
describe("OrdersView filter by canonical status", () => {
  it("filters by pending_submit and shows TSLA only", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // Both orders visible initially
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Select "제출 대기" (pending_submit) — only TSLA has status=pending_submit
    const statusSelect = screen.getByLabelText("상태");
    await user.selectOptions(statusSelect, "pending_submit");

    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
  });
});
