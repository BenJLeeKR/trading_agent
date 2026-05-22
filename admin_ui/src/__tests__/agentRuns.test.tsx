import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, beforeEach, vi } from "vitest";
import AgentRunsView from "../components/AgentRunsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockAgentRuns, VALID_TOKEN, mockEiAgentRunNoSummary } from "./test-utils/fixtures";

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

/* ──────────────────────────────────────────────
 * 구조화된 출력 확장형 뷰 테스트
 * ────────────────────────────────────────────── */

describe("AgentRunsView structured output", () => {
  it("displays collapsed keys when structured output exists", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // EI run has: signal, confidence, summary — first 3 keys shown
    expect(screen.getByText(/signal/)).toBeInTheDocument();
    // AR run has: risk_score, max_order_value, approved — 3 keys, no "+N more"
    // FDC run has: decision, quantity, entry_price — 3 keys, no "+N more"
  });

  it("shows '-' for runs without structured output", async () => {
    // Create a run with null structured_output_json
    const runsWithoutSo = [
      {
        ...mockAgentRuns[0],
        structured_output_json: null,
      },
    ];
    mockUrlRouter({ "/agent-runs": runsWithoutSo });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // Should show '-' in the structured output column
    const dashes = screen.getAllByText("-");
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it("expands structured output on toggle click", async () => {
    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // Find and click the "구조화된 출력 펼치기" button
    const toggleButtons = screen.getAllByText("구조화된 출력 펼치기");
    expect(toggleButtons.length).toBeGreaterThanOrEqual(1);

    await userEvent.click(toggleButtons[0]);

    // After expanding, we should see key/value rows (use getAllByText since
    // "구조화된 출력" appears both in the table header <th> and the expanded button)
    await waitFor(() => {
      const matches = screen.getAllByText("구조화된 출력");
      expect(matches.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("expands nested object in structured output", async () => {
    // Use the EI run with aggregate_view (nested object)
    mockUrlRouter({ "/agent-runs": [mockEiAgentRunNoSummary] });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // Expand the structured output
    const toggleButtons = screen.getAllByText("구조화된 출력 펼치기");
    await userEvent.click(toggleButtons[0]);

    // Should show the aggregate_view as a nested toggle
    await waitFor(() => {
      expect(screen.getByText(/객체/)).toBeInTheDocument();
    });

    // Click to expand the nested object
    const nestedToggle = screen.getByText(/객체/);
    await userEvent.click(nestedToggle);

    // After expanding, nested fields should be visible
    await waitFor(() => {
      expect(screen.getByText("overall_bias")).toBeInTheDocument();
    });
  });

  it("copies full JSON on copy action", async () => {
    // Mock clipboard API
    const writeText = vi.fn();
    Object.assign(navigator, {
      clipboard: { writeText },
    });

    mockUrlRouter({ "/agent-runs": mockAgentRuns });
    renderView();

    await waitFor(() => {
      expect(screen.getByText("EI")).toBeInTheDocument();
    });

    // Expand the structured output
    const toggleButtons = screen.getAllByText("구조화된 출력 펼치기");
    await userEvent.click(toggleButtons[0]);

    // Click the copy button
    const copyButton = screen.getByText("전체 JSON 복사");
    await userEvent.click(copyButton);

    await waitFor(() => {
      expect(writeText).toHaveBeenCalled();
    });

    // Verify the copied content is valid JSON
    const calledArg = writeText.mock.calls[0][0];
    expect(() => JSON.parse(calledArg)).not.toThrow();
  });
});
