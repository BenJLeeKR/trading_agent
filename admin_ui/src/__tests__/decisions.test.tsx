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
  mockRecentEvents005930,
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
    expect(screen.getByRole("columnheader", { name: "종목" })).toBeInTheDocument();
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
    // EI/AR decision_json sections should be rendered
    expect(screen.getByText("종합 판단 근거")).toBeInTheDocument();
    expect(screen.getByText("이벤트 해석 (EI)")).toBeInTheDocument();
    expect(screen.getByText("리스크 평가 (AR)")).toBeInTheDocument();
    // EI reason content (formatter 적용 — raw event_bias가 BIAS_LABEL_MAP에 없으므로 원문 유지)
    expect(screen.getByText(/Positive earnings surprise expected/)).toBeInTheDocument();
    // AR reason content
    expect(screen.getByText(/Low risk — strong fundamentals/)).toBeInTheDocument();
    // event_reason_codes chip 렌더링 검증 (formatter에 의해 한글 라벨로 표시)
    expect(screen.getByText("결정 사유")).toBeInTheDocument();
    expect(screen.getByText("외국인 매도")).toBeInTheDocument();
    expect(screen.getByText("가격 하락")).toBeInTheDocument();
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

  it("EI run displays aggregate_view based summary when top-level summary is absent", async () => {
    const user = userEvent.setup();
    // EI run fixture (top-level summary 없음, aggregate_view 있음)
    const eiOnlyRuns = [{
      agent_run_id: "ei-run-001",
      decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
      agent_type: "event_interpretation",
      started_at: "2026-05-05T00:00:02Z",
      status: "completed",
      structured_output_json: {
        symbol: "005930",
        agent_name: "event_interpretation",
        events: [],
        aggregate_view: {
          overall_bias: "negative",
          event_conflict: false,
          top_reason_codes: ["foreign_investor_selling", "price_decline"],
          opposing_evidence: [],
        },
        schema_version: "1.0",
        decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
      },
      completed_at: "2026-05-05T00:00:05Z",
      model_id: null,
      prompt_id: null,
      temperature: null,
      seed: null,
      raw_output_uri: null,
      created_at: null,
    }];
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": mockDecisionContext,
      "/agent-runs": eiOnlyRuns,
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

    // EI badge visible
    expect(screen.getByText("EI")).toBeInTheDocument();

    // formatEiOutput 기반 요약이 표시되는지 확인 (한글 interpreted view)
    expect(screen.getByText(/성향: 부정/)).toBeInTheDocument();
    // reason_codes fallback: top_reason_codes가 formatter에 의해 한글 라벨로 표시되는지 확인
    // (EI 요약 + chip 양쪽에 표시되므로 getAllByText 사용)
    const foreignSellMatches = screen.getAllByText(/외국인 매도/);
    expect(foreignSellMatches.length).toBeGreaterThanOrEqual(1);
    const priceDeclineMatches = screen.getAllByText(/가격 하락/);
    expect(priceDeclineMatches.length).toBeGreaterThanOrEqual(1);
  });

  it("FDC/AR run still displays top-level summary (regression)", async () => {
    const user = userEvent.setup();
    // FDC run fixture (top-level summary 있음)
    const fdcOnlyRuns = [{
      agent_run_id: "fdc-run-001",
      decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
      agent_type: "final_decision_composer",
      started_at: "2026-05-05T00:00:10Z",
      status: "completed",
      structured_output_json: {
        summary: "종합 판단: 이벤트 해석 결과 중립 편향이며 리스크 허용 범위 내",
        decision_type: "HOLD",
        reason_codes: ["no_events", "neutral_bias"],
        risk_opinion: "Low risk — strong fundamentals",
      },
      completed_at: "2026-05-05T00:00:12Z",
      model_id: null,
      prompt_id: null,
      temperature: null,
      seed: null,
      raw_output_uri: null,
      created_at: null,
    }];
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": mockTradeDecisions,
      "/decision-contexts/": mockDecisionContext,
      "/agent-runs": fdcOnlyRuns,
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

    // FDC badge visible
    expect(screen.getByText("FDC")).toBeInTheDocument();

    // Top-level summary가 그대로 표시되는지 확인
    // ("종합 판단 근거" 헤더에도 포함되므로 getAllByText 사용)
    const summaryMatches = screen.getAllByText(/종합 판단/);
    expect(summaryMatches.length).toBeGreaterThanOrEqual(1);

    // top-level reason_codes가 표시되는지 확인
    // (summary: ... 텍스트에도 포함될 수 있으므로 getAllByText 사용)
    const noEventsMatches = screen.getAllByText(/no_events/);
    expect(noEventsMatches.length).toBeGreaterThanOrEqual(1);
    const neutralBiasMatches = screen.getAllByText(/neutral_bias/);
    expect(neutralBiasMatches.length).toBeGreaterThanOrEqual(1);

    // decision_type 표시 확인
    expect(screen.getByText(/HOLD/)).toBeInTheDocument();
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

/* ───────────────────────────────────────────
 * Scenario 10: Pagination footer 표시
 * ─────────────────────────────────────────── */
describe("DecisionsView pagination footer", () => {
  it("shows pagination footer when decisions are loaded", async () => {
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

    // Total item count should appear (mockTradeDecisions has 3 items)
    expect(screen.getByText("총 3건")).toBeInTheDocument();
    // Page navigation should appear
    expect(screen.getByRole("button", { name: "Previous page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 11: EI interpreted labels (Korean)
 * ─────────────────────────────────────────── */
describe("DecisionsView EI interpreted labels", () => {
  it("displays Korean labels for event_bias when bias code is recognized", async () => {
    const user = userEvent.setup();
    // TSLA 의 decision_json.event_bias = "Neutral — no significant catalysts" (not in BIAS_LABEL_MAP)
    // → formatter는 원문을 그대로 표시. 'negative' code를 가진 decision으로 확인 필요.
    const decisionsWithBiasCode = [
      {
        trade_decision_id: "bias-test-001",
        decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
        decision_type: "auto_execute",
        side: "buy",
        strategy_id: "strat-bias-test",
        symbol: "TEST",
        instrument_name: "Test Corp.",
        market: "NASDAQ",
        entry_style: "limit",
        created_at: "2026-05-05T00:00:00Z",
        entry_price: 100,
        quantity: 10,
        max_order_value: 2000,
        confidence: 0.75,
        rationale_summary: "Test rationale",
        decision_json: {
          event_bias: "negative",
          event_conflict: true,
          event_reason_codes: ["foreign_investor_selling", "earnings_surprise"],
          risk_opinion: "Low risk",
          risk_flags: [],
        },
      },
    ];

    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": decisionsWithBiasCode,
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

    // Click TEST row
    const testRow = screen.getByText("TEST");
    await user.click(testRow);

    // Detail panel with EI section
    await waitFor(() => {
      expect(screen.getByText("의사결정 상세")).toBeInTheDocument();
    });

    // EI section: bias → '부정' (Korean label via formatBiasLabel)
    expect(screen.getByText(/부정/)).toBeInTheDocument();
    // Conflict label (event_conflict=true)
    expect(screen.getByText(/상반된 이벤트 존재/)).toBeInTheDocument();
    // Reason codes → Korean labels
    expect(screen.getByText("외국인 매도")).toBeInTheDocument();
    expect(screen.getByText("실적 서프라이즈")).toBeInTheDocument();
  });

  it("shows '사유 정보 없음' when event_reason_codes is empty", async () => {
    const user = userEvent.setup();
    const decisionsNoReasonCodes = [
      {
        trade_decision_id: "no-reason-test-001",
        decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
        decision_type: "auto_execute",
        side: "hold",
        strategy_id: "strat-no-reason",
        symbol: "NORSN",
        instrument_name: "No Reason Co.",
        market: "NASDAQ",
        entry_style: "limit",
        created_at: "2026-05-05T00:00:00Z",
        entry_price: null,
        quantity: 0,
        max_order_value: 0,
        confidence: 0.5,
        rationale_summary: "No reason test",
        decision_json: {
          event_bias: "neutral",
          event_conflict: false,
          event_reason_codes: [],
          risk_opinion: "Medium risk",
          risk_flags: [],
        },
      },
    ];

    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": decisionsNoReasonCodes,
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

    const row = screen.getByText("NORSN");
    await user.click(row);

    await waitFor(() => {
      expect(screen.getByText("의사결정 상세")).toBeInTheDocument();
    });

    // '사유 정보 없음' 메시지 표시
    expect(screen.getByText("사유 정보 없음")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Recent Events Section
 * ─────────────────────────────────────────── */
describe("Recent Events Section", () => {
  const sampleSymbol = "005930";

  const decisionWithEvents = {
    trade_decision_id: "events-test-001",
    decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
    decision_type: "auto_execute",
    side: "buy",
    strategy_id: "strat-events",
    symbol: sampleSymbol,
    instrument_name: "Samsung Electronics",
    market: "KRX",
    entry_style: "limit",
    created_at: "2026-05-17T00:00:00Z",
    entry_price: 80000,
    quantity: 10,
    max_order_value: 1000000,
    confidence: 0.75,
    rationale_summary: "Test rationale with events",
    decision_json: {},
  };

  const noSymbolDecision = {
    ...decisionWithEvents,
    trade_decision_id: "no-symbol-test-001",
    symbol: "",
  };

  it("shows recent events section when decision with symbol is selected", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": [decisionWithEvents],
      "/external-events/recent": { status: "ok", data: mockRecentEvents005930 },
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

    // Click the symbol row to select decision
    const row = screen.getByText(sampleSymbol);
    await user.click(row);

    // Recent events section should appear
    await waitFor(() => {
      expect(screen.getByText("최근 이벤트 (Recent Events)")).toBeInTheDocument();
    });

    // T1 badges should be visible (3 T1 events)
    expect(screen.getAllByText("T1").length).toBeGreaterThan(0);
    // T3 badges should be visible (2 T3 events)
    expect(screen.getAllByText("T3").length).toBeGreaterThan(0);

    // Headlines should be rendered
    expect(screen.getByText("삼성전자, 2026년 1분기 영업이익 14조원 기록")).toBeInTheDocument();
    expect(screen.getByText("삼성전자, 차세대 HBM4 개발 속도")).toBeInTheDocument();
  });

  it("shows T1 and T3 badges with correct colors", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": [decisionWithEvents],
      "/external-events/recent": { status: "ok", data: mockRecentEvents005930 },
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

    const row = screen.getByText(sampleSymbol);
    await user.click(row);

    await waitFor(() => {
      expect(screen.getByText("최근 이벤트 (Recent Events)")).toBeInTheDocument();
    });

    // T1 badge with blue styling (pick first of multiple T1 badges)
    const t1Badges = screen.getAllByText("T1");
    expect(t1Badges[0].className).toContain("bg-blue-100");
    expect(t1Badges[0].className).toContain("text-blue-800");

    // T3 badge with gray styling (pick first of multiple T3 badges)
    const t3Badges = screen.getAllByText("T3");
    expect(t3Badges[0].className).toContain("bg-gray-100");
    expect(t3Badges[0].className).toContain("text-gray-600");
  });

  it("shows empty state when no events", async () => {
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": [decisionWithEvents],
      "/external-events/recent": { status: "ok", data: [] },
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

    const row = screen.getByText(sampleSymbol);
    await user.click(row);

    await waitFor(() => {
      expect(screen.getByText("최근 이벤트가 없습니다.")).toBeInTheDocument();
    });
  });

  it("does not fetch events when symbol is empty", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const user = userEvent.setup();
    mockUrlRouter({
      "/metadata/enums": mockEnumMetadataResponse,
      "/trade-decisions": [noSymbolDecision],
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

    const row = screen.getByText("Samsung Electronics");
    await user.click(row);

    // Wait briefly — no fetch for external-events should occur
    await new Promise((r) => setTimeout(r, 300));
    const eventCalls = fetchSpy.mock.calls.filter(
      ([url]) => typeof url === "string" && url.includes("/external-events/recent")
    );
    expect(eventCalls.length).toBe(0);

    fetchSpy.mockRestore();
  });
});
