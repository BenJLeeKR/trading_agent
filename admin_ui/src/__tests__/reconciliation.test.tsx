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
 * Scenario 2: Runs 테이블 렌더 (side-by-side layout)
 * ─────────────────────────────────────────── */
describe("ReconciliationView runs table", () => {
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

    // Template columns: Run ID, Date, Time, Status, Order Mismatches, Position Mismatches
    expect(screen.getByRole("columnheader", { name: "Run ID" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Date" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Time" })).toBeInTheDocument();
    expect(screen.getByText("Order Mismatches")).toBeInTheDocument();
    expect(screen.getByText("Position Mismatches")).toBeInTheDocument();

    // Run data — "0" appears in both order_mismatches and position_mismatches cells
    expect(screen.getAllByText("0").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("completed")).toBeInTheDocument(); // StatusBadge text

    // Status filter group should be visible with buttons
    expect(screen.getByRole("button", { name: /^All$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Completed$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Running$/i })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Runs 탭 — status filter (button group)
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

    // Click "Running" status button
    const runningBtn = screen.getByRole("button", { name: /^Running$/i });
    await user.click(runningBtn);

    // "completed" row should be hidden
    expect(screen.queryByText("completed")).not.toBeInTheDocument();
    // No runs data — empty message should show (runs still exist but filtered to empty)
    // DataTable shows emptyMessage when filtered data is empty
    expect(screen.getByText("No reconciliation runs found.")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Lock 카드 표시 (side-by-side layout)
 * ─────────────────────────────────────────── */
describe("ReconciliationView lock cards", () => {
  it("renders lock cards in the right sidebar", async () => {
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    // Blocking Locks panel header should be visible
    expect(screen.getByText("Blocking Locks")).toBeInTheDocument();

    // Lock data rendered as cards (combined lock_type — strategy_code text)
    expect(screen.getByText(/manual.*strat-a/)).toBeInTheDocument();

    // Active count badge (multiple elements may contain "active" text)
    expect(screen.getAllByText(/active/).length).toBeGreaterThanOrEqual(1);
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Active lock 경고 표시 (side-by-side layout)
 * ─────────────────────────────────────────── */
describe("ReconciliationView active lock warning", () => {
  it("shows enhanced warning banner when active (non-expired) locks exist", async () => {
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    mockFetchOnce(mockLocks);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    // Warning banner should be visible (no tab switch needed — always visible)
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
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockReconciliationRuns);
    // Empty locks
    mockFetchOnce([]);

    render(<ReconciliationView />);

    await waitFor(() => {
      expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    });

    // No warning banner
    expect(
      screen.queryByText(/Active Blocking Lock/i),
    ).not.toBeInTheDocument();

    // Empty message from card panel
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
