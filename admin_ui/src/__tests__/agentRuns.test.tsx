import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, beforeEach, vi } from "vitest";
import AgentRunsView from "../components/AgentRunsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockAgentRuns, VALID_TOKEN } from "./test-utils/fixtures";

/**
 * URL-based fetch mock — routes are matched by `url.includes(pattern)`.
 * The first match wins. Used to avoid mockFetchOnce call-order dependencies.
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

/* ── Helper to render AgentRunsView inside a MemoryRouter ── */
function renderView() {
  return render(
    <MemoryRouter>
      <AgentRunsView />
    </MemoryRouter>
  );
}

/* ── Test data variants ── */

/** Single EI run for filter tests */
const singleEiRun = [mockAgentRuns[0]];

/** Single completed run */
const singleCompletedRun = [mockAgentRuns[0]];

/** Empty array */
const emptyRuns: typeof mockAgentRuns = [];

/* ──────────────────────────────────────────────
 * AgentRunsView — data rendering
 * ────────────────────────────────────────────── */

describe("AgentRunsView with data", () => {
  it("renders agent runs with EI/AR/FDC badges", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    expect(screen.getByText("AR")).toBeInTheDocument();
    expect(screen.getByText("FDC")).toBeInTheDocument();
    expect(screen.getByText("3개 결과")).toBeInTheDocument();
  });

  it("shows summary text from structured_output_json", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("Strong earnings momentum")).toBeInTheDocument();
    });
  });

  it("shows degraded indicator for EI run with incomplete interpretation", async () => {
    const degradedEiRun = [{
      agent_run_id: "degraded-ei-run-001",
      decision_context_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00dc1",
      agent_type: "event_interpretation",
      started_at: "2026-05-05T00:00:02Z",
      status: "completed",
      structured_output_json: {
        summary: "입력 이벤트 감지됐으나 LLM이 이벤트를 무시함. [degraded: self_contradiction_corrected]. 전반 중립.",
        aggregate_view: {
          overall_bias: "neutral",
          event_conflict: false,
          top_reason_codes: [],
          event_count: 0,
          no_material_events: true,
          interpretation_incomplete: true,
          degraded_reason: "self_contradiction_corrected",
        },
      },
      completed_at: "2026-05-05T00:00:05Z",
      model_id: null,
      prompt_id: null,
      temperature: null,
      seed: null,
      raw_output_uri: null,
      created_at: null,
    }];
    mockUrlRouter({ "/agent-runs": degradedEiRun });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // ⚠️ prefix가 summary 텍스트 앞에 표시되는지 확인
    expect(screen.getByText(/⚠️/)).toBeInTheDocument();
    // degraded reason이 title 속성으로 표시되는지 확인 (span의 title)
    const summarySpan = screen.getByText(/⚠️/).closest('span');
    expect(summarySpan).toBeInTheDocument();
  });
});

/* ──────────────────────────────────────────────
 * AgentRunsView — empty state
 * ────────────────────────────────────────────── */

describe("AgentRunsView empty list", () => {
  it("shows empty message when no agent runs exist", async () => {
    mockUrlRouter({ "/agent-runs": emptyRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("에이전트 실행 기록이 없습니다")).toBeInTheDocument();
    });
  });
});

/* ──────────────────────────────────────────────
 * AgentRunsView — error state
 * ────────────────────────────────────────────── */

describe("AgentRunsView error state", () => {
  it("shows error banner when API call fails", async () => {
    mockUrlRouter({ "/agent-runs": new Error("Network failure") });
    renderView();

    await waitFor(() => {
      expect(screen.getByText(/API error 500/)).toBeInTheDocument();
    });
  });

  it("dismisses error banner on click", async () => {
    mockUrlRouter({ "/agent-runs": new Error("Network failure") });
    renderView();

    await waitFor(() => {
      expect(screen.getByText(/API error 500/)).toBeInTheDocument();
    });

    // Click dismiss button (×)
    const dismissBtn = screen.getByRole("button", { name: /×|dismiss/i });
    await userEvent.click(dismissBtn);

    await waitFor(() => {
      expect(screen.queryByText(/API error 500/)).not.toBeInTheDocument();
    });
  });
});

/* ──────────────────────────────────────────────
 * AgentRunsView — search filter
 * ────────────────────────────────────────────── */

describe("AgentRunsView search filter", () => {
  it("filters runs by decision_context_id", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // All 3 runs visible initially
    expect(screen.getByText("3개 결과")).toBeInTheDocument();

    // Search for a non-matching decision_context_id
    const searchInput = screen.getByPlaceholderText(/에이전트 실행 ID 검색/i);
    await userEvent.type(searchInput, "NONEXISTENT");

    await waitFor(() => {
      expect(screen.getByText("0개 결과")).toBeInTheDocument();
    });
  });
});

/* ──────────────────────────────────────────────
 * AgentRunsView — agent type filter
 * ────────────────────────────────────────────── */

describe("AgentRunsView agent type filter", () => {
  it("shows only EI runs when event_interpretation filter is selected", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // Select "event_interpretation" from the Agent Type dropdown
    const agentTypeSelect = screen.getByLabelText("에이전트 유형");
    await userEvent.selectOptions(agentTypeSelect, "event_interpretation");

    // EI should still be visible
    expect(screen.getByText("EI")).toBeInTheDocument();
    // AR and FDC should not be visible
    expect(screen.queryByText("AR")).not.toBeInTheDocument();
    expect(screen.queryByText("FDC")).not.toBeInTheDocument();
    expect(screen.getByText("1개 결과")).toBeInTheDocument();
  });
});

/* ──────────────────────────────────────────────
 * AgentRunsView — status filter
 * ────────────────────────────────────────────── */

describe("AgentRunsView status filter", () => {
  it("shows only completed runs when completed filter is selected", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // All 3 runs are "completed", so all should remain visible
    const statusSelect = screen.getByLabelText("상태");
    await userEvent.selectOptions(statusSelect, "completed");

    expect(screen.getByText("EI")).toBeInTheDocument();
    expect(screen.getByText("AR")).toBeInTheDocument();
    expect(screen.getByText("FDC")).toBeInTheDocument();
    expect(screen.getByText("3개 결과")).toBeInTheDocument();
  });

  it("shows 0 results when status filter matches nothing", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // Select "running" — none of the mock runs have this status
    const statusSelect = screen.getByLabelText("상태");
    await userEvent.selectOptions(statusSelect, "running");

    await waitFor(() => {
      expect(screen.getByText("0개 결과")).toBeInTheDocument();
    });
  });
});

/* ──────────────────────────────────────────────
 * AgentRunsView — context ID drill-down link
 * ────────────────────────────────────────────── */

describe("AgentRunsView context ID link", () => {
  it("renders decision_context_id as a link to /decisions?contextId=...", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // Find the context ID link — first mock run has decision_context_id ending in "00dc1"
    // All 3 mock runs share the same decision_context_id, so getAllByTitle returns 3 links
    const links = screen.getAllByTitle(mockAgentRuns[0].decision_context_id);
    expect(links.length).toBeGreaterThanOrEqual(1);
    expect(links[0].tagName).toBe("A");
    expect(links[0]).toHaveAttribute(
      "href",
      `/decisions?contextId=${encodeURIComponent(mockAgentRuns[0].decision_context_id)}`
    );
  });
});
