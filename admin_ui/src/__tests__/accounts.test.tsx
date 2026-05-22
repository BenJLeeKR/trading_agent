import { render, screen, waitFor, fireEvent, act, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import AccountsView from "../components/AccountsView";
import { setStoredToken, clearStoredToken } from "../api/client";
import { VALID_TOKEN } from "./test-utils/fixtures";
import type { AccountSummary } from "../types/api";
import type { ReactNode } from "react";

/** Wraps component in MemoryRouter so useNavigate() works. */
function RouterWrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

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
    purchase_amount: 15000.0,
    evaluation_amount: 15500.0,
    source_of_truth: "broker",
    snapshot_at: "2024-01-01T12:00:00Z",
    symbol: "AAPL",
    instrument_name: "Apple Inc.",
  },
];

const mockCashBalance = {
  cash_balance_snapshot_id: "cb-88888888-8888-8888-8888-888888888888",
  account_id: "ac-22222222-2222-2222-2222-222222222222",
  currency: "USD",
  available_cash: 500000,
  settled_cash: 1000000,
  unsettled_cash: 0,
  // ── KIS output2 계좌 총괄 필드 (optional, fallback 지원) ──
  total_asset: 1550000,
  settlement_amount: 980000,
  total_unrealized_pnl: 500,
  source_of_truth: "broker",
  snapshot_at: "2024-01-01T12:00:00Z",
};

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
  cleanup();
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
    render(<AccountsView />, { wrapper: RouterWrapper });
    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
  });

  it("fetches clients and displays account list", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);

    render(<AccountsView />, { wrapper: RouterWrapper });

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
    expect(screen.getByText("내부 데이터베이스 계좌 메타데이터")).toBeInTheDocument();
  });

  it("shows empty state when no clients exist", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue([]);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("클라이언트가 없습니다. 표시할 계좌가 없습니다.")).toBeInTheDocument();
    });
  });

  it("shows error state on fetch failure", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockRejectedValue(
      new Error("API failure"),
    );

    render(<AccountsView />, { wrapper: RouterWrapper });

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

    render(<AccountsView />, { wrapper: RouterWrapper });

    // Wait for accounts to load, then click the first row
    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    // Click the first account row (account_code is the primary display text)
    screen.getByText("CLIENT1-PAPER-PAPER").click();

    // Wait for detail panel + positions/cash balance data to load
    await waitFor(() => {
      expect(screen.getByText("계좌 메타데이터")).toBeInTheDocument();
      expect(screen.getByText("브로커 스냅샷 — 포지션")).toBeInTheDocument();
      expect(screen.getByText("브로커 스냅샷 — 현금 잔고")).toBeInTheDocument();
    });

    // Detail fields — broker_account_code appears in table + detail panel
    expect(screen.getAllByText("KIS-PAPER-****5678").length).toBeGreaterThanOrEqual(2);
    // account_alias appears in detail panel Alias field (table shows account_code)
    expect(screen.getByText("My Paper Account")).toBeInTheDocument();
    // Environment appears in table + detail panel
    expect(screen.getAllByText("PAPER").length).toBeGreaterThanOrEqual(2);

    // Summary cards — "미실현 손익" also appears as a column header
    // in the positions table, so use getAllByText
    expect(screen.getAllByText("미실현 손익").length).toBeGreaterThanOrEqual(2);

    // Cash balance detail — settled cash appears in the summary card
    // and the cash balance detail section
    await waitFor(() => {
      // "1,000,000" might be split across text nodes in jsdom;
      // verify via the parent text content instead
      expect(screen.getByText(/결제완료:/)).toBeInTheDocument();
    });

    // Freshness indicator — "스냅샷:" with formatted timestamp appears
    // in both Cash Balance header and Positions header.
    // mock data has snapshot_at: "2024-01-01T12:00:00Z".
    // Output now includes timezone offset + elapsed time, e.g.:
    //   "스냅샷: 2024-01-01 12:00:00 UTC+00:00 (약 863일 전)"
    // Two elements match (Cash Balance + Positions), so use getAllByText
    expect(screen.getAllByText(/^스냅샷:/).length).toBe(2);
  });

  it("handles null cash balance", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(mockPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(null);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("계좌 메타데이터")).toBeInTheDocument();
    });

    // Cash balance section should not render
    expect(screen.queryByText("브로커 스냅샷 — 현금 잔고")).not.toBeInTheDocument();

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

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("계좌 잠금")).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * AccountsView — snapshot dedup and history toggle
 * ─────────────────────────────────────────── */
