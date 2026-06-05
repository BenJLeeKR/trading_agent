import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import SubmissionAttemptsView from "../components/SubmissionAttemptsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import {
  mockSubmissionAttempts,
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

function renderView() {
  return render(
    <MemoryRouter initialEntries={[`/orders/${ORDER_ID}/submission-attempts`]}>
      <Routes>
        <Route path="/orders/:orderId/submission-attempts" element={<SubmissionAttemptsView />} />
      </Routes>
    </MemoryRouter>,
  );
}

/* ───────────────────────────────────────────
 * Scenario 1: 로딩 상태
 * ─────────────────────────────────────────── */
describe("SubmissionAttemptsView loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    // Do NOT mock fetch — the component will be in loading state
    renderView();
    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 정상 데이터 렌더링
 * ─────────────────────────────────────────── */
describe("SubmissionAttemptsView with data", () => {
  it("renders DataTable with correct rows", async () => {
    const fetchSpy = mockFetchOnce(mockSubmissionAttempts);

    renderView();

    await waitFor(() => {
      expect(screen.getByText("제출 시도 전체 이력")).toBeInTheDocument();
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      `/orders/${ORDER_ID}/submission-attempts`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${VALID_TOKEN}`,
        }),
      }),
    );

    // Column headers
    expect(screen.getByText("시도")).toBeInTheDocument();
    expect(screen.getByText("결과")).toBeInTheDocument();
    expect(screen.getByText("제출 시각")).toBeInTheDocument();
    expect(screen.getByText("Broker")).toBeInTheDocument();
    expect(screen.getByText("Native ID")).toBeInTheDocument();
    expect(screen.getByText("상태")).toBeInTheDocument();
    expect(screen.getByText("응답 코드")).toBeInTheDocument();
    expect(screen.getByText("응답 메시지")).toBeInTheDocument();
    expect(screen.getByText("에러 유형")).toBeInTheDocument();
    expect(screen.getByText("HTTP")).toBeInTheDocument();
    expect(screen.getByText("소요 시간")).toBeInTheDocument();

    // Row data — attempt numbers
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByText("#3")).toBeInTheDocument();

    // Broker name
    const brokerCells = screen.getAllByText("KIS");
    expect(brokerCells.length).toBeGreaterThanOrEqual(3);

    // Native order ID (att-001 only)
    expect(screen.getByText("KIS12345")).toBeInTheDocument();

    // Raw code & message (att-002)
    expect(screen.getByText("2011")).toBeInTheDocument();
    expect(screen.getByText("주문 수량이 1주 미만입니다.")).toBeInTheDocument();

    // Error type (att-003)
    expect(screen.getByText("TIMEOUT")).toBeInTheDocument();

    // Duration
    expect(screen.getByText("145ms")).toBeInTheDocument();
    expect(screen.getByText("98ms")).toBeInTheDocument();
    expect(screen.getByText("30000ms")).toBeInTheDocument();
  });

  it("maps attempt_outcome to correct StatusBadge variant", async () => {
    mockFetchOnce(mockSubmissionAttempts);

    renderView();

    await waitFor(() => {
      expect(screen.getByText("제출 시도 전체 이력")).toBeInTheDocument();
    });

    // outcomeLabel mappings
    expect(screen.getByText("승인")).toBeInTheDocument(); // accepted
    expect(screen.getByText("거부")).toBeInTheDocument(); // rejected
    expect(screen.getByText("예외")).toBeInTheDocument(); // exception
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Back link
 * ─────────────────────────────────────────── */
describe("SubmissionAttemptsView back link", () => {
  it("renders a link back to the order detail page", async () => {
    mockFetchOnce(mockSubmissionAttempts);

    renderView();

    await waitFor(() => {
      expect(screen.getByText("제출 시도 전체 이력")).toBeInTheDocument();
    });

    const backLink = screen.getByRole("link", { name: /주문 상세로 돌아가기/ });
    expect(backLink).toBeInTheDocument();
    expect(backLink).toHaveAttribute(
      "href",
      `/orders/${ORDER_ID}`,
    );
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: API 실패
 * ─────────────────────────────────────────── */
describe("SubmissionAttemptsView API error", () => {
  it("shows ErrorBanner when fetch fails", async () => {
    mockFetchError(500, "Internal server error");

    renderView();

    await waitFor(() => {
      expect(
        screen.getByText(/API error 500/i),
      ).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: 빈 상태
 * ─────────────────────────────────────────── */
describe("SubmissionAttemptsView empty state", () => {
  it("shows '제출 시도 내역이 없습니다.' when data is empty array", async () => {
    mockFetchOnce([]);

    renderView();

    await waitFor(() => {
      expect(
        screen.getByText("제출 시도 내역이 없습니다."),
      ).toBeInTheDocument();
    });
  });
});
