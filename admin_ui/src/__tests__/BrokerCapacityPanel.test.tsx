import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import BrokerCapacityPanel from "../components/BrokerCapacityPanel";
import { setStoredToken, clearStoredToken } from "../api/client";
import {
  mockFetchOnce,
  mockFetchError,
  mockFetchNetworkError,
} from "./test-utils/mockFetch";
import {
  mockBrokerCapacity,
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
 * Scenario 1: 정상 데이터 로드
 * ─────────────────────────────────────────── */
describe("BrokerCapacityPanel with valid data", () => {
  it("renders broker name, environment, and key metrics", async () => {
    mockFetchOnce(mockBrokerCapacity);

    render(<BrokerCapacityPanel />);

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText("Broker Capacity")).toBeInTheDocument();
    });

    // Header info
    expect(screen.getByText("koreainvestment")).toBeInTheDocument();
    expect(screen.getByText("paper")).toBeInTheDocument();

    // can_accept_new_entries = true → "YES" badge
    expect(screen.getByText("YES")).toBeInTheDocument();

    // REST Budget section
    expect(screen.getByText("REST Budget")).toBeInTheDocument();
    expect(screen.getByText("Auth")).toBeInTheDocument();
    expect(screen.getByText("Order")).toBeInTheDocument();
    expect(screen.getByText("Inquiry")).toBeInTheDocument();
    expect(screen.getByText("Reconciliation")).toBeInTheDocument();
    expect(screen.getByText("Market Data")).toBeInTheDocument();

    // REST budget values — "5/8 (38%)" etc. (0.375 → 38%)
    expect(screen.getByText("5/8 (38%)")).toBeInTheDocument();
    expect(screen.getByText("15/20 (25%)")).toBeInTheDocument();

    // WebSocket section
    expect(screen.getByText("WebSocket")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument(); // ws_connected badge
    expect(screen.getByText("7 / 50")).toBeInTheDocument(); // total_used / max_subscriptions
    expect(screen.getByText("43")).toBeInTheDocument(); // remaining
    expect(screen.getByText("5 / 40")).toBeInTheDocument(); // current_critical / critical_limit
    expect(screen.getByText("2 / 10")).toBeInTheDocument(); // current_optional / optional_limit

    // Market data subs + order event accounts
    expect(screen.getByText("3")).toBeInTheDocument(); // market_data_subscriptions
    expect(screen.getByText("1")).toBeInTheDocument(); // order_event_accounts.length
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: can_accept_new_entries = false
 * ─────────────────────────────────────────── */
describe("BrokerCapacityPanel warning state", () => {
  it("shows NO badge when can_accept_new_entries is false", async () => {
    const exhausted = {
      ...mockBrokerCapacity,
      can_accept_new_entries: false,
    };
    mockFetchOnce(exhausted);

    render(<BrokerCapacityPanel />);

    await waitFor(() => {
      expect(screen.getByText("NO")).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 503 — Broker adapter not configured
 * ─────────────────────────────────────────── */
describe("BrokerCapacityPanel 503 state", () => {
  it("shows unavailable message when broker adapter is not configured", async () => {
    // Simulate 503 response — backend returns 503 with detail
    mockFetchError(503, "Broker adapter not configured");

    render(<BrokerCapacityPanel />);

    await waitFor(() => {
      expect(
        screen.getByText("Capacity information unavailable in this runtime"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText("Broker adapter not configured"),
    ).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: 네트워크 에러
 * ─────────────────────────────────────────── */
describe("BrokerCapacityPanel network error", () => {
  it("shows error banner on network failure", async () => {
    mockFetchNetworkError();

    render(<BrokerCapacityPanel />);

    await waitFor(() => {
      expect(
        screen.getByText(/Network error/i),
      ).toBeInTheDocument();
    });
  });
});
