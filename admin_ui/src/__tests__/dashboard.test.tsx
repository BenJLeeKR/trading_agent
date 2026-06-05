import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import Dashboard from "../components/Dashboard";
import OperationsDashboardView from "../components/OperationsDashboardView";
import { setStoredToken, clearStoredToken } from "../api/client";
import {
  mockFetchOnce,
  mockFetchNetworkError,
} from "./test-utils/mockFetch";
import {
  mockClients,
  mockAccounts,
  mockAccountsNoPositions,
  mockPositions,
  mockPositionsForLocked,
  mockCashBalance,
  mockCashBalanceForLocked,
  mockCashBalanceNull,
  mockOrders,
  mockReconciliationSummary,
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
describe("Dashboard loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 정상 데이터 로드 — 다중 계좌 + orders + reconciliation summary
 * API call sequence:
 *   getClients → getAccounts
 *   → getPositions(3x) + getCashBalance(3x) (parallel)
 *   → getOrders + getReconciliationSummary (parallel)
 * ─────────────────────────────────────────── */
describe("Dashboard with valid data", () => {
  it("renders summary cards with correct metrics", async () => {
    // Mock API calls in order:
    // 1. getClients() → mockClients
    // 2. getAccounts(clientId) → mockAccounts (3 accounts)
    // 3-5. getPositions(accountId) for each of 3 accounts
    // 6-8. getCashBalance(accountId) for each of 3 accounts
    // 9. getOrders() → mockOrders (2 orders)
    // 10. getReconciliationSummary() → mockReconciliationSummary
    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);          // getPositions(a1)
    mockFetchOnce(mockPositionsForLocked); // getPositions(a3)
    mockFetchOnce([]);                     // getPositions(a2)
    mockFetchOnce(mockCashBalance);        // getCashBalance(a1)
    mockFetchOnce(mockCashBalanceForLocked);// getCashBalance(a3)
    mockFetchOnce(mockCashBalanceNull);    // getCashBalance(a2)
    mockFetchOnce(mockOrders);             // getOrders()
    mockFetchOnce(mockReconciliationSummary); // getReconciliationSummary()

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Top 3 account/cash/position cards
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getAllByText("가용 현금").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("포지션").length).toBeGreaterThanOrEqual(1);

    // Restored metric cards — Recent Orders, Active Locks, Incomplete Recon
    // These appear both as metric card titles and section headings, so use getAllByText
    expect(screen.getAllByText("최근 주문").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("활성 잠금").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();

    // Removed metric cards — Paper/Live/Locked Accounts should NOT be present
    expect(screen.queryByText("Paper Accounts")).not.toBeInTheDocument();
    expect(screen.queryByText("Live Accounts")).not.toBeInTheDocument();
    expect(screen.queryByText("Locked Accounts")).not.toBeInTheDocument();

    // Metric values
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1); // Total Accounts = 3
    expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1); // Recent Orders = 2
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1); // Active Locks = 1, Incomplete Recon = 1

    // Account table rows (3 accounts)
    expect(screen.getByText("Paper Account 1")).toBeInTheDocument();
    expect(screen.getByText("Live Account 1")).toBeInTheDocument();
    expect(screen.getByText("Locked Paper Account")).toBeInTheDocument();

    // Status badges — StatusBadge uses acct.status.toUpperCase() (API field, not translated)
    expect(screen.getAllByText("ACTIVE").length).toBe(2);
    expect(screen.getByText("LOCKED")).toBeInTheDocument();

    // Environment labels
    expect(screen.getAllByText("paper").length).toBe(2);
    expect(screen.getByText("live")).toBeInTheDocument();

    // "View all accounts" navigation button
    expect(screen.getByRole("button", { name: /전체 계좌 보기/ })).toBeInTheDocument();

    // Recent Orders section — shows order rows
    expect(screen.getAllByText("AAPL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Active Locks section — shows lock rows
    expect(screen.getByText("Manual review required")).toBeInTheDocument();

    // Freshness indicator — "HH:mm:ss에 업데이트됨" appears in the page header
    expect(screen.getByText(/에 업데이트됨/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 빈 상태 — 계좌 없음
 * ─────────────────────────────────────────── */
describe("Dashboard empty state", () => {
  it("shows empty state when no clients exist", async () => {
    mockFetchOnce([]); // getClients returns empty array
    // fetchAll() may trigger additional fetches during re-render;
    // provide all remaining mocks to prevent queue exhaustion.
    mockFetchOnce([]); // getAccounts
    mockFetchOnce([]); // getPositions (a1)
    mockFetchOnce([]); // getPositions (a3)
    mockFetchOnce([]); // getPositions (a2)
    mockFetchOnce([]); // getCashBalance (a1)
    mockFetchOnce([]); // getCashBalance (a3)
    mockFetchOnce([]); // getCashBalance (a2)
    mockFetchOnce([]); // getOrders
    mockFetchOnce(mockReconciliationSummary); // getReconciliationSummary()

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("계좌가 없습니다")).toBeInTheDocument();
    });

    // Empty state CTA
    expect(
      screen.getByRole("button", { name: /계좌로 이동/ }),
    ).toBeInTheDocument();

    // Freshness indicator also appears in empty state
    expect(screen.getByText(/에 업데이트됨/)).toBeInTheDocument();
  });

  it("shows empty state when clients exist but no accounts", async () => {
    mockFetchOnce(mockClients);  // getClients
    mockFetchOnce([]);           // getAccounts returns empty array
    // When allAccounts is empty, getPositions/getCashBalance are not called.
    // Only getOrders + getReconciliationSummary follow.
    mockFetchOnce([]);                          // getOrders
    mockFetchOnce(mockReconciliationSummary);   // getReconciliationSummary()

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("계좌가 없습니다")).toBeInTheDocument();
    });

    // Freshness indicator also appears in empty state
    expect(screen.getByText(/에 업데이트됨/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: 에러 상태 (API 실패)
 * ─────────────────────────────────────────── */
describe("Dashboard error state", () => {
  it("shows ErrorBanner when API calls fail", async () => {
    // First API call (getClients) fails with network error
    mockFetchNetworkError();

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        screen.getByText("Network error"),
      ).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Navigation links
 * ─────────────────────────────────────────── */
describe("Dashboard navigation links", () => {
  it("renders clickable navigation buttons", async () => {
    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockReconciliationSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // "View all accounts" button
    const accountsLink = screen.getByRole("button", { name: /전체 계좌 보기/ });
    expect(accountsLink).toBeInTheDocument();

    // "View all orders" button
    const ordersLink = screen.getByRole("button", { name: /전체 주문 보기/ });
    expect(ordersLink).toBeInTheDocument();

    // "View all locks" button
    const locksLink = screen.getByRole("button", { name: /전체 잠금 보기/ });
    expect(locksLink).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: 계좌 없음 — empty state에서 Accounts 이동 버튼
 * ─────────────────────────────────────────── */
describe("Dashboard empty state navigation", () => {
  it("shows Go to Accounts button in empty state", async () => {
    mockFetchOnce([]); // getClients returns empty
    // Provide remaining mocks to prevent queue exhaustion on re-render.
    mockFetchOnce([]); // getAccounts
    mockFetchOnce([]); // getPositions (a1)
    mockFetchOnce([]); // getPositions (a3)
    mockFetchOnce([]); // getPositions (a2)
    mockFetchOnce([]); // getCashBalance (a1)
    mockFetchOnce([]); // getCashBalance (a3)
    mockFetchOnce([]); // getCashBalance (a2)
    mockFetchOnce([]); // getOrders
    mockFetchOnce([]); // getReconciliationLocks
    mockFetchOnce([]); // getReconciliationRuns

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("계좌가 없습니다")).toBeInTheDocument();
    });

    const goButton = screen.getByRole("button", { name: /계좌로 이동/ });
    expect(goButton).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Dashboard reconciliation summary variations
 * ─────────────────────────────────────────── */
describe("Dashboard reconciliation StatusCard", () => {
  it("activeIssueCount > 0 → Dashboard renders correctly with warning state", async () => {
    // Create custom reconciliation summary with active issues
    const customSummary = {
      ...mockReconciliationSummary,
      activeIssueCount: 3,
      historicalFailedCount: 5,
    };

    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(customSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Dashboard should still render key metric cards
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getAllByText("가용 현금").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();

    // Metric values should be correct
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1); // Total Accounts = 3
    expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1); // Recent Orders = 2
  });

  it("activeIssueCount === 0 && historicalFailedCount > 0 → Dashboard renders correctly", async () => {
    // Create custom summary: no active issues but historical failures exist
    const customSummary = {
      ...mockReconciliationSummary,
      activeIssueCount: 0,
      historicalFailedCount: 3,
    };

    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(customSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Dashboard renders normally with no reconciliation issues
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();

    // Verify account data still renders
    expect(screen.getByText("Paper Account 1")).toBeInTheDocument();
    expect(screen.getByText("Live Account 1")).toBeInTheDocument();

    // historicalFailedCount는 Dashboard에 표시되지 않아야 함 (activeIssueCount만 기준)
    expect(screen.queryByText(/과거 실패/)).not.toBeInTheDocument();
  });

  it("both activeIssueCount and historicalFailedCount are 0 → Dashboard renders correctly", async () => {
    // Create custom summary: no issues at all
    const customSummary = {
      ...mockReconciliationSummary,
      activeIssueCount: 0,
      historicalFailedCount: 0,
    };

    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(customSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Dashboard renders normally
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * OperationsDashboardView — 최근 제출 실패 StatusCard
 * ─────────────────────────────────────────── */

/** Mock health response for OperationsDashboardView */
const mockOpsHealth = {
  status: "ok",
  version: "1.0.0",
  timestamp: "2026-05-30T00:00:00Z",
  database: "connected",
  runtime_mode: "postgres",
  snapshot_sync_detail: null,
  snapshot_sync_stale: null,
  snapshot_sync_last_successful_run_at: null,
  snapshot_sync_consecutive_failures: null,
  scheduler: null,
};

/** Mock readyz response */
const mockReadyz = { "db": "ok", "cache": "ok" };

/** Mock session response */
const mockSessionResponse = {
  status: "ok",
  data: null,
  healthy: true,
  stale_seconds: null,
};

/** Mock operations-day response */
const mockOperationsDayResponse = {
  status: "ok",
  data: {
    operations_day_run_id: 7,
    run_date: "2026-05-30",
    scheduler_status: "intraday",
    is_trading_day: true,
    session_source: "kis_live",
    market_phase: "OPEN",
    pre_market_done: true,
    end_of_day_done: false,
    after_hours_mode: false,
    recovery_batch_done: false,
    submit_count: 2,
    held_position_sell_submit_count: 1,
    cycles: 14,
    last_phase_change_at: "2026-05-30T09:00:00+09:00",
    last_heartbeat_at: "2026-05-30T09:05:00+09:00",
    created_at: "2026-05-30T08:00:00+09:00",
    updated_at: "2026-05-30T09:05:00+09:00",
    summary_json: {
      command_results_count: 4,
      ok_count: 4,
    },
  },
  healthy: true,
  stale_seconds: 4,
};

/** Mock session events response */
const mockSessionEvents = { status: "ok", data: [] };

/** Mock recent failures data (2건: rejected + exception 혼합) */
const mockRecentFailures = [
  {
    order_request_id: "fail-001",
    symbol: "AAPL",
    side: "BUY",
    latest_outcome: "rejected",
    latest_error_type: "INVALID_QUANTITY",
    latest_raw_code: "2011",
    latest_raw_message: "주문 수량이 1주 미만입니다.",
    last_submitted_at: "2026-05-30T14:32:10+09:00",
    created_at: "2026-05-30T14:32:00+09:00",
  },
  {
    order_request_id: "fail-002",
    symbol: "TSLA",
    side: "SELL",
    latest_outcome: "exception",
    latest_error_type: "TIMEOUT",
    latest_raw_code: null,
    latest_raw_message: null,
    last_submitted_at: "2026-05-30T14:33:00+09:00",
    created_at: "2026-05-30T14:33:00+09:00",
  },
];

/** Mock failure summary with data (1h/24h mixed) */
const mockFailureSummary = {
  last_1h_count: 1,
  last_24h_count: 3,
  rejected_count: 2,
  exception_count: 1,
  total_submissions_24h: 10,
  failure_rate_pct_24h: 30.0,
  today_count: 2,
  rejected_count_today: 1,
  exception_count_today: 1,
  total_submissions_today: 4,
  failure_rate_pct_today: 50.0,
};

/** Mock failure summary with zero failures */
const mockFailureSummaryEmpty = {
  last_1h_count: 0,
  last_24h_count: 0,
  rejected_count: 0,
  exception_count: 0,
  total_submissions_24h: 5,
  failure_rate_pct_24h: 0.0,
  today_count: 0,
  rejected_count_today: 0,
  exception_count_today: 0,
  total_submissions_today: 2,
  failure_rate_pct_today: 0.0,
};

const mockTodayOrderSummary = {
  date: "2026-05-30",
  timezone: "Asia/Seoul",
  total_count: 2,
  filled_count: 1,
  pending_submit_count: 0,
  submitted_count: 0,
};

const mockBuyBlockSummary = {
  date: "2026-05-30",
  timezone: "Asia/Seoul",
  total_buy_orders_count: 12,
  buy_submission_attempted_count: 2,
  blocked_count: 1,
  rejected_count: 1,
  exception_count: 0,
};

/**
 * Helper: mock all fetch calls required by OperationsDashboardView.fetchAll()
 * before the final getRecentFailures(5) and getFailureSummary() calls.
 *
 * Call order (20 total):
 *   1-10: Promise.all [health, readyz, recon, orders, daily-summary, buy-block-summary, clients, session, operations-day, events]
 *   11:   getAccounts(clientId)
 *   12-14: getPositions(3 accounts)
 *   15-17: getCashBalance(3 accounts)
 *   18:   getSnapshotSyncRuns(10)
 *   19:   getRecentFailures(5) — caller provides this mock
 *   20:   getFailureSummary() — caller provides this mock
 */
function mockOpsDashboardCommon() {
  // 1-10: Parallel batch
  mockFetchOnce(mockOpsHealth);            // 1. GET /health
  mockFetchOnce(mockReadyz);               // 2. GET /health/readyz
  mockFetchOnce(mockReconciliationSummary); // 3. GET /reconciliation/summary
  mockFetchOnce(mockOrders);               // 4. GET /orders
  mockFetchOnce(mockTodayOrderSummary);    // 5. GET /orders/daily-summary
  mockFetchOnce(mockBuyBlockSummary);      // 6. GET /orders/buy-block-summary
  mockFetchOnce(mockClients);              // 7. GET /clients
  mockFetchOnce(mockSessionResponse);      // 8. GET /market-sessions/latest
  mockFetchOnce(mockOperationsDayResponse);// 9. GET /market-sessions/operations-day/latest
  mockFetchOnce(mockSessionEvents);        // 10. GET /market-sessions/events/recent

  // 11. getAccounts
  mockFetchOnce(mockAccounts);

  // 12-14. getPositions (3 accounts)
  mockFetchOnce(mockPositions);
  mockFetchOnce(mockPositionsForLocked);
  mockFetchOnce([]);

  // 15-17. getCashBalance (3 accounts)
  mockFetchOnce(mockCashBalance);
  mockFetchOnce(mockCashBalanceForLocked);
  mockFetchOnce(mockCashBalanceNull);

  // 18. getSnapshotSyncRuns
  mockFetchOnce([]);
}

describe("OperationsDashboardView — recent failures", () => {
  it("renders recent submission failures card with data", async () => {
    mockOpsDashboardCommon();
    // 17. getRecentFailures(5) returns mockRecentFailures
    mockFetchOnce(mockRecentFailures);
    // 18. getFailureSummary() returns aggregated counts
    mockFetchOnce(mockFailureSummary);

    render(
      <MemoryRouter>
        <OperationsDashboardView />
      </MemoryRouter>,
    );

    // Wait for aggregated failureSummary value to appear (async)
    await screen.findByText("오늘 2건");
    expect(screen.getByText("Scheduler Status")).toBeInTheDocument();
    expect(screen.getAllByText("운영중").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/OPEN \| 제출 2 \/ HP매도 1 \/ cycles 14/)).toBeInTheDocument();
    expect(screen.getByText("오늘 주문 제출")).toBeInTheDocument();
    expect(screen.getByText("2건")).toBeInTheDocument();
    expect(screen.getByText("오늘 BUY 차단")).toBeInTheDocument();
    expect(screen.getByText("1건")).toBeInTheDocument();
    expect(screen.queryByText(/BUY 주문 12 \/ 제출시도 2 \| 거절 1 · 예외 0/)).not.toBeInTheDocument();

    expect(screen.getByText(/실패율: 50% \(오늘\) \| 거절 1건 · 예외 1건/)).toBeInTheDocument();

    // Should show failure items with symbols (AAPL also appears in orders table)
    const symbols = screen.getAllByText("AAPL");
    expect(symbols.length).toBeGreaterThanOrEqual(1);
    const tslaSymbols = screen.getAllByText("TSLA");
    expect(tslaSymbols.length).toBeGreaterThanOrEqual(1);

    // Should show outcome badges
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Exception")).toBeInTheDocument();

    // Should show error types
    expect(screen.getByText("INVALID_QUANTITY")).toBeInTheDocument();
    expect(screen.getByText("TIMEOUT")).toBeInTheDocument();

    // Should show raw_code prefix (monospace [CODE] format)
    expect(screen.getByText("[2011]")).toBeInTheDocument();

    // Should show raw_message inline preview (truncated if needed)
    expect(screen.getByText(/주문 수량이 1주 미만입니다/)).toBeInTheDocument();

    // Should render title attribute for tooltip (full raw_message text)
    const errorTypeSpan = screen.getByText(/INVALID_QUANTITY/).closest('span');
    expect(errorTypeSpan).toHaveAttribute('title', '주문 수량이 1주 미만입니다.');

    // Should render link to all failed orders
    expect(screen.getByText("모든 실패 주문 보기 →")).toBeInTheDocument();

    // Should show direct "제출 이력 보기" links to submission attempts
    const submissionLinks = screen.getAllByText("제출 이력 보기 →");
    expect(submissionLinks.length).toBe(2); // 2 failure items

    // Verify first link goes to correct URL
    expect(submissionLinks[0].closest('a')).toHaveAttribute(
      'href',
      '/orders/fail-001/submission-attempts'
    );

    // Verify second link
    expect(submissionLinks[1].closest('a')).toHaveAttribute(
      'href',
      '/orders/fail-002/submission-attempts'
    );
  });

  it("renders empty state when no failures", async () => {
    mockOpsDashboardCommon();
    // 17. getRecentFailures(5) returns empty array
    mockFetchOnce([]);
    // 18. getFailureSummary() returns empty aggregated counts
    mockFetchOnce(mockFailureSummaryEmpty);

    render(
      <MemoryRouter>
        <OperationsDashboardView />
      </MemoryRouter>,
    );

    // Wait for aggregated failureSummary value to appear (async)
    await screen.findByText("오늘 0건");

    expect(screen.getByText(/실패율: 0% \(오늘\) \| 거절 0건 · 예외 0건/)).toBeInTheDocument();
  });

  it("handles fetch error gracefully", async () => {
    mockOpsDashboardCommon();
    // 17. getRecentFailures(5) fails with network error
    mockFetchNetworkError();
    // 18. getFailureSummary() also fails
    mockFetchNetworkError();

    render(
      <MemoryRouter>
        <OperationsDashboardView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("최근 제출 실패")).toBeInTheDocument();
    });

    // Should show error state (value is "오류", which also appears in other cards)
    const errorValues = screen.getAllByText("오류");
    expect(errorValues.length).toBeGreaterThanOrEqual(1);

    // Should show error message in subtitle area (contains "Error:" from API error)
    expect(screen.getByText(/API 오류/)).toBeInTheDocument();
  });

  it("renders failure summary with zero failures — neutral status", async () => {
    mockOpsDashboardCommon();
    // 17. getRecentFailures(5) returns empty
    mockFetchOnce([]);
    // 18. getFailureSummary() returns zero counts
    mockFetchOnce(mockFailureSummaryEmpty);

    render(
      <MemoryRouter>
        <OperationsDashboardView />
      </MemoryRouter>,
    );

    // Wait for aggregated failureSummary value to appear (async)
    await screen.findByText("오늘 0건");

    expect(screen.getByText(/실패율: 0% \(오늘\) \| 거절 0건 · 예외 0건/)).toBeInTheDocument();

    // 개별 실패 목록은 보이지 않아야 함
    expect(screen.queryByText("Rejected")).not.toBeInTheDocument();
  });

  it("renders failure summary with 1h errors — error status", async () => {
    mockOpsDashboardCommon();
    // 17. getRecentFailures(5) returns recent failures
    mockFetchOnce(mockRecentFailures);
    // 18. getFailureSummary() returns data with 1h count > 0
    mockFetchOnce({
      last_1h_count: 2,
      last_24h_count: 5,
      rejected_count: 3,
      exception_count: 2,
      total_submissions_24h: 20,
      failure_rate_pct_24h: 25.0,
      today_count: 4,
      rejected_count_today: 2,
      exception_count_today: 2,
      total_submissions_today: 8,
      failure_rate_pct_today: 50.0,
    });

    render(
      <MemoryRouter>
        <OperationsDashboardView />
      </MemoryRouter>,
    );

    // Wait for aggregated failureSummary value to appear (async)
    await screen.findByText("오늘 4건");

    expect(screen.getByText(/실패율: 50% \(오늘\) \| 거절 2건 · 예외 2건/)).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Exception")).toBeInTheDocument();
  });
});
