import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import OrderDetail from "../components/OrderDetail";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import {
  mockOrderDetail,
  mockOrderDetailNoDecision,
  mockOrderEvents,
  mockBrokerOrders,
  mockEnumMetadataResponse,
  VALID_TOKEN,
} from "./test-utils/fixtures";

const ORDER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001";

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

function renderOrderDetail() {
  // Pre-load useEnumMetadata module-level cache so that the component
  // does not fire a fetch for /metadata/enums during the test.
  mockFetchOnce(mockEnumMetadataResponse);
  return render(
    <MemoryRouter initialEntries={[`/orders/${ORDER_ID}`]}>
      <Routes>
        <Route path="/orders/:orderId" element={<OrderDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

/* ───────────────────────────────────────────
 * Scenario 1: 로딩 상태
 * ─────────────────────────────────────────── */
describe("OrderDetail loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    renderOrderDetail();
    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 정상 데이터 (summary + events + broker orders + decision links)
 * ─────────────────────────────────────────── */
describe("OrderDetail with valid data", () => {
  it("renders order summary, events, broker orders, and decision links", async () => {
    // GET /orders/{orderId}
    mockFetchOnce(mockOrderDetail);
    // GET /orders/{orderId}/events
    mockFetchOnce(mockOrderEvents);
    // GET /orders/{orderId}/broker-orders
    mockFetchOnce(mockBrokerOrders);

    renderOrderDetail();

    await waitFor(() => {
      expect(screen.getByText("주문 상세")).toBeInTheDocument();
    });

    // Summary section
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("매수")).toBeInTheDocument();
    // "지정가" appears twice: subtitle + detail field → use getAllByText
    expect(screen.getAllByText("지정가").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("100").length).toBeGreaterThanOrEqual(1); // requested_quantity + filled_qty
    expect(screen.getByText("185.50")).toBeInTheDocument();

    // Back link (ArrowLeft icon + text)
    expect(screen.getByText("주문 목록으로")).toBeInTheDocument();

    // Decision Links footer (no colon in new template)
    expect(screen.getByText("의사결정 연결")).toBeInTheDocument();
    // Verify the IDs are rendered inside Link elements (they should have href)
    const contextLink = screen.getByRole("link", {
      name: /aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1/,
    });
    expect(contextLink).toBeInTheDocument();
    expect(contextLink).toHaveAttribute(
      "href",
      "/decisions?contextId=aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    );

    const decisionLink = screen.getByRole("link", {
      name: /aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00td1/,
    });
    expect(decisionLink).toBeInTheDocument();
    expect(decisionLink).toHaveAttribute(
      "href",
      "/decisions?contextId=aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    );

    // State Events section header
    expect(screen.getByText(/상태 이벤트 \(2\)/)).toBeInTheDocument();

    // Broker Orders section header
    expect(screen.getByText(/브로커 주문 \(1\)/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: State Events 테이블
 * ─────────────────────────────────────────── */
describe("OrderDetail state events table", () => {
  it("renders event rows with from/to StatusBadge", async () => {
    mockFetchOnce(mockOrderDetail);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    renderOrderDetail();

    await waitFor(() => {
      expect(screen.getByText("주문 상세")).toBeInTheDocument();
    });

    // Column headers
    expect(screen.getByText("시각")).toBeInTheDocument();
    expect(screen.getByText("이전")).toBeInTheDocument();
    expect(screen.getByText("이후")).toBeInTheDocument();
    expect(screen.getByText("사유")).toBeInTheDocument();

    // Event data
    expect(screen.getByText("Order submitted to broker")).toBeInTheDocument();
    expect(screen.getByText("Fill confirmed by broker")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Broker Orders 섹션
 * ─────────────────────────────────────────── */
describe("OrderDetail broker orders section", () => {
  it("renders broker order rows", async () => {
    mockFetchOnce(mockOrderDetail);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    renderOrderDetail();

    await waitFor(() => {
      expect(screen.getByText("주문 상세")).toBeInTheDocument();
    });

    // Column headers
    expect(screen.getByText("브로커")).toBeInTheDocument();
    expect(screen.getByText("Native 주문 ID")).toBeInTheDocument();
    expect(screen.getByText("제출 시각")).toBeInTheDocument();

    // Broker order data
    expect(screen.getByText("KIS")).toBeInTheDocument();
    expect(screen.getByText("KIS-NATIVE-001")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Decision Links 조건부 (null → 미표시)
 * ─────────────────────────────────────────── */
describe("OrderDetail without decision links", () => {
  it("hides Decision Links footer when both IDs are null", async () => {
    // Use the no-decision variant fixture
    mockFetchOnce(mockOrderDetailNoDecision);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    renderOrderDetail();

    await waitFor(() => {
      expect(screen.getByText("주문 상세")).toBeInTheDocument();
    });

    // Decision Links must NOT be present
    expect(screen.queryByText("의사결정 연결")).not.toBeInTheDocument();
    // Regular content should still render
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: API 실패
 * ─────────────────────────────────────────── */
describe("OrderDetail API error", () => {
  it("shows ErrorBanner when first API call fails", async () => {
    // First API (getOrderDetail) fails
    mockFetchError(500, "Internal server error");

    renderOrderDetail();

    await waitFor(() => {
      expect(
        screen.getByText(/Internal server error/i),
      ).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Order not found (null body)
 * ─────────────────────────────────────────── */
describe("OrderDetail order not found", () => {
  it("shows 'Order not found' when order data is null", async () => {
    // getOrderDetail returns null body → setOrder(null)
    mockFetchOnce(null);
    // Events and broker-orders still succeed (but irrelevant)
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    renderOrderDetail();

    await waitFor(() => {
      expect(screen.getByText("주문을 찾을 수 없습니다.")).toBeInTheDocument();
    });
  });
});
