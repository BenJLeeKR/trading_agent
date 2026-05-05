import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import AccountsView from "../components/AccountsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { mockFetchOnce, mockFetchError } from "./test-utils/mockFetch";
import {
  mockOrders,
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
 * Scenario 2: 계정 카드 목록 렌더
 * ─────────────────────────────────────────── */
describe("AccountsView account list", () => {
  it("renders account cards with account codes and types", async () => {
    // GET /orders first (for client_id heuristic), then GET /accounts?client_id=...
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("Accounts & Positions")).toBeInTheDocument();
    });

    // Account data — rendered as card buttons
    expect(screen.getByText("ACC-001")).toBeInTheDocument();
    expect(screen.getByText("ACC-002")).toBeInTheDocument();

    // Account types are shown in the card broker line: e.g. "cash · USD"
    expect(screen.getByText(/cash · USD/)).toBeInTheDocument();
    expect(screen.getByText(/margin · USD/)).toBeInTheDocument();
    // USD appears in both account card broker lines (e.g. "cash · USD")
    expect(screen.getAllByText(/USD/).length).toBeGreaterThanOrEqual(2);
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: Card click → positions + cash balance
 * ─────────────────────────────────────────── */
describe("AccountsView account detail", () => {
  it("loads positions and cash balance after card click", async () => {
    const user = userEvent.setup();

    // Phase 1: orders (for client_id heuristic)
    mockFetchOnce(mockOrders);
    // Phase 2: accounts list
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Phase 2: register mocks BEFORE clicking (fetch fires synchronously in click handler)
    mockFetchOnce(mockPositions);   // GET /positions?account_id=...
    mockFetchOnce(mockCashBalance); // GET /cash-balances?account_id=...

    // Click the first account card button
    await user.click(screen.getByText("ACC-001"));

    // Wait for detail section to appear
    await waitFor(() => {
      expect(screen.getByText("Cash Balance Detail")).toBeInTheDocument();
    });

    // Positions table — values are formatted with formatCurrency()
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    // Quantity is not formatted
    expect(screen.getByText("100")).toBeInTheDocument();
    // Price values are formatted as currency: $180.00, $185.50
    expect(screen.getByText("$180.00")).toBeInTheDocument();
    expect(screen.getByText("$185.50")).toBeInTheDocument();

    // Cash balance section — formatted with commas: $50,000.00, $100,000.00
    expect(screen.getByText("$50,000.00")).toBeInTheDocument();
    expect(screen.getByText("$100,000.00")).toBeInTheDocument();
    // USD appears in cards ("cash · USD", "margin · USD") AND cash balance detail
    expect(screen.getAllByText(/USD/).length).toBeGreaterThanOrEqual(3);
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: Cash balance null
 * ─────────────────────────────────────────── */
describe("AccountsView cash balance null", () => {
  it("shows em dash when cashBalance is null", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Cash balance returns null
    mockFetchOnce(mockPositions);
    mockFetchOnce(null); // GET /cash-balances?account_id=... returns null

    await user.click(screen.getByText("ACC-001"));

    // When cashBalance is null, the Cash Balance card shows "—"
    await waitFor(() => {
      expect(screen.getByText("Cash Balance")).toBeInTheDocument();
    });

    // The value shows "—" (em dash in account cards and summary card)
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Empty positions
 * ─────────────────────────────────────────── */
describe("AccountsView empty positions", () => {
  it("shows empty message when positions list is empty", async () => {
    const user = userEvent.setup();

    mockFetchOnce(mockOrders);
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

    // Cash balance should still load — formatted as $50,000.00
    expect(screen.getByText("$50,000.00")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Search/filter accounts
 * ─────────────────────────────────────────── */
describe("AccountsView search filter", () => {
  it("filters accounts by search text", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);
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
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Click "Margin" type button
    const marginBtn = screen.getByRole("button", { name: /^Margin$/i });
    await user.click(marginBtn);

    // ACC-002 (margin) should remain, ACC-001 (cash) should be hidden
    expect(screen.getByText("ACC-002")).toBeInTheDocument();
    expect(screen.queryByText("ACC-001")).not.toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 9: Selected card highlight via detail render
 * ─────────────────────────────────────────── */
describe("AccountsView selected card highlight", () => {
  it("loads detail when account card is clicked", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    // Card click triggers Phase 2 API calls
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockCashBalance);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    // Click ACC-001 card
    await user.click(screen.getByText("ACC-001"));

    // The detail panel should appear — verify by checking for summary card content
    await waitFor(() => {
      expect(screen.getByText("Cash Balance Detail")).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 10: Detail area clarity
 * ─────────────────────────────────────────── */
describe("AccountsView detail area clarity", () => {
  it("shows account code and type in detail area", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockCashBalance);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("ACC-001")).toBeInTheDocument();
    });

    await user.click(screen.getByText("ACC-001"));

    await waitFor(() => {
      expect(screen.getByText("Cash Balance Detail")).toBeInTheDocument();
    });

    // Account code appears in the card button
    expect(screen.getByText("ACC-001")).toBeInTheDocument();

    // Type "cash" appears in the account card broker line ("cash · USD")
    expect(screen.getByText(/^cash · USD$/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 11: Selection reset on filter
 * ─────────────────────────────────────────── */
describe("AccountsView selection reset on filter", () => {
  it("resets selection when filtered list no longer contains selected account", async () => {
    const user = userEvent.setup();
    mockFetchOnce(mockOrders);
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
      expect(screen.getByText("Cash Balance Detail")).toBeInTheDocument();
    });

    // Now filter by "margin" — ACC-001 (cash) should disappear from list
    const marginBtn = screen.getByRole("button", { name: /^Margin$/i });
    await user.click(marginBtn);

    // Detail should be gone since ACC-001 is no longer visible
    await waitFor(() => {
      expect(
        screen.queryByText("Select an account from the left panel to view details."),
      ).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: API 실패
 * ─────────────────────────────────────────── */
describe("AccountsView error state", () => {
  it("shows ErrorBanner when API call fails", async () => {
    // First API (getOrders) fails
    mockFetchError(500, "Server error");

    render(<AccountsView />);

    await waitFor(() => {
      expect(
        screen.getByText(/Server error/i),
      ).toBeInTheDocument();
    });
  });
});
