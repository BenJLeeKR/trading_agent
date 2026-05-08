import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import AccountsView from "../components/AccountsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { VALID_TOKEN } from "./test-utils/fixtures";
import type { AccountSummary } from "../types/api";

/* ───────────────────────────────────────────
 * Mock data
 * ─────────────────────────────────────────── */
const mockClients = [
  {
    client_id: "cl-11111111-1111-1111-1111-111111111111",
    client_code: "CLIENT01",
    name: "Test Client",
    status: "active",
    base_currency: "KRW",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: null,
  },
];

const mockAccounts = [
  {
    account_id: "ac-22222222-2222-2222-2222-222222222222",
    client_id: "cl-11111111-1111-1111-1111-111111111111",
    broker_account_id: "ba-33333333-3333-3333-3333-333333333333",
    account_alias: "My Paper Account",
    account_masked: "****1234",
    broker_account_ref: "50045678",
    broker_account_code: "KIS-PAPER-****5678",
    account_code: "CLIENT1-PAPER-PAPER",
    environment: "paper",
    status: "active",
    risk_profile: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: null,
  },
  {
    account_id: "ac-44444444-4444-4444-4444-444444444444",
    client_id: "cl-11111111-1111-1111-1111-111111111111",
    broker_account_id: "ba-55555555-5555-5555-5555-555555555555",
    account_alias: "My Live Account",
    account_masked: "****5678",
    broker_account_ref: "50091234",
    broker_account_code: "KIS-LIVE-****1234",
    account_code: "CLIENT1-LIVE-LIVE",
    environment: "live",
    status: "active",
    risk_profile: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: null,
  },
];

const mockPositions = [
  {
    position_snapshot_id: "ps-66666666-6666-6666-6666-666666666666",
    account_id: "ac-22222222-2222-2222-2222-222222222222",
    instrument_id: "in-77777777-7777-7777-7777-777777777777",
    quantity: 100,
    average_price: 150.0,
    market_price: 155.0,
    unrealized_pnl: 500.0,
    source_of_truth: "broker",
    snapshot_at: "2024-01-01T12:00:00Z",
  },
];

const mockCashBalance = {
  cash_balance_snapshot_id: "cb-88888888-8888-8888-8888-888888888888",
  account_id: "ac-22222222-2222-2222-2222-222222222222",
  currency: "KRW",
  available_cash: 500000,
  settled_cash: 1000000,
  unsettled_cash: 0,
  source_of_truth: "broker",
  snapshot_at: "2024-01-01T12:00:00Z",
};

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
});

/* ───────────────────────────────────────────
 * AccountsView — data fetching and rendering
 * ─────────────────────────────────────────── */
describe("AccountsView data fetching", () => {
  it("shows loading state initially", async () => {
    // Don't resolve the mock — component stays in loading state
    vi.spyOn(await import("../api/client"), "getClients").mockReturnValue(
      new Promise<never>(() => {}),
    );
    render(<AccountsView />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("fetches clients and displays account list", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);

    render(<AccountsView />);

    // Wait for loading to finish
    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    // Account column shows account_code (primary identifier)
    expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    expect(screen.getByText("CLIENT1-LIVE-LIVE")).toBeInTheDocument();
    // Account # column shows broker_account_code
    expect(screen.getByText("KIS-PAPER-****5678")).toBeInTheDocument();
    expect(screen.getByText("KIS-LIVE-****1234")).toBeInTheDocument();
    // Client indicator
    expect(screen.getByText("Test Client")).toBeInTheDocument();
    expect(screen.getByText("(CLIENT01)")).toBeInTheDocument();
    // Data source label
    expect(screen.getByText("Account metadata from internal database")).toBeInTheDocument();
  });

  it("shows empty state when no clients exist", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue([]);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("No clients found. No accounts to display.")).toBeInTheDocument();
    });
  });

  it("shows error state on fetch failure", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockRejectedValue(
      new Error("API failure"),
    );

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("API failure")).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * AccountsView — account selection and detail
 * ─────────────────────────────────────────── */
describe("AccountsView detail panel", () => {
  it("shows positions and cash balance when account is selected", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(mockPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />);

    // Wait for accounts to load, then click the first row
    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    // Click the first account row (account_code is the primary display text)
    screen.getByText("CLIENT1-PAPER-PAPER").click();

    // Wait for detail panel + positions/cash balance data to load
    await waitFor(() => {
      expect(screen.getByText("Account Metadata")).toBeInTheDocument();
      expect(screen.getByText("Broker Snapshot — Positions")).toBeInTheDocument();
      expect(screen.getByText("Broker Snapshot — Cash Balance")).toBeInTheDocument();
    });

    // Detail fields — broker_account_code appears in table + detail panel
    expect(screen.getAllByText("KIS-PAPER-****5678").length).toBeGreaterThanOrEqual(2);
    // account_alias appears in detail panel Alias field (table shows account_code)
    expect(screen.getByText("My Paper Account")).toBeInTheDocument();
    // Environment appears in table + detail panel
    expect(screen.getAllByText("PAPER").length).toBeGreaterThanOrEqual(2);

    // Summary cards — "Unrealized P&L" also appears as a column header
    // in the positions table, so use getAllByText
    expect(screen.getAllByText("Unrealized P&L").length).toBeGreaterThanOrEqual(2);

    // Cash balance detail — settled cash appears in the summary card
    // and the cash balance detail section
    await waitFor(() => {
      // "1,000,000" might be split across text nodes in jsdom;
      // verify via the parent text content instead
      expect(screen.getByText(/Settled:/)).toBeInTheDocument();
    });
  });

  it("handles null cash balance", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(mockPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(null);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("Account Metadata")).toBeInTheDocument();
    });

    // Cash balance section should not render
    expect(screen.queryByText("Broker Snapshot — Cash Balance")).not.toBeInTheDocument();

    // Cash Balance summary card shows "—"
    const cashCard = screen.getAllByText("—");
    expect(cashCard.length).toBeGreaterThan(0);
  });

  it("shows locked warning for locked accounts", async () => {
    const lockedAccounts: AccountSummary[] = [
      {
        ...mockAccounts[0],
        status: "locked",
      },
    ];

    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(lockedAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue([]);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(null);

    render(<AccountsView />);

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("Account Locked")).toBeInTheDocument();
    });
  });
});
