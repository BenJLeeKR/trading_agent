import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import RealtimeQuoteView from "../components/RealtimeQuoteView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import { VALID_TOKEN } from "./test-utils/fixtures";
import type {
  RealtimeQuoteBootstrapResponse,
  RealtimeQuoteSnapshotResponse,
} from "../types/api";

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

const emptyBootstrap: RealtimeQuoteBootstrapResponse = {
  connection: {
    connection_state: "connected",
    environment: "mock",
    data_source: "mock",
    registered_count: 0,
    max_registrations: 41,
    registrations_per_symbol: 2,
    symbol_capacity: 20,
  },
  subscriptions: [],
  generated_at: "2026-07-08T00:00:00Z",
};

const bootstrapWithSubscription: RealtimeQuoteBootstrapResponse = {
  connection: {
    connection_state: "connected",
    environment: "mock",
    data_source: "mock",
    registered_count: 2,
    max_registrations: 41,
    registrations_per_symbol: 2,
    symbol_capacity: 20,
  },
  subscriptions: [{ symbol: "005930", market: "KOSPI", name: "삼성전자" }],
  generated_at: "2026-07-08T00:00:00Z",
};

const snapshotResponse: RealtimeQuoteSnapshotResponse = {
  quotes: {
    "005930": {
      symbol: "005930",
      market: "KOSPI",
      name: "삼성전자",
      last_price: 71900,
      prev_close: 71000,
      change: 900,
      change_rate: 1.27,
      change_sign: "up",
      open_price: 71100,
      high_price: 72000,
      low_price: 70900,
      upper_limit: 92300,
      lower_limit: 49700,
      accumulated_volume: 12345678,
      accumulated_value: 887654321000,
      per: 12.5,
      pbr: 1.1,
      eps: 5432.1,
      bps: 65000,
      ask_levels: Array.from({ length: 10 }, (_, i) => ({ price: 72000 + i * 100, quantity: 100 })),
      bid_levels: Array.from({ length: 10 }, (_, i) => ({ price: 71800 - i * 100, quantity: 90 })),
      total_ask_quantity: 1000,
      total_bid_quantity: 900,
      trade_time: "09:37:30",
      hour_class: "장중",
      trading_halted: false,
      data_source: "mock",
      updated_at: "2026-07-08T00:00:03Z",
    },
  },
  generated_at: "2026-07-08T00:00:03Z",
};

describe("RealtimeQuoteView loading state", () => {
  it("shows a loading spinner on initial render", () => {
    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );
    expect(screen.getByText("실시간 현재가 화면을 불러오는 중...")).toBeInTheDocument();
  });
});

describe("RealtimeQuoteView empty state", () => {
  it("renders the connection/capacity areas with no subscriptions", async () => {
    mockFetchOnce(emptyBootstrap);

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("실시간 현재가")).toBeInTheDocument();
    });

    expect(screen.getByText("MOCK")).toBeInTheDocument();
    expect(screen.getByText("연결됨")).toBeInTheDocument();
    expect(screen.getByText(/0종목 · 0\/41건/)).toBeInTheDocument();
    expect(
      screen.getByText("구독 중인 종목이 없습니다. 종목코드를 입력해 추가하세요.")
    ).toBeInTheDocument();
  });
});

describe("RealtimeQuoteView with a subscribed symbol", () => {
  it("renders the subscription chip, price table row, and detail panel", async () => {
    mockFetchOnce(bootstrapWithSubscription);
    mockFetchOnce(snapshotResponse);

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("1종목 · 2/41건")).toBeInTheDocument();
    });

    // Subscription chip
    expect(screen.getAllByText("삼성전자").length).toBeGreaterThan(0);
    expect(screen.getAllByText("005930").length).toBeGreaterThan(0);

    // Price table row shows the latest snapshot once polled
    await waitFor(() => {
      expect(screen.getByText("71,900")).toBeInTheDocument();
    });
    expect(screen.getByText("09:37:30")).toBeInTheDocument();

    // Detail panel (selected symbol defaults to the first subscription)
    expect(screen.getByText("삼성전자 (005930) 상세")).toBeInTheDocument();
    expect(screen.getByText("PER")).toBeInTheDocument();
  });
});

describe("RealtimeQuoteView bootstrap error", () => {
  it("shows an error banner when bootstrap fails entirely", async () => {
    mockFetchError(503, "Realtime quote source not configured");

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByText("API error 503: Realtime quote source not configured")
      ).toBeInTheDocument();
    });
  });
});
