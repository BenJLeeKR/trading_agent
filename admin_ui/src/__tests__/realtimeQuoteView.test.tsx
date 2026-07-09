import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import RealtimeQuoteView from "../components/RealtimeQuoteView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import { VALID_TOKEN } from "./test-utils/fixtures";
import type {
  RealtimeQuoteBootstrapResponse,
  RealtimeQuoteLevel,
  RealtimeQuoteSnapshotResponse,
  RealtimeQuoteSubscriptionsResponse,
} from "../types/api";

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

/* ── fixtures ── */

const emptyBootstrap: RealtimeQuoteBootstrapResponse = {
  connection: {
    connection_state: "connected",
    environment: "mock",
    data_source: "mock",
    registered_count: 0,
    max_registrations: 30,
    registrations_per_symbol: 2,
    symbol_capacity: 15,
  },
  subscriptions: [],
  generated_at: "2026-07-08T00:00:00Z",
};

function bootstrapWith(symbol: string, name: string, market: string): RealtimeQuoteBootstrapResponse {
  return {
    connection: {
      connection_state: "connected",
      environment: "mock",
      data_source: "mock",
      registered_count: 2,
      max_registrations: 30,
      registrations_per_symbol: 2,
      symbol_capacity: 15,
    },
    subscriptions: [{ symbol, name, market }],
    generated_at: "2026-07-08T00:00:00Z",
  };
}

function askLevels(): RealtimeQuoteLevel[] {
  return Array.from({ length: 10 }, (_, i) => ({ price: 72000 + i * 100, quantity: 100 * (i + 1) }));
}
function bidLevels(): RealtimeQuoteLevel[] {
  return Array.from({ length: 10 }, (_, i) => ({ price: 71800 - i * 100, quantity: 90 * (i + 1) }));
}

function snapshotFor(symbol: string, name: string, market: string): RealtimeQuoteSnapshotResponse {
  return {
    quotes: {
      [symbol]: {
        symbol,
        market,
        name,
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
        ask_levels: askLevels(),
        bid_levels: bidLevels(),
        total_ask_quantity: 5500,
        total_bid_quantity: 4950,
        trade_time: "09:37:30",
        hour_class: "장중",
        trading_halted: false,
        data_source: "mock",
        updated_at: "2026-07-08T00:00:03Z",
        recent_trades: [
          { trade_time: "09:37:30", price: 71900, change: 900, change_rate: 1.27, volume: 10 },
        ],
      },
    },
    generated_at: "2026-07-08T00:00:03Z",
  };
}

/** Snapshot response where the requested symbol has no data yet (subscribed, no tick received). */
function emptySnapshot(): RealtimeQuoteSnapshotResponse {
  return { quotes: {}, generated_at: "2026-07-08T00:00:00Z" };
}

function subscriptionsResponse(
  symbols: { symbol: string; name: string; market: string }[]
): RealtimeQuoteSubscriptionsResponse {
  return {
    connection: {
      connection_state: "connected",
      environment: "mock",
      data_source: "mock",
      registered_count: symbols.length * 2,
      max_registrations: 30,
      registrations_per_symbol: 2,
      symbol_capacity: 15,
    },
    subscriptions: symbols,
    generated_at: "2026-07-08T00:00:00Z",
  };
}

function bootstrapWithMany(
  symbols: { symbol: string; name: string; market: string }[]
): RealtimeQuoteBootstrapResponse {
  return { ...subscriptionsResponse(symbols) };
}

/** Renders the current URL's search string into the DOM so tests can assert on it. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

/* ── tests ── */

describe("RealtimeQuoteView keeps the detail frame while data is pending", () => {
  it("shows the 호가/상세정보 frames with a waiting state when subscribed but quote is null", async () => {
    mockFetchOnce(bootstrapWith("005930", "삼성전자", "KOSPI"));
    mockFetchOnce(emptySnapshot());

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    // The symbol is selected and subscribed — the frame must render even
    // though no snapshot data has arrived yet (must NOT fall through to the
    // "종목을 선택하거나..." empty state).
    await waitFor(() => {
      expect(screen.getAllByText("삼성전자").length).toBeGreaterThan(0);
    });
    expect(
      screen.queryByText("조회할 종목을 선택하거나 종목코드를 입력하세요.")
    ).not.toBeInTheDocument();

    expect(screen.getByText("호가")).toBeInTheDocument();
    expect(screen.getByText("종목 상세정보")).toBeInTheDocument();
    // Grid structure stays intact — values render as "—" placeholders,
    // not a text blob replacing the whole panel.
    expect(screen.getAllByText("수신 대기 중").length).toBeGreaterThan(0); // header badges
    expect(screen.getByText("잔량합계")).toBeInTheDocument(); // ladder totals row still renders
    expect(screen.getByText("시간구분")).toBeInTheDocument(); // detail field grid still renders
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("keeps the frame on ?symbol= deep-link entry before any snapshot arrives", async () => {
    mockFetchOnce(bootstrapWith("138040", "메리츠금융지주", "KOSPI"));
    mockFetchOnce(emptySnapshot());

    render(
      <MemoryRouter initialEntries={["/operations/realtime-quotes?symbol=138040"]}>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("138040").length).toBeGreaterThan(0);
    });
    expect(
      screen.queryByText("조회할 종목을 선택하거나 종목코드를 입력하세요.")
    ).not.toBeInTheDocument();
    expect(screen.getByText("호가")).toBeInTheDocument();
    expect(screen.getByText("종목 상세정보")).toBeInTheDocument();
  });
});

