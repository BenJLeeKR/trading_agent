import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import Dashboard from "../components/Dashboard";
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

    expect(screen.getByText("Loading...")).toBeInTheDocument();
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
      expect(screen.getByText("Overview")).toBeInTheDocument();
    });

    // Top 3 account/cash/position cards
    expect(screen.getByText("Total Accounts")).toBeInTheDocument();
    expect(screen.getAllByText("Available Cash").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Positions").length).toBeGreaterThanOrEqual(1);

    // Restored metric cards — Recent Orders, Active Locks, Incomplete Recon
    // These appear both as metric card titles and section headings, so use getAllByText
    expect(screen.getAllByText("Recent Orders").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Active Locks").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Incomplete Recon")).toBeInTheDocument();

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

    // Status badges
    expect(screen.getAllByText("ACTIVE").length).toBe(2);
    expect(screen.getByText("LOCKED")).toBeInTheDocument();

    // Environment labels
    expect(screen.getAllByText("paper").length).toBe(2);
    expect(screen.getByText("live")).toBeInTheDocument();

    // "View all accounts" navigation button
    expect(screen.getByRole("button", { name: /View all accounts/ })).toBeInTheDocument();

    // Recent Orders section — shows order rows
    expect(screen.getAllByText("AAPL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Active Locks section — shows lock rows
    expect(screen.getByText("manual-review-account-a1")).toBeInTheDocument();
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
      expect(screen.getByText("No accounts found")).toBeInTheDocument();
    });

    // Empty state CTA
    expect(
      screen.getByRole("button", { name: /Go to Accounts/ }),
    ).toBeInTheDocument();
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
      expect(screen.getByText("No accounts found")).toBeInTheDocument();
    });
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
        screen.getByText(/Network error/i),
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
      expect(screen.getByText("Overview")).toBeInTheDocument();
    });

    // "View all accounts" button
    const accountsLink = screen.getByRole("button", { name: /View all accounts/ });
    expect(accountsLink).toBeInTheDocument();

    // "View all orders" button
    const ordersLink = screen.getByRole("button", { name: /View all orders/ });
    expect(ordersLink).toBeInTheDocument();

    // "View all locks" button
    const locksLink = screen.getByRole("button", { name: /View all locks/ });
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
      expect(screen.getByText("No accounts found")).toBeInTheDocument();
    });

    const goButton = screen.getByRole("button", { name: /Go to Accounts/ });
    expect(goButton).toBeInTheDocument();
  });
});
