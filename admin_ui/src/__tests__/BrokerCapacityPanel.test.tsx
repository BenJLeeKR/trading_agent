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
      expect(screen.getByText("브로커 용량")).toBeInTheDocument();
    });

    // Header info
    expect(screen.getByText("koreainvestment")).toBeInTheDocument();
    expect(screen.getByText("paper")).toBeInTheDocument();

    // can_accept_new_entries = true → "허용" badge
    expect(screen.getByText("허용")).toBeInTheDocument();

    // REST Budget section
    expect(screen.getByText("REST 예산")).toBeInTheDocument();
    expect(screen.getByText("인증")).toBeInTheDocument();
    expect(screen.getByText("주문")).toBeInTheDocument();
    expect(screen.getByText("조회")).toBeInTheDocument();
    expect(screen.getByText("정합성 점검")).toBeInTheDocument();
    expect(screen.getByText("시장 데이터")).toBeInTheDocument();

    // REST budget values — "5/8 (38%)" etc. (0.375 → 38%)
    expect(screen.getByText("5/8 (38%)")).toBeInTheDocument();
    expect(screen.getByText("15/20 (25%)")).toBeInTheDocument();

    // WebSocket section
    expect(screen.getByText("웹소켓")).toBeInTheDocument();
    expect(screen.getByText("연결됨")).toBeInTheDocument(); // ws_connected badge
    expect(screen.getByText("7 / 50")).toBeInTheDocument(); // total_used / max_subscriptions
    expect(screen.getByText("43")).toBeInTheDocument(); // remaining
    expect(screen.getByText("5 / 40")).toBeInTheDocument(); // current_critical / critical_limit
    expect(screen.getByText("2 / 10")).toBeInTheDocument(); // current_optional / optional_limit

    // Market data subs + order event accounts
    expect(screen.getByText("3")).toBeInTheDocument(); // market_data_subscriptions
    expect(screen.getByText("1")).toBeInTheDocument(); // order_event_accounts.length

    // Freshness indicator — "스냅샷 HH:mm:ss" appears in the summary row
    expect(screen.getByText(/스냅샷/)).toBeInTheDocument();
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
      expect(screen.getByText("차단")).toBeInTheDocument();
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
        screen.getByText("이 런타임에서는 용량 정보를 사용할 수 없습니다"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText("브로커 어댑터가 설정되지 않았습니다"),
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
        screen.getByText("Network error"),
      ).toBeInTheDocument();
    });
  });
});
