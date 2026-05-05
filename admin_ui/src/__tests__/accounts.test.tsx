import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import AccountsView from "../components/AccountsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import {
  mockAccounts,
  mockPositions,
  mockCashBalance,
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
 * Scenario 1: 로딩 상태
 * ─────────────────────────────────────────── */
describe("AccountsView loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    render(<AccountsView />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 계정 목록 렌더
 * ─────────────────────────────────────────── */
describe("AccountsView account list", () => {
  it("renders accounts table with account codes and types", async () => {
    // GET /accounts
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("Account Code")).toBeInTheDocument();
    });

    // Account data
    expect(screen.getByText("ACC-001")).toBeInTheDocument();
    expect(screen.getByText("ACC-002")).toBeInTheDocument();
    // CLIENT-001 appears in both rows of the DataTable
    expect(screen.getAllByText("CLIENT-001").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("cash")).toBeInTheDocument();
    expect(screen.getByText("margin")).toBeInTheDocument();
    // USD appears in both account rows (currency column)
    expect(screen.getAllByText("USD").length).toBeGreaterThanOrEqual(1);
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Row click → positions + cash balance
 * ─────────────────────────────────────────── */
describe("AccountsView account detail", () => {
  it("loads positions and cash balance after row click", async () => {
    const user = userEvent.setup();

    // Phase 1: accounts list
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Phase 2: register mocks BEFORE clicking (fetch fires synchronously in click handler)
    mockFetchOnce(mockPositions);   // GET /positions?account_id=...
    mockFetchOnce(mockCashBalance); // GET /cash-balances?account_id=...

    // Click the first account row
    await user.click(screen.getByText("ACC-001"));

    // Wait for detail section to appear
    await waitFor(() => {
      expect(screen.getByText(/Account Detail/)).toBeInTheDocument();
    });

    // Positions table
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("180.00")).toBeInTheDocument();
    expect(screen.getByText("185.50")).toBeInTheDocument();

    // Cash balance section
    expect(screen.getByText("50000.00")).toBeInTheDocument();
    expect(screen.getByText("100000.00")).toBeInTheDocument();
    // USD appears in DataTable AND cash balance section
    expect(screen.getAllByText("USD").length).toBeGreaterThanOrEqual(2);
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Cash balance null
 * ─────────────────────────────────────────── */
describe("AccountsView cash balance null", () => {
  it("shows 'No cash balance snapshot' when cashBalance is null", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Cash balance returns null
    mockFetchOnce(mockPositions);
    mockFetchOnce(null); // GET /cash-balances?account_id=... returns null

    await user.click(screen.getByText("ACC-001"));

    await waitFor(() => {
      expect(
        screen.getByText("No cash balance snapshot available."),
      ).toBeInTheDocument();
    });

    // Positions should still load
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Empty positions
 * ─────────────────────────────────────────── */
describe("AccountsView empty positions", () => {
  it("shows empty message when positions list is empty", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Positions returns empty array
    mockFetchOnce([]);   // GET /positions?account_id=... returns []
    mockFetchOnce(mockCashBalance);

    await user.click(screen.getByText("ACC-001"));

    await waitFor(() => {
      expect(
        screen.getByText("No positions for this account."),
      ).toBeInTheDocument();
    });

    // Cash balance should still load
    expect(screen.getByText("50000.00")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Search/filter accounts
 * ─────────────────────────────────────────── */
describe("AccountsView search filter", () => {
  it("filters accounts by search text", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    const searchInput = screen.getByLabelText("Search accounts");
    await user.type(searchInput, "ACC-002");

    // ACC-002 should remain, ACC-001 should be hidden
    expect(screen.getByText("ACC-002")).toBeInTheDocument();
    expect(screen.queryByText("ACC-001")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 8: Filter by account type
 * ─────────────────────────────────────────── */
describe("AccountsView type filter", () => {
  it("shows only matching accounts when type filter is selected", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    const typeSelect = screen.getByLabelText("Filter by account type");
    await user.selectOptions(typeSelect, "margin");

    // ACC-002 (margin) should remain, ACC-001 (cash) should be hidden
    expect(screen.getByText("ACC-002")).toBeInTheDocument();
    expect(screen.queryByText("ACC-001")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 9: Selected row highlight
 * ─────────────────────────────────────────── */
describe("AccountsView selected row highlight", () => {
  it("highlights the selected account row", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockAccounts);
    // Row click triggers Phase 2 API calls
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockCashBalance);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Click ACC-001 row
    await user.click(screen.getByText("ACC-001"));

    // The selected row should have aria-selected="true"
    const selectedRow = screen.getByRole("row", { selected: true });
    expect(selectedRow).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 10: Detail area clarity
 * ─────────────────────────────────────────── */
describe("AccountsView detail area clarity", () => {
  it("shows account code and type in detail header", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockCashBalance);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    await user.click(screen.getByText("ACC-001"));

    await waitFor(() => {
      expect(screen.getByText(/Account Detail/)).toBeInTheDocument();
    });

    // Detail header should contain account code and type
    // These values appear in both DataTable row and detail header, so use getAllByText
    expect(screen.getAllByText(/ACC-001/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/cash/).length).toBeGreaterThanOrEqual(2);
  });
});

/* ───────────────────────────────────────────
 * Scenario 11: Selection reset on filter
 * ─────────────────────────────────────────── */
describe("AccountsView selection reset on filter", () => {
  it("resets selection when filtered list no longer contains selected account", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockCashBalance);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Select ACC-001
    await user.click(screen.getByText("ACC-001"));

    await waitFor(() => {
      expect(screen.getByText(/Account Detail/)).toBeInTheDocument();
    });

    // Now filter by "margin" — ACC-001 (cash) should disappear from list
    const typeSelect = screen.getByLabelText("Filter by account type");
    await user.selectOptions(typeSelect, "margin");

    // Detail should be gone since ACC-001 is no longer visible
    await waitFor(() => {
      expect(screen.queryByText(/Account Detail/)).not.toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: API 실패
 * ─────────────────────────────────────────── */
describe("AccountsView error state", () => {
  it("shows ErrorBanner when API call fails", async () => {
    // First API (getAccounts) fails
    mockFetchError(500, "Server error");

    render(<AccountsView />);

    await waitFor(() => {
      expect(
        screen.getByText(/Server error/i),
      ).toBeInTheDocument();
    });
  });
});