describe("AccountsView snapshot dedup", () => {
  const multiSnapshotPositions = [
    {
      position_snapshot_id: "ps-1111-aaaa",
      account_id: "ac-22222222-2222-2222-2222-222222222222",
      instrument_id: "in-77777777-7777-7777-7777-777777777777",
      quantity: 100,
      average_price: 150.0,
      market_price: 155.0,
      unrealized_pnl: 500.0,
      purchase_amount: null,
      evaluation_amount: null,
      source_of_truth: "broker",
      snapshot_at: "2024-01-01T10:00:00Z",
      symbol: "AAPL",
      instrument_name: "Apple Inc.",
    },
    {
      position_snapshot_id: "ps-1111-bbbb",
      account_id: "ac-22222222-2222-2222-2222-222222222222",
      instrument_id: "in-77777777-7777-7777-7777-777777777777",
      quantity: 100,
      average_price: 150.0,
      market_price: 160.0,
      unrealized_pnl: 1000.0,
      purchase_amount: null,
      evaluation_amount: null,
      source_of_truth: "broker",
      snapshot_at: "2024-01-01T12:00:00Z",
      symbol: "AAPL",
      instrument_name: "Apple Inc.",
    },
    {
      position_snapshot_id: "ps-2222-aaaa",
      account_id: "ac-22222222-2222-2222-2222-222222222222",
      instrument_id: "in-88888888-8888-8888-8888-888888888888",
      quantity: 50,
      average_price: 250.0,
      market_price: 245.0,
      unrealized_pnl: -250.0,
      purchase_amount: null,
      evaluation_amount: null,
      source_of_truth: "broker",
      snapshot_at: "2024-01-01T10:00:00Z",
      symbol: "MSFT",
      instrument_name: "Microsoft Corporation",
    },
  ];

  it("shows only latest snapshot per instrument by default", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(multiSnapshotPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    // Wait for positions to load
    await waitFor(() => {
      expect(screen.getByText("브로커 스냅샷 — 포지션")).toBeInTheDocument();
    });

    // Default: only latest snapshot per instrument (2 rows: AAPL latest + MSFT)
    // AAPL latest has snapshot_at 12:00, MSFT has 10:00
    // Both should be visible as rows
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();

    // The older AAPL snapshot (10:00) should NOT be visible by default
    // Since both snapshots have same quantity/price, we verify by checking
    // that only 2 position rows are rendered (not 3)
    // DataTable renders rows inside tbody; we check AAPL appears once
    const aaplElements = screen.getAllByText("AAPL");
    expect(aaplElements.length).toBe(1);
  });

  it("shows toggle button when snapshot history exists", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(multiSnapshotPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("스냅샷 이력 보기 (3건)")).toBeInTheDocument();
    });
  });

  it("toggle shows all snapshots when activated", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(multiSnapshotPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("스냅샷 이력 보기 (3건)")).toBeInTheDocument();
    });

    // Click toggle to show all snapshots
    screen.getByText("스냅샷 이력 보기 (3건)").click();

    // Now all 3 snapshots should be visible
    // AAPL appears twice (10:00 + 12:00), MSFT once
    await waitFor(() => {
      const aaplElements = screen.getAllByText("AAPL");
      expect(aaplElements.length).toBe(2);
    });

    // Toggle text should change to "최신 포지션만 보기"
    expect(screen.getByText("최신 포지션만 보기")).toBeInTheDocument();
  });

  it("hides toggle when no snapshot history exists", async () => {
    // Single snapshot per instrument — no history to show
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(mockPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("브로커 스냅샷 — 포지션")).toBeInTheDocument();
    });

    // Toggle should NOT be present
    expect(screen.queryByText(/스냅샷 이력 보기/)).not.toBeInTheDocument();
    expect(screen.queryByText("최신 포지션만 보기")).not.toBeInTheDocument();
  });

  it("shows 관련 주문 보기 button for each position row", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(mockPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("브로커 스냅샷 — 포지션")).toBeInTheDocument();
    });

    // "관련 주문 보기 →" button should be visible
    expect(screen.getByText(/관련 주문 보기/)).toBeInTheDocument();
  });

  it("summary cards use dedup data not raw positions", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(multiSnapshotPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    // Wait for account list to render, then select first account
    await screen.findByText("CLIENT1-PAPER-PAPER", {}, { timeout: 3000 });

    // Click the table row containing the account text
    const accountRow = screen.getByText("CLIENT1-PAPER-PAPER").closest("tr");
    expect(accountRow).not.toBeNull();
    await act(async () => {
      fireEvent.click(accountRow!);
    });

    // Wait for positions table to render (confirms detail panel is open)
    expect(await screen.findByText("AAPL", {}, { timeout: 3000 })).toBeInTheDocument();

    // multiSnapshotPositions has 3 snapshots:
    //   AAPL (10:00): unrealized_pnl=500,  qty=100, market_price=155
    //   AAPL (12:00): unrealized_pnl=1000, qty=100, market_price=160  ← latest
    //   MSFT (10:00): unrealized_pnl=-250, qty=50,  market_price=245  ← latest
    //
    // KIS 우선: mockCashBalance.total_asset = 1550000
    //           mockCashBalance.total_unrealized_pnl = 500
    //           mockCashBalance.settlement_amount = 980000
    //
    // formatKrw(1550000) → "1,550,000원"
    // formatKrw(500) → "+500원" (totalPnl >= 0 이므로 "+" prefix)

    // Verify totalValue shows KIS total_asset (1,550,000), not dedup-based calculation
    expect(await screen.findByText("1,550,000원", { exact: false }, { timeout: 3000 })).toBeInTheDocument();

    // Verify totalPnl shows KIS total_unrealized_pnl (500), not dedup sum (750)
    expect(await screen.findByText("+500원", { exact: false }, { timeout: 3000 })).toBeInTheDocument();

    // Toggle to history view — summary cards should STAY on latest data
    screen.getByText("스냅샷 이력 보기 (3건)").click();

    await waitFor(() => {
      expect(screen.getByText("최신 포지션만 보기")).toBeInTheDocument();
    });

    // Summary values unchanged even in history mode
    expect(screen.getByText("1,550,000원", { exact: false })).toBeInTheDocument();
    // "+500원" appears in summary card AND positions table → use getAllByText
    expect(screen.getAllByText("+500원", { exact: false }).length).toBeGreaterThanOrEqual(1);
  });

  it("falls back to calculated values when KIS fields are undefined", async () => {
    const cashBalanceWithoutKis = {
      ...mockCashBalance,
      total_asset: undefined,
      settlement_amount: undefined,
      total_unrealized_pnl: undefined,
    };

    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(multiSnapshotPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(cashBalanceWithoutKis);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await screen.findByText("CLIENT1-PAPER-PAPER", {}, { timeout: 3000 });

    const accountRow = screen.getByText("CLIENT1-PAPER-PAPER").closest("tr");
    expect(accountRow).not.toBeNull();
    await act(async () => {
      fireEvent.click(accountRow!);
    });

    expect(await screen.findByText("AAPL", {}, { timeout: 3000 })).toBeInTheDocument();

    // KIS 필드가 undefined이므로 fallback 계산 사용:
    //   totalPnl = 1000 + (-250) = 750
    //   totalValue = (100*160 + 50*245) + 1000000 = 16000 + 12250 + 1000000 = 1028250
    //   현금잔고 = settled_cash = 1000000
    //
    // formatKrw(750) → "+750원" (totalPnl >= 0 이므로 "+" prefix)
    // formatKrw(1028250) → "1,028,250원"

    expect(await screen.findByText("+750원", { exact: false }, { timeout: 3000 })).toBeInTheDocument();
    expect(await screen.findByText("1,028,250원", { exact: false }, { timeout: 3000 })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * AccountsView — zero-quantity position filter
 * ─────────────────────────────────────────── */
describe("AccountsView zero-quantity position filter", () => {
  const positionsWithZeroQty = [
    {
      position_snapshot_id: "ps-zero-aaaa",
      account_id: "ac-22222222-2222-2222-2222-222222222222",
      instrument_id: "in-77777777-7777-7777-7777-777777777777",
      quantity: 100,
      average_price: 150.0,
      market_price: 155.0,
      unrealized_pnl: 500.0,
      purchase_amount: 15000.0,
      evaluation_amount: 15500.0,
      source_of_truth: "broker",
      snapshot_at: "2024-01-01T12:00:00Z",
      symbol: "AAPL",
      instrument_name: "Apple Inc.",
    },
    {
      position_snapshot_id: "ps-zero-bbbb",
      account_id: "ac-22222222-2222-2222-2222-222222222222",
      instrument_id: "in-88888888-8888-8888-8888-888888888888",
      quantity: 0, // 전량 매도되어 수량 0
      average_price: 250.0,
      market_price: 245.0,
      unrealized_pnl: 0.0,
      purchase_amount: null,
      evaluation_amount: null,
      source_of_truth: "broker",
      snapshot_at: "2024-01-01T12:00:00Z",
      symbol: "MSFT",
      instrument_name: "Microsoft Corporation",
    },
    {
      position_snapshot_id: "ps-zero-cccc",
      account_id: "ac-22222222-2222-2222-2222-222222222222",
      instrument_id: "in-99999999-9999-9999-9999-999999999999",
      quantity: 0, // 전량 매도되어 수량 0
      average_price: 50000.0,
      market_price: 51000.0,
      unrealized_pnl: 0.0,
      purchase_amount: null,
      evaluation_amount: null,
      source_of_truth: "broker",
      snapshot_at: "2024-01-01T12:00:00Z",
      symbol: "TSLA",
      instrument_name: "Tesla Inc.",
    },
  ];

  it("hides zero-quantity positions in default latest view", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(positionsWithZeroQty);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    // Wait for positions to load
    await waitFor(() => {
      expect(screen.getByText("브로커 스냅샷 — 포지션")).toBeInTheDocument();
    });

    // AAPL (quantity=100)은 표시되어야 함
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    // MSFT (quantity=0)은 기본 뷰에서 숨겨져야 함
    expect(screen.queryByText("MSFT")).not.toBeInTheDocument();

    // TSLA (quantity=0)도 기본 뷰에서 숨겨져야 함
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();

    // 수량 0이 아닌 종목만 표시되므로 1개 row만 있어야 함
    const symbolElements = screen.getAllByText("AAPL");
    expect(symbolElements.length).toBe(1);
  });

  it("shows quantity>0 positions normally", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(positionsWithZeroQty);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("브로커 스냅샷 — 포지션")).toBeInTheDocument();
    });

    // AAPL (quantity=100)은 정상 표시
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    // AAPL의 수량 100이 표시되어야 함
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("shows zero-quantity positions in snapshot history mode", async () => {
    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(positionsWithZeroQty);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    await waitFor(() => {
      expect(screen.getByText("스냅샷 이력 보기 (3건)")).toBeInTheDocument();
    });

    // 기본 뷰에서는 MSFT가 보이지 않음
    expect(screen.queryByText("MSFT")).not.toBeInTheDocument();

    // 스냅샷 이력 보기로 전환
    screen.getByText("스냅샷 이력 보기 (3건)").click();

    // 이력 모드에서는 MSFT (quantity=0)도 표시되어야 함
    await waitFor(() => {
      expect(screen.getByText("MSFT")).toBeInTheDocument();
    });

    // 이력 모드에서는 TSLA (quantity=0)도 표시되어야 함
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // 이력 모드에서는 AAPL도 당연히 표시
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    // 토글 텍스트 변경 확인
    expect(screen.getByText("최신 포지션만 보기")).toBeInTheDocument();
  });

  it("shows empty message when all positions have zero quantity", async () => {
    const allZeroPositions = positionsWithZeroQty.filter(p => p.quantity === 0);

    vi.spyOn(await import("../api/client"), "getClients").mockResolvedValue(mockClients);
    vi.spyOn(await import("../api/client"), "getAccounts").mockResolvedValue(mockAccounts);
    vi.spyOn(await import("../api/client"), "getPositions").mockResolvedValue(allZeroPositions);
    vi.spyOn(await import("../api/client"), "getCashBalance").mockResolvedValue(mockCashBalance);

    render(<AccountsView />, { wrapper: RouterWrapper });

    await waitFor(() => {
      expect(screen.getByText("CLIENT1-PAPER-PAPER")).toBeInTheDocument();
    });

    screen.getByText("CLIENT1-PAPER-PAPER").click();

    // 모든 포지션이 수량 0이므로 빈 상태 메시지 표시
    await waitFor(() => {
      expect(screen.getByText("이 계좌의 포지션이 없습니다.")).toBeInTheDocument();
    });
  });
});
