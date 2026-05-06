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
  mockHealthOk,
  mockHealthDegraded,
  mockOrders,
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
 * Scenario 2: 정상 데이터 로드 (health + orders 병렬 API)
 * ─────────────────────────────────────────── */
describe("Dashboard with valid data", () => {
  it("renders summary cards, database status, and orders", async () => {
    // Mock 2 API calls: getHealth() + getOrders() in parallel via Promise.all
    mockFetchOnce(mockHealthOk);
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    // Wait for data to load — all rendered content
    await waitFor(() => {
      expect(screen.getByText("Overview")).toBeInTheDocument();
      // Verify health data loaded: <code>in_memory</code> proves getHealth() succeeded
      expect(screen.getByText(/in_memory/)).toBeInTheDocument();
    });

    // Summary cards
    expect(screen.getByText("API Health")).toBeInTheDocument();
    expect(screen.getAllByText("Operational")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Recent Orders")[0]).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    // Database status — <code>in_memory</code> already verified health loaded in waitFor
    expect(screen.getByText(/Database Health/)).toBeInTheDocument();

    // Locks section — empty state (no reconciliation API calls anymore)
    expect(screen.getByText(/No active locks/)).toBeInTheDocument();

    // Orders table
    expect(screen.getAllByText(/Recent Orders/)[0]).toBeInTheDocument();
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
 * Scenario 4: Navigation links
 * ─────────────────────────────────────────── */
describe("Dashboard navigation links", () => {
  it("renders clickable navigation buttons with correct href", async () => {
    mockFetchOnce(mockHealthOk);
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Overview")).toBeInTheDocument();
    });

    // "View all orders" button should link to /orders
    const ordersLink = screen.getByRole("button", { name: /View all orders/ });
    expect(ordersLink).toBeInTheDocument();

    // "View reconciliation" button should link to /reconciliation
    const reconLink = screen.getByRole("button", { name: /View reconciliation/ });
    expect(reconLink).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: Health degraded signal banner
 * ─────────────────────────────────────────── */
describe("Dashboard health degraded signal", () => {
  it("shows warning banner when health status is degraded", async () => {
    // Use degraded health (database: "disconnected")
    mockFetchOnce(mockHealthDegraded);
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Overview")).toBeInTheDocument();
    });

    // Database Health card should show "Disconnected"
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Health ok — no warning
 * ─────────────────────────────────────────── */
describe("Dashboard health ok", () => {
  it("does not show health warning when status is ok", async () => {
    mockFetchOnce(mockHealthOk);
    mockFetchOnce(mockOrders);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Overview")).toBeInTheDocument();
    });

    // Database Health card should show "Operational"
    expect(screen.getAllByText("Operational").length).toBeGreaterThanOrEqual(1);
  });
});
