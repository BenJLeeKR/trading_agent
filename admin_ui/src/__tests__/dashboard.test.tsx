import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import Dashboard from "../components/Dashboard";
import { setStoredToken, clearStoredToken } from "../api/client";
import {
  mockFetchOnce,
  mockFetchNetworkError,
} from "./test-utils/mockFetch";
import {
  mockAccounts,
  mockHealthOk,
  mockHealthDegraded,
  mockOrders,
  mockReconciliationRuns,
  mockLocks,
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
 * Scenario 2: 정상 데이터 로드 (4개 병렬 API)
 * ─────────────────────────────────────────── */
describe("Dashboard with valid data", () => {
  it("renders summary cards, database status, locks, and orders", async () => {
    // Mock 5 API calls: orders → accounts → health → reconRuns → locks
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockHealthOk);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    // Wait for data to load — all rendered content
    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeInTheDocument();
      // Verify health data loaded: <code>in_memory</code> proves getHealth() succeeded
      expect(screen.getAllByText("in_memory")[0]).toBeInTheDocument();
    });

    // Summary cards
    expect(screen.getByText("Server Status")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("Total Orders")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    // Database status — <code>in_memory</code> already verified health loaded in waitFor
    expect(screen.getByText(/Database/)).toBeInTheDocument();

    // Locks table
    expect(screen.getAllByText("Active Locks")[0]).toBeInTheDocument();

    // Orders table
    expect(screen.getByText(/Recent Orders/)).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // AAPL appears in the Recent Orders table
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 에러 상태 (API 실패)
 * ─────────────────────────────────────────── */
describe("Dashboard error state", () => {
  it("shows ErrorBanner when API calls fail", async () => {
    // First API call (getOrders) fails with network error
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
 * Scenario 4: Summary Card navigation links
 * ─────────────────────────────────────────── */
describe("Dashboard navigation links", () => {
  it("renders clickable summary cards with correct href", async () => {
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockHealthOk);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeInTheDocument();
    });

    // "Total Orders" card should link to /orders
    const ordersLink = screen.getByRole("link", { name: /2.*Total Orders/ });
    expect(ordersLink).toBeInTheDocument();
    expect(ordersLink).toHaveAttribute("href", "/orders");

    // There are active locks (mockLocks has is_expired: false)
    // So "Active Locks" card should link to /reconciliation
    const locksLink = screen.getByRole("link", { name: /1.*Active Locks/ });
    expect(locksLink).toBeInTheDocument();
    expect(locksLink).toHaveAttribute("href", "/reconciliation");

    // "Incomplete Runs" — mockReconciliationRuns has status "completed", so no incomplete runs
    // Check that Incomplete Runs card exists (value 0) but should NOT have a link
    const incompleteRunsLink = screen.queryByRole("link", { name: /0.*Incomplete Runs/ });
    expect(incompleteRunsLink).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: Health degraded signal banner
 * ─────────────────────────────────────────── */
describe("Dashboard health degraded signal", () => {
  it("shows warning banner when health status is degraded", async () => {
    // Use degraded health (database: "disconnected")
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockHealthDegraded);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeInTheDocument();
    });

    // Warning banner should be visible
    expect(screen.getByText(/System Status: DEGRADED/i)).toBeInTheDocument();
    expect(screen.getByText(/Disconnected — Some features may be unavailable/i)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Health ok — no warning banner
 * ─────────────────────────────────────────── */
describe("Dashboard health ok", () => {
  it("does not show health warning when status is ok", async () => {
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockHealthOk);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeInTheDocument();
    });

    // No degraded warning banner
    expect(
      screen.queryByText(/System Status: [A-Z]/i),
    ).not.toBeInTheDocument();
  });
});
