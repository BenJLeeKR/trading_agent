import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import ReconciliationView from "../components/ReconciliationView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import {
  mockOrders,
  mockAccounts,
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
 * Scenario 1: 로딩 상태
 * ─────────────────────────────────────────── */
describe("ReconciliationView loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    render(<ReconciliationView />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: Runs 탭 렌더
 * ─────────────────────────────────────────── */
describe("ReconciliationView runs tab", () => {
  it("renders reconciliation runs table with status badge", async () => {
    // GET /orders → GET /accounts?client_id=... → GET /reconciliation/runs + /reconciliation/locks
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    // Runs tab is active by default
    expect(screen.getByText("Started")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Completed" })).toBeInTheDocument();
    expect(screen.getByText("Order Mismatches")).toBeInTheDocument();
    expect(screen.getByText("Position Mismatches")).toBeInTheDocument();

    // Run data — "0" appears in both order_mismatches and position_mismatches cells
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("completed")).toBeInTheDocument(); // StatusBadge text

    // Status filter dropdown should be visible
    expect(
      screen.getByRole("combobox", { name: /filter runs by status/i }),
    ).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Runs 탭 — status filter
 * ─────────────────────────────────────────── */
describe("ReconciliationView run status filter", () => {
  it("filters runs when status is selected", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    // Initially "completed" run is visible
    expect(screen.getByText("completed")).toBeInTheDocument();

    // Change filter to "running"
    const filterSelect = screen.getByRole("combobox", { name: /filter runs by status/i });
    await user.selectOptions(filterSelect, "running");

    // "completed" row should be hidden
    expect(screen.queryByText("completed")).not.toBeInTheDocument();
    // No runs data — empty message should show (runs still exist but filtered to empty)
    // DataTable shows emptyMessage when filtered data is empty
    expect(screen.getByText("No reconciliation runs found.")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Locks 탭 전환
 * ─────────────────────────────────────────── */
describe("ReconciliationView locks tab", () => {
  it("switches to locks tab and renders lock columns", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    // Click Locks tab
    await user.click(screen.getByRole("tab", { name: /locks/i }));

    // Lock columns
    expect(screen.getByText("Symbol")).toBeInTheDocument();
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Strategy")).toBeInTheDocument();
    expect(screen.getByText("Acquired")).toBeInTheDocument();
    expect(screen.getByText("Expires")).toBeInTheDocument();

    // Lock data
    expect(screen.getByText("manual")).toBeInTheDocument();
    expect(screen.getByText("strat-a")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Active lock 경고 표시 (강화된 스타일)
 * ─────────────────────────────────────────── */
describe("ReconciliationView active lock warning", () => {
  it("shows enhanced warning banner when active (non-expired) locks exist", async () => {
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    // mockLocks has is_expired: false → active
    mockFetchOnce(mockLocks);

    render(<ReconciliationView />);

    // Switch to locks tab to see the warning
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: /locks/i }));

    // Warning banner should be visible with enhanced text
    await waitFor(() => {
      expect(
        screen.getByText(/Active Blocking Lock/i),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/may block trading operations/i),
    ).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: Empty locks → 경고 없음, empty message
 * ─────────────────────────────────────────── */
describe("ReconciliationView empty locks", () => {
  it("shows no warning and empty message when locks list is empty", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    // Empty locks
    mockFetchOnce([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: /locks/i }));

    // No warning banner
    expect(
      screen.queryByText(/Active Blocking Lock/i),
    ).not.toBeInTheDocument();

    // Empty message from DataTable
    expect(
      screen.getByText("No blocking locks found."),
    ).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: API 실패
 * ─────────────────────────────────────────── */
describe("ReconciliationView error state", () => {
  it("shows ErrorBanner when API calls fail", async () => {
    mockFetchError(500, "Database error");

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(
        screen.getByText(/Database error/i),
      ).toBeInTheDocument();
    });
  });
});