describe("RealtimeQuoteView deep link (?symbol=)", () => {
  it("auto-selects an already-subscribed symbol from the query param", async () => {
    mockFetchOnce(bootstrapWith("138040", "메리츠금융지주", "KOSPI"));
    mockFetchOnce(snapshotFor("138040", "메리츠금융지주", "KOSPI"));

    render(
      <MemoryRouter initialEntries={["/operations/realtime-quotes?symbol=138040"]}>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("메리츠금융지주").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("138040").length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });
  });
});

describe("RealtimeQuoteView symbol code validation", () => {
  it("blocks non-6-digit symbol codes on the client", async () => {
    mockFetchOnce(emptyBootstrap);
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("실시간 현재가")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText("종목코드 6자리 (예: 005930)");
    await user.type(input, "12A45");
    await user.click(screen.getByText("종목 추가"));

    expect(
      screen.getByText("종목코드는 6자리 숫자로 입력하세요 (예: 005930)")
    ).toBeInTheDocument();
  });
});

describe("RealtimeQuoteView subscribe flow", () => {
  it("subscribing a new symbol adds a chip and renders the main view", async () => {
    mockFetchOnce(emptyBootstrap);
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByText("구독 중인 종목이 없습니다. 종목코드를 입력해 조회를 시작하세요.")
      ).toBeInTheDocument();
    });

    mockFetchOnce(subscriptionsResponse([{ symbol: "005930", name: "삼성전자", market: "KOSPI" }]));
    mockFetchOnce(snapshotFor("005930", "삼성전자", "KOSPI"));

    const input = screen.getByPlaceholderText("종목코드 6자리 (예: 005930)");
    await user.type(input, "005930");
    await user.click(screen.getByText("종목 추가"));

    await waitFor(() => {
      expect(screen.getAllByText("삼성전자").length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });
  });

  it("re-adding an already-subscribed symbol does not call the API again", async () => {
    mockFetchOnce(bootstrapWith("005930", "삼성전자", "KOSPI"));
    mockFetchOnce(snapshotFor("005930", "삼성전자", "KOSPI"));
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const callCountBefore = fetchSpy.mock.calls.length;

    const input = screen.getByPlaceholderText("종목코드 6자리 (예: 005930)");
    await user.type(input, "005930");
    await user.click(screen.getByText("종목 추가"));

    // No new network call for a duplicate subscribe — purely client-side switch.
    expect(fetchSpy.mock.calls.length).toBe(callCountBefore);
  });
});

describe("RealtimeQuoteView unsubscribe flow", () => {
  it("removing the active symbol clears the chip and main view", async () => {
    mockFetchOnce(bootstrapWith("005930", "삼성전자", "KOSPI"));
    mockFetchOnce(snapshotFor("005930", "삼성전자", "KOSPI"));
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });

    mockFetchOnce(subscriptionsResponse([]));
    await user.click(screen.getByLabelText("005930 구독 해제"));

    await waitFor(() => {
      expect(
        screen.getByText("조회할 종목을 선택하거나 종목코드를 입력하세요.")
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("71,900")).not.toBeInTheDocument();
  });
});

describe("RealtimeQuoteView snapshot rendering", () => {
  it("renders the 10-level ladder and detail panel fields from the snapshot", async () => {
    mockFetchOnce(bootstrapWith("138040", "메리츠금융지주", "KOSPI"));
    mockFetchOnce(snapshotFor("138040", "메리츠금융지주", "KOSPI"));

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });

    // Ladder: best ask (72,000, also equals high_price) and best bid (71,800).
    expect(screen.getAllByText("72,000").length).toBeGreaterThan(0);
    expect(screen.getByText("71,800")).toBeInTheDocument();
    expect(screen.getByText("잔량합계")).toBeInTheDocument();

    // Detail panel fields
    expect(screen.getByText("시간구분")).toBeInTheDocument();
    expect(screen.getByText("장중")).toBeInTheDocument();
    expect(screen.getByText("거래정지 여부")).toBeInTheDocument();
    expect(screen.getByText("정상거래")).toBeInTheDocument();
    expect(screen.getByText("PER")).toBeInTheDocument();
    expect(screen.getByText("12.50")).toBeInTheDocument();
  });
});

