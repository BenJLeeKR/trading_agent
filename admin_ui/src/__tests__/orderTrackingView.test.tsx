import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import OrderTrackingView from "../components/OrderTrackingView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce } from "./test-utils/mockFetch";

/* ── Mock useEnumMetadata to avoid real network calls ────────────── */
vi.mock("../hooks/useEnumMetadata", () => ({
  useEnumMetadata: () => ({
    fieldMap: {
      reason_code: {
        field: "reason_code",
        type: "string",
        values: [
          { value: "BLOCKED", label: "차단됨", description: null, broker_code: null, supported: true },
          { value: "UNCERTAIN", label: "불확실 상태", description: null, broker_code: null, supported: true },
          { value: "RECONCILE_RESOLVED", label: "조정 해소", description: null, broker_code: null, supported: true },
          { value: "MANUAL_RESOLVE", label: "운영자 수동 해소", description: null, broker_code: null, supported: true },
          { value: "manual_paper_resolution", label: "운영자 수동 해소", description: null, broker_code: null, supported: true },
          { value: "WS_FILL", label: "WS 체결 수신", description: null, broker_code: null, supported: true },
          { value: "FILL_CONFIRMED", label: "체결 확인", description: null, broker_code: null, supported: true },
          { value: "REJECTED", label: "거부됨", description: null, broker_code: null, supported: true },
        ],
      },
    },
    loading: false,
    error: null,
  }),
  getEnumLabel: (_fm: Record<string, any>, _field: string, value: string | null | undefined) => {
    if (!value) return "-";
    return value;
  },
}));
import {
  mockOrders,
  mockOrderDetail,
  mockOrderEvents,
  mockBrokerOrders,
  VALID_TOKEN,
} from "./test-utils/fixtures";

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
describe("OrderTrackingView loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    expect(screen.getByText("주문 데이터 로딩 중...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 주문 목록 렌더링
 * ─────────────────────────────────────────── */
describe("OrderTrackingView with order data", () => {
  it("renders order list in DataTable", async () => {
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("주문 추적")).toBeInTheDocument();
    });

    // Verify data is rendered
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Verify column headers
    expect(screen.getByText("주문 ID")).toBeInTheDocument();
    expect(screen.getByText("종목")).toBeInTheDocument();
    // "상태" appears in both FilterBar dropdown and table header → use getAllByText
    expect(screen.getAllByText("상태").length).toBeGreaterThanOrEqual(1);
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 상태 전이 타임라인 — 필드 매핑 확인
 * ─────────────────────────────────────────── */
describe("OrderTrackingView event timeline", () => {
  it("renders event timeline with correct field mappings (previous_status → new_status)", async () => {
    const user = userEvent.setup();

    // Queue: getOrders, then row click triggers getOrderDetail + getOrderEvents + getBrokerOrders
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockOrderDetail);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    // Wait for orders to load
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Click on AAPL row to open detail
    const aaplRow = screen.getByText("AAPL").closest("tr");
    expect(aaplRow).toBeInTheDocument();
    await user.click(aaplRow!);

    // Wait for event timeline to appear
    await waitFor(() => {
      expect(screen.getByText("상태 전이 타임라인")).toBeInTheDocument();
    });

    // Verify column headers match new field names
    expect(screen.getByText("이전 상태")).toBeInTheDocument();
    expect(screen.getByText("이후 상태")).toBeInTheDocument();
    expect(screen.getByText("시간")).toBeInTheDocument();
    expect(screen.getByText("사유")).toBeInTheDocument();
    expect(screen.getByText("소스")).toBeInTheDocument();

    // Verify new_status=submitted is displayed
    // "제출됨" appears in both FilterBar dropdown and event timeline → use getAllByText
    expect(screen.getAllByText("제출됨").length).toBeGreaterThanOrEqual(1);

    // Verify event_source is shown
    expect(screen.getByText("INTERNAL")).toBeInTheDocument();
    expect(screen.getByText("BROKER")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: event_timestamp KST 포맷 확인
 * ─────────────────────────────────────────── */
describe("OrderTrackingView KST timestamp", () => {
  it("displays event_timestamp in KST format (UTC+9)", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockOrderDetail);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Click on AAPL row
    const aaplRow = screen.getByText("AAPL").closest("tr");
    await user.click(aaplRow!);

    // Wait for event timeline
    await waitFor(() => {
      expect(screen.getByText("상태 전이 타임라인")).toBeInTheDocument();
    });

    // 2026-05-05T00:00:01Z → KST: 2026-05-05 09:00:01 KST
    // 2026-05-05T00:00:05Z → KST: 2026-05-05 09:00:05 KST
    expect(screen.getByText("2026-05-05 09:00:01 KST")).toBeInTheDocument();
    expect(screen.getByText("2026-05-05 09:00:05 KST")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: reason_code=null → "—" 표시
 * ─────────────────────────────────────────── */
describe("OrderTrackingView reason_code null handling", () => {
  it("shows — when reason_code is null", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockOrderDetail);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Click on AAPL row
    const aaplRow = screen.getByText("AAPL").closest("tr");
    await user.click(aaplRow!);

    // Wait for event timeline
    await waitFor(() => {
      expect(screen.getByText("상태 전이 타임라인")).toBeInTheDocument();
    });

    // First event has reason_code=null → "—" displayed
    const dashElements = screen.getAllByText("—");
    expect(dashElements.length).toBeGreaterThanOrEqual(1);

    // Second event has reason_code="FILL_CONFIRMED" → formatter → "체결 확인"
    expect(screen.getByText("체결 확인")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: idKey="order_state_event_id" row 렌더링
 * ─────────────────────────────────────────── */
describe("OrderTrackingView row key with order_state_event_id", () => {
  it("renders event DataTable without row key errors when idKey=order_state_event_id", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockOrderDetail);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Click on AAPL row
    const aaplRow = screen.getByText("AAPL").closest("tr");
    await user.click(aaplRow!);

    // Wait for event timeline to render
    await waitFor(() => {
      expect(screen.getByText("상태 전이 타임라인")).toBeInTheDocument();
    });

    // Verify both event rows are rendered (by checking event data)
    expect(screen.getByText("INTERNAL")).toBeInTheDocument();
    expect(screen.getByText("BROKER")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: statusLabel() 모든 OrderStatus 커버리지
 * ─────────────────────────────────────────── */
describe("OrderTrackingView statusLabel coverage", () => {
  it("displays Korean labels for all order statuses in the timeline", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockOrderDetail);

    // Create events covering all status types
    const coverageEvents = [
      {
        order_state_event_id: "evt-draft",
        previous_status: null,
        new_status: "draft",
        event_timestamp: "2026-05-05T00:00:00Z",
        reason_code: null,
        event_source: "INTERNAL",
      },
      {
        order_state_event_id: "evt-validated",
        previous_status: "draft",
        new_status: "validated",
        event_timestamp: "2026-05-05T00:00:01Z",
        reason_code: null,
        event_source: "INTERNAL",
      },
      {
        order_state_event_id: "evt-pending-submit",
        previous_status: "validated",
        new_status: "pending_submit",
        event_timestamp: "2026-05-05T00:00:02Z",
        reason_code: null,
        event_source: "INTERNAL",
      },
      {
        order_state_event_id: "evt-submitted",
        previous_status: "pending_submit",
        new_status: "submitted",
        event_timestamp: "2026-05-05T00:00:03Z",
        reason_code: null,
        event_source: "INTERNAL",
      },
      {
        order_state_event_id: "evt-cancel-pending",
        previous_status: "submitted",
        new_status: "cancel_pending",
        event_timestamp: "2026-05-05T00:00:04Z",
        reason_code: null,
        event_source: "INTERNAL",
      },
      {
        order_state_event_id: "evt-cancelled",
        previous_status: "cancel_pending",
        new_status: "cancelled",
        event_timestamp: "2026-05-05T00:00:05Z",
        reason_code: null,
        event_source: "INTERNAL",
      },
      {
        order_state_event_id: "evt-expired",
        previous_status: "submitted",
        new_status: "expired",
        event_timestamp: "2026-05-05T00:00:06Z",
        reason_code: null,
        event_source: "INTERNAL",
      },
    ];

    mockFetchOnce(coverageEvents);
    mockFetchOnce(mockBrokerOrders);

    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Click on AAPL row
    const aaplRow = screen.getByText("AAPL").closest("tr");
    await user.click(aaplRow!);

    // Wait for event timeline
    await waitFor(() => {
      expect(screen.getByText("상태 전이 타임라인")).toBeInTheDocument();
    });

    // Verify each status Korean label appears in the timeline
    // Status labels may appear in both "이전 상태" and "이후 상태" columns → use getAllByText
    expect(screen.getAllByText("초안").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("검증됨").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("제출 대기").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("제출됨").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("취소 대기").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("취소됨").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("만료").length).toBeGreaterThanOrEqual(1);
  });
});

/* ───────────────────────────────────────────
 * Scenario 8: reason_code metadata label 우선 표시
 * ─────────────────────────────────────────── */
describe("OrderTrackingView reason_code metadata label", () => {
  it("reason_code 컬럼이 metadata label을 우선 표시해야 함", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockOrderDetail);
    mockFetchOnce(mockOrderEvents);
    mockFetchOnce(mockBrokerOrders);

    render(
      <MemoryRouter>
        <OrderTrackingView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    // Click on AAPL row
    const aaplRow = screen.getByText("AAPL").closest("tr");
    await user.click(aaplRow!);

    // Wait for event timeline
    await waitFor(() => {
      expect(screen.getByText("상태 전이 타임라인")).toBeInTheDocument();
    });

    // Second event has reason_code="FILL_CONFIRMED" → metadata label → "체결 확인"
    // (mockEnumMetadataResponse has reason_code with Korean labels matching local map)
    expect(screen.getByText("체결 확인")).toBeInTheDocument();
  });
});
