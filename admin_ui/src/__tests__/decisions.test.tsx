import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, beforeEach, vi } from "vitest";
import DecisionsView from "../components/DecisionsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import { mockTradeDecisions, mockDecisionContext, VALID_TOKEN } from "./test-utils/fixtures";

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
    mockFetchOnce(mockTradeDecisions);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
    });

    // Verify all tickers are rendered
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();

    // Verify total count
    expect(screen.getByText(/Total: 3 decisions/)).toBeInTheDocument();

    // Verify key column headers (updated for template columns)
    expect(screen.getByRole("columnheader", { name: "Symbol" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Action" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Confidence" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Strategy" })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: Confidence 색상 검증
 * ─────────────────────────────────────────── */
describe("DecisionsView confidence color", () => {
  it("applies correct color based on confidence value", async () => {
    mockFetchOnce(mockTradeDecisions);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
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
    mockFetchOnce([]);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("No trade decisions found.")).toBeInTheDocument();
    });

    expect(screen.getByText(/Total: 0 decisions/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Row selection → detail panel
 * ─────────────────────────────────────────── */
describe("DecisionsView detail panel", () => {
  it("shows decision fields and lazy-loads context on row click", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockTradeDecisions);
    mockFetchOnce(mockDecisionContext);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
    });

    // Click the first row (AAPL)
    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    // Detail panel shows decision fields
    await waitFor(() => {
      expect(screen.getByText("Decision Detail")).toBeInTheDocument();
    });
    // Decision type "auto_execute" appears in detail panel
    expect(screen.getAllByText("auto_execute").length).toBeGreaterThanOrEqual(1);
    // 85% appears in table row, status banner, ConfidenceBar, and Input Signals card
    expect(screen.getAllByText("85%").length).toBeGreaterThanOrEqual(3);
    // rationale_summary appears in Reason section
    expect(screen.getByText("Strong earnings outlook for AAPL")).toBeInTheDocument();
    // Quantity "100" appears in Detail card and Input Signals card
    expect(screen.getAllByText("100").length).toBeGreaterThanOrEqual(2);

    // Market Context section loaded
    await waitFor(() => {
      expect(screen.getByText("Market Context")).toBeInTheDocument();
    });
    // strategy_id UUID appears in both DataTable column and detail panel
    expect(screen.getAllByText("aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00s1").length).toBeGreaterThanOrEqual(2);
    // account_id UUID is shown in detail panel
    expect(screen.getByText("aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1")).toBeInTheDocument();
  });

  it("shows error banner when context API call fails", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockTradeDecisions);
    mockFetchError(500, "Internal error");

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
    });

    // Click the first row
    const aaplRow = screen.getByText("AAPL");
    await user.click(aaplRow);

    await waitFor(() => {
      expect(screen.getByText("Decision Detail")).toBeInTheDocument();
    });

    // Error should appear
    await waitFor(() => {
      expect(screen.getByText(/API error 500/i)).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Filter by side
 * ─────────────────────────────────────────── */
describe("DecisionsView side filter", () => {
  it("shows only matching decisions when side filter is selected", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockTradeDecisions);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
    });

    // Click "Buy" side button
    const buyBtn = screen.getByRole("button", { name: /^Buy$/i });
    await user.click(buyBtn);

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
    mockFetchOnce(mockTradeDecisions);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
    });

    const searchInput = screen.getByLabelText("Search decisions by ticker");
    await user.type(searchInput, "AAPL");

    // Only AAPL should be visible
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Filter by confidence range
 * ─────────────────────────────────────────── */
describe("DecisionsView confidence filter", () => {
  it("filters decisions by confidence range", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockTradeDecisions);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
    });

    // Set confidence min to 0.5 → only AAPL (0.85) and TSLA (0.55) should show
    const minInput = screen.getByLabelText("Minimum confidence");
    await user.type(minInput, "0.5");

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.queryByText("MSFT")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 8: Empty / no-selection state
 * ─────────────────────────────────────────── */
describe("DecisionsView no selection state", () => {
  it("shows placeholder text when no row is selected", async () => {
    mockFetchOnce(mockTradeDecisions);

    render(
      <MemoryRouter>
        <DecisionsView />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Trade Decisions")[0]).toBeInTheDocument();
    });

    // Placeholder should be visible when data loaded and no row selected
    expect(
      screen.getByText("Select a decision row to view details."),
    ).toBeInTheDocument();
  });
});