describe("RealtimeQuoteView connection/degraded states", () => {
  it("shows a reconnecting banner when connection_state is reconnecting", async () => {
    const reconnecting = bootstrapWith("005930", "삼성전자", "KOSPI");
    reconnecting.connection.connection_state = "reconnecting";
    mockFetchOnce(reconnecting);
    mockFetchOnce(snapshotFor("005930", "삼성전자", "KOSPI"));

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("WebSocket 재연결 시도 중")).toBeInTheDocument();
    });
    expect(screen.getByText("재연결 중")).toBeInTheDocument();
  });

  it("shows a degraded banner when the snapshot poll fails but keeps the screen alive", async () => {
    mockFetchOnce(bootstrapWith("005930", "삼성전자", "KOSPI"));
    mockFetchError(500, "snapshot unavailable");

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("시세 갱신 중 오류가 발생했습니다")).toBeInTheDocument();
    });
    // The screen stays alive — symbol chip/header still rendered, not blanked.
    expect(screen.getAllByText("삼성전자").length).toBeGreaterThan(0);
  });

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

describe("RealtimeQuoteView URL (?symbol=) sync", () => {
  it("clears the symbol query param after unsubscribing the last symbol", async () => {
    mockFetchOnce(bootstrapWith("005930", "삼성전자", "KOSPI"));
    mockFetchOnce(snapshotFor("005930", "삼성전자", "KOSPI"));
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/operations/realtime-quotes?symbol=005930&foo=bar"]}>
        <RealtimeQuoteView />
        <LocationProbe />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId("location-search").textContent).toContain("symbol=005930");

    mockFetchOnce(subscriptionsResponse([]));
    await user.click(screen.getByLabelText("005930 구독 해제"));

    await waitFor(() => {
      expect(screen.getByTestId("location-search").textContent).not.toContain("symbol");
    });
    // Unrelated query params must survive the symbol cleanup.
    expect(screen.getByTestId("location-search").textContent).toContain("foo=bar");
  });

  it("updates the symbol query param when the selected symbol changes", async () => {
    mockFetchOnce(
      bootstrapWithMany([
        { symbol: "005930", name: "삼성전자", market: "KOSPI" },
        { symbol: "000660", name: "SK하이닉스", market: "KOSPI" },
      ])
    );
    mockFetchOnce(snapshotFor("005930", "삼성전자", "KOSPI"));
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <RealtimeQuoteView />
        <LocationProbe />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("location-search").textContent).toContain("symbol=005930");
    });

    mockFetchOnce(snapshotFor("000660", "SK하이닉스", "KOSPI"));
    await user.click(screen.getByText("SK하이닉스"));

    await waitFor(() => {
      expect(screen.getByTestId("location-search").textContent).toContain("symbol=000660");
    });
    expect(screen.getByTestId("location-search").textContent).not.toContain("symbol=005930");
  });

  it("keeps the deep-linked symbol and unrelated query params on initial entry", async () => {
    mockFetchOnce(bootstrapWith("138040", "메리츠금융지주", "KOSPI"));
    mockFetchOnce(snapshotFor("138040", "메리츠금융지주", "KOSPI"));

    render(
      <MemoryRouter initialEntries={["/operations/realtime-quotes?symbol=138040&foo=bar"]}>
        <RealtimeQuoteView />
        <LocationProbe />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });
    const search = screen.getByTestId("location-search").textContent ?? "";
    expect(search).toContain("symbol=138040");
    expect(search).toContain("foo=bar");
  });
});

describe("RealtimeQuoteView 실시간 체결가 frame", () => {
  it("shows recent trade ticks on the default 시별 tab", async () => {
    mockFetchOnce(bootstrapWith("138040", "메리츠금융지주", "KOSPI"));
    mockFetchOnce(snapshotFor("138040", "메리츠금융지주", "KOSPI"));

    render(
      <MemoryRouter initialEntries={["/operations/realtime-quotes?symbol=138040"]}>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    expect(await screen.findByText("실시간 체결가")).toBeInTheDocument();
    expect(screen.getByText("시별")).toBeInTheDocument();
    expect(screen.getByText("일별")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });
  });

  it("fetches and shows daily bars when the 일별 tab is clicked", async () => {
    mockFetchOnce(bootstrapWith("138040", "메리츠금융지주", "KOSPI"));
    mockFetchOnce(snapshotFor("138040", "메리츠금융지주", "KOSPI"));
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/operations/realtime-quotes?symbol=138040"]}>
        <RealtimeQuoteView />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("71,900").length).toBeGreaterThan(0);
    });

    mockFetchOnce({
      symbol: "138040",
      bars: [
        { date: "20260708", close: 102900, change: 700, change_rate: 0.68, volume: 125040 },
        { date: "20260707", close: 102200, change: -300, change_rate: -0.29, volume: 98000 },
      ],
      generated_at: "2026-07-08T00:00:00Z",
    });
    await user.click(screen.getByText("일별"));

    await waitFor(() => {
      expect(screen.getByText("2026-07-08")).toBeInTheDocument();
    });
    expect(screen.getByText("102,900")).toBeInTheDocument();
    expect(screen.getByText("2026-07-07")).toBeInTheDocument();
  });
});
