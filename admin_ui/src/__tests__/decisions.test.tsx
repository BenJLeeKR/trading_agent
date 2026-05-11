import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, beforeEach, vi } from "vitest";
import DecisionsView from "../components/DecisionsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import {
  mockTradeDecisions,
  mockDecisionContext,
  mockAgentRuns,
  mockEnumMetadataResponse,
  VALID_TOKEN,
} from "./test-utils/fixtures";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";

/**
 * Create a fetch mock that dispatches by URL path pattern.
 * Routes are matched by `url.includes(pattern)` — the first match wins.
 * If the route value is an `Error`, it is returned as a 500 response.
 */
function mockUrlRouter(routes: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : input instanceof Request ? input.url : "";
    const entry = Object.entries(routes).find(([pattern]) => url.includes(pattern));
    if (entry) {
      const data = entry[1];
      if (data instanceof Error) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: data.message,
          json: async () => ({ detail: data.message }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => data,
      } as Response);
    }
    return Promise.reject(new Error(`No mock for ${url}`));
  });
}

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

/* ───────────────────────────────────────────
 * Scenario 1: 결정 목록 렌더링
 * ─────────────────────────────────────────── */
describe("DecisionsView with data", () => {
  it("renders trade decisions in DataTable", async () => {
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    // Verify all tickers are rendered
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();

    // Verify key column headers (template columns: Side, Reasoning, Timestamp)
    expect(screen.getByRole("columnheader", { name: "심볼" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "매매" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "신뢰도" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "근거" })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: Confidence 색상 검증
 * ─────────────────────────────────────────── */
describe("DecisionsView confidence color", () => {
  it("applies correct color based on confidence value", async () => {
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    // AAPL confidence 0.85 >= 0.7 → green (#22c55e)
    const aaplConf = screen.getByText("85%");
    expect(aaplConf).toHaveStyle("color: #22c55e");

    // TSLA confidence 0.55 >= 0.4 → amber (#f59e0b)
    const tslaConf = screen.getByText("55%");
    expect(tslaConf).toHaveStyle("color: #f59e0b");

    // MSFT confidence 0.25 < 0.4 → red (#ef4444)
    const msftConf = screen.getByText("25%");
    expect(msftConf).toHaveStyle("color: #ef4444");
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 빈 목록
 * ─────────────────────────────────────────── */
describe("DecisionsView empty list", () => {
  it("shows empty message when no decisions", async () => {
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": [],
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정이 없습니다.")).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Row selection → detail panel
 * ─────────────────────────────────────────── */
describe("DecisionsView detail panel", () => {
  it("shows decision fields and lazy-loads context on row click", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": mockDecisionContext,
      "/agent-runs": mockAgentRuns,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    // Click the first row (AAPL)
    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    // Detail panel shows decision fields
    await waitFor(() => {
      expect(screen.getByText("의사결정 상세")).toBeInTheDocument();
    });
    // Decision type "auto_execute" appears in detail panel (via getEnumLabel → "자동 실행")
    expect(screen.getAllByText("자동 실행").length).toBeGreaterThanOrEqual(1);
    // 85% appears in table row, ConfidenceBar, and Signals card
    expect(screen.getAllByText("85%").length).toBeGreaterThanOrEqual(3);
    // rationale_summary appears in both table (Reasoning column) and detail panel (Reason section)
    expect(screen.getAllByText("Strong earnings outlook for AAPL").length).toBeGreaterThanOrEqual(1);
    // Quantity "100" appears in Detail card and Signals card
    expect(screen.getAllByText("100").length).toBeGreaterThanOrEqual(2);

    // Market Context section loaded
    await waitFor(() => {
      expect(screen.getByText("시장 컨텍스트")).toBeInTheDocument();
    });
    // strategy_id UUID appears in both DataTable column and detail panel
    expect(screen.getAllByText("aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s1").length).toBeGreaterThanOrEqual(2);
    // account_id UUID is shown in detail panel
    expect(screen.getByText("aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1")).toBeInTheDocument();
  });

  it("shows error banner when context API call fails", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": new Error("API error 500: Internal error"),
      "/agent-runs": mockAgentRuns,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    // Click the first row
    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    await waitFor(() => {
      expect(screen.getByText("의사결정 상세")).toBeInTheDocument();
    });

    // Error should appear
    await waitFor(() => {
      expect(screen.getByText(/API error 500/i)).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Filter by side (dropdown)
 * ─────────────────────────────────────────── */
describe("DecisionsView side filter", () => {
  it("shows only matching decisions when side filter is selected", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    // Select "매수" from side dropdown
    const sideSelect = screen.getByLabelText("매매");
    await user.selectOptions(sideSelect, "buy");

    // AAPL (buy) should remain, TSLA (hold) and MSFT (sell) should be hidden
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
    expect(screen.queryByText("MSFT")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: Filter by symbol search
 * ─────────────────────────────────────────── */
describe("DecisionsView symbol search", () => {
  it("filters decisions by ticker search text", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText("심볼 또는 의사결정 ID 검색...");
    await user.type(searchInput, "AAPL");

    // Only AAPL should be visible
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 8: Agent Runs panel in detail panel
 * ─────────────────────────────────────────── */
describe("DecisionsView agent runs panel", () => {
  it("shows agent runs panel with EI/AR/FDC cards when decision is selected", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": mockDecisionContext,
      "/agent-runs": mockAgentRuns,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    // Click AAPL row
    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    // Agent Runs card appears
    await waitFor(() => {
      expect(screen.getByText("에이전트 실행")).toBeInTheDocument();
    });

    // All three agent type badges are visible
    expect(screen.getByText("EI")).toBeInTheDocument();
    expect(screen.getByText("AR")).toBeInTheDocument();
    expect(screen.getByText("FDC")).toBeInTheDocument();

    // Structured output summary is shown
    expect(screen.getByText(/Strong earnings momentum/)).toBeInTheDocument();
  });

  it("shows empty state when no agent runs exist", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": mockDecisionContext,
      "/agent-runs": [],
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    await waitFor(() => {
      expect(screen.getByText("에이전트 실행")).toBeInTheDocument();
    });

    expect(
      screen.getByText("이 의사결정 컨텍스트에 대한 에이전트 실행 기록이 없습니다."),
    ).toBeInTheDocument();
  });

  it("shows error banner when agent runs API call fails", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": mockDecisionContext,
      "/agent-runs": new Error("API error 500: Internal error"),
    });
    // Override the agent-runs route to return an error
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : "";
      if (url.includes("/metadata/enums")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockEnumMetadataResponse,
        } as Response);
      }
      if (url.includes("/agent-runs")) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: "Internal error",
          json: async () => ({ detail: "Internal error" }),
        } as Response);
      }
      if (url.includes("/decision-contexts/")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDecisionContext,
        } as Response);
      }
      if (url.includes("/trade-decisions")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockTradeDecisions,
        } as Response);
      }
      return Promise.reject(new Error(`No mock for ${url}`));
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    await waitFor(() => {
      expect(screen.getByText("에이전트 실행")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText(/API error 500/i)).toBeInTheDocument();
    });
  });

  it("toggles structured output JSON detail", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": mockDecisionContext,
      "/agent-runs": mockAgentRuns,
    });

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("의사결정")).toBeInTheDocument();
    });

    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    await waitFor(() => {
      expect(screen.getByText("에이전트 실행")).toBeInTheDocument();
    });

    // Click "원시 출력 보기" for the first run
    const showButtons = screen.getAllByText("원시 출력 보기");
    await user.click(showButtons[0]);

    // JSON block should appear
    await waitFor(() => {
      expect(screen.getByText(/"signal"/)).toBeInTheDocument();
    });

    // Click "원시 출력 숨기기"
    const hideButton = screen.getByText("원시 출력 숨기기");
    await user.click(hideButton);

    // JSON block should disappear
    await waitFor(() => {
      expect(screen.queryByText(/"signal"/)).not.toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 9: contextId query param → filtered fetch + indicator
 * ─────────────────────────────────────────── */
describe("DecisionsView contextId query param", () => {
  it("passes contextId to getTradeDecisions and shows filter indicator", async () => {
    const contextId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : "";
      if (url.includes("/metadata/enums")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockEnumMetadataResponse,
        } as Response);
      }
      // Must include decision_context_id query param
      if (url.includes("/trade-decisions") && url.includes("decision_context_id")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockTradeDecisions,
        } as Response);
      }
      if (url.includes("/trade-decisions")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        } as Response);
      }
      return Promise.reject(new Error(`No mock for ${url}`));
    });

    render(
      <MemoryRouter initialEntries={[`/decisions?contextId=${contextId}`]}>
        <DecisionsView />
      </MemoryRouter>,
    );

    // Filter indicator should appear
    await waitFor(() => {
      expect(screen.getByText(/컨텍스트별 필터링/i)).toBeInTheDocument();
    });

    // The fetch URL should include decision_context_id
    const tradeDecisionsCalls = fetchSpy.mock.calls.filter(
      ([input]) => typeof input === "string" && input.includes("/trade-decisions")
    );
    expect(tradeDecisionsCalls.length).toBeGreaterThanOrEqual(1);
    const callUrl = tradeDecisionsCalls[0][0] as string;
    expect(callUrl).toContain("decision_context_id");
    expect(callUrl).toContain(encodeURIComponent(contextId));
  });

  it("clears context filter when X button is clicked", async () => {
    const contextId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1";
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
    });

    render(
      <MemoryRouter initialEntries={[`/decisions?contextId=${contextId}`]}>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/컨텍스트별 필터링/i)).toBeInTheDocument();
    });

    // Click the clear button
    const clearBtn = screen.getByRole("button", { name: /컨텍스트 필터 초기화/i });
    await user.click(clearBtn);

    // Indicator should disappear
    await waitFor(() => {
      expect(screen.queryByText(/컨텍스트별 필터링/i)).not.toBeInTheDocument();
    });
  });
});
