import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
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

function setFixtureOrderDate() {
  fireEvent.change(screen.getByLabelText("조회일"), {
    target: { value: "2026-05-05" },
  });
}

/** Renders the current URL's path+search so tests can assert on navigation. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

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
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    // Verify data is rendered
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Verify column headers
    expect(screen.getByText("종목")).toBeInTheDocument();
    expect(screen.getAllByText("매매")[0]).toBeInTheDocument();
    expect(screen.getAllByText("상태")[0]).toBeInTheDocument();
  });

  it("종목/매매/수량/주문유형/상태/시각 컬럼이 가운데 정렬로 표시된다", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    const row = screen.getByText("AAPL").closest("tr")!;
    const cells = Array.from(row.querySelectorAll("td"));
    // 컬럼 순서: 주문 ID, 종목, 종목명, 매매, 수량, 주문유형, 체결가격, 체결금액, 상태, 시각.
    expect(cells[1].className).toContain("text-center"); // 종목
    expect(cells[3].className).toContain("text-center"); // 매매
    expect(cells[4].className).toContain("text-center"); // 수량
    expect(cells[5].className).toContain("text-center"); // 주문유형
    expect(cells[8].className).toContain("text-center"); // 상태
    expect(cells[9].className).toContain("text-center"); // 시각
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

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

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
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    // Initially both orders visible
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
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
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    // Initially both visible
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
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
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
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
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
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

describe("OrdersView filter by selected date", () => {
  it("shows only orders matching the selected KST date", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // Date changes now re-fetch from the server with ?date=..., so the mock
    // for this second call returns only the entry the server would filter to.
    mockFetchOnce([
      {
        ...mockOrders[0],
        symbol: "TODAY1",
        created_at: "2026-05-05T00:00:00Z",
      },
    ]);
    setFixtureOrderDate();

    await waitFor(() => {
      expect(screen.getByText("TODAY1")).toBeInTheDocument();
    });
    expect(screen.queryByText("OTHER1")).not.toBeInTheDocument();
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
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    // Both orders visible initially
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Select "제출 대기" (pending_submit) — only TSLA has status=pending_submit
    const statusSelect = screen.getByLabelText("상태");
    await user.selectOptions(statusSelect, "pending_submit");

    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 10: Pagination footer 표시
 * ─────────────────────────────────────────── */
describe("OrdersView pagination footer", () => {
  it("shows pagination footer when orders are loaded", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    // Total item count should appear (mockOrders has 2 items)
    await waitFor(() => {
      expect(screen.getByText("총 2건")).toBeInTheDocument();
    });
    // Page navigation should appear
    expect(screen.getByRole("button", { name: "Previous page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 11: 종목 클릭 → 실시간 현재가 딥링크
 * ─────────────────────────────────────────── */
describe("OrdersView symbol deep link", () => {
  it("navigates to the realtime quote screen with ?symbol= when a symbol is clicked", async () => {
    mockFetchOnce(mockOrders);
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <OrdersView />
        <LocationProbe />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });
    mockFetchOnce(mockOrders);
    setFixtureOrderDate();

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Symbol text is still rendered as before — clicking it navigates away
    // without opening the order detail panel (row-click behavior).
    await user.click(screen.getByText("AAPL"));

    expect(screen.getByTestId("location-probe").textContent).toBe(
      "/operations/realtime-quotes?symbol=AAPL",
    );
    // Row-level selection (order detail panel) must not also trigger.
    expect(screen.queryByText("클라이언트 주문 ID")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 12: URL의 symbol/date query 초기 반영
 * ─────────────────────────────────────────── */
describe("OrdersView query param initial state", () => {
  it("반영: symbol과 date가 모두 있으면 해당 날짜를 조회일로 사용한다(전체 기간 배지 없음)", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter initialEntries={["/orders?symbol=AAPL&date=2026-05-05"]}>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // date query가 조회일 input에 반영되어야 한다.
    expect(screen.getByLabelText("조회일")).toHaveValue("2026-05-05");
    // symbol query가 검색어에 반영되어야 한다.
    expect(screen.getByPlaceholderText("심볼 또는 주문 ID 검색...")).toHaveValue("AAPL");
    // date가 있으므로 "전체 기간" 배지는 보이지 않아야 한다.
    expect(screen.queryByText(/전체 기간/)).not.toBeInTheDocument();
  });

  it("symbol만 있고 date가 없으면 오늘 날짜로 고정하지 않고 전체 기간(최근 주문) 모드로 전환한다", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter initialEntries={["/orders?symbol=AAPL"]}>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문")).toBeInTheDocument();
    });

    // "전체 기간" 모드 배지가 표시되고, 날짜 input(조회일)은 렌더링되지 않는다.
    expect(screen.getByText(/전체 기간/)).toBeInTheDocument();
    expect(screen.queryByLabelText("조회일")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("심볼 또는 주문 ID 검색...")).toHaveValue("AAPL");

    // symbol과 매칭되는 주문이 실제 조회 응답(날짜 필터 없이 받아온 최근 주문)에 있으면 보여야 한다.
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
  });

  it("전체 기간 모드에서 '오늘 날짜로 보기'를 누르면 조회일 지정 모드로 돌아간다", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter initialEntries={["/orders?symbol=AAPL"]}>
        <OrdersView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/전체 기간/)).toBeInTheDocument();
    });

    mockFetchOnce(mockOrders);
    fireEvent.click(screen.getByText("오늘 날짜로 보기"));

    await waitFor(() => {
      expect(screen.queryByText(/전체 기간/)).not.toBeInTheDocument();
      expect(screen.getByLabelText("조회일")).toBeInTheDocument();
    });
  });
});
