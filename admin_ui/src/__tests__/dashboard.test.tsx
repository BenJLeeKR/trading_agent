import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import Dashboard from "../components/Dashboard";
import OperationsDashboardView from "../components/OperationsDashboardView";
import { setStoredToken, clearStoredToken } from "../api/client";
import * as apiClient from "../api/client";
import {
  mockFetchOnce,
  mockFetchNetworkError,
} from "./test-utils/mockFetch";
import {
  mockClients,
  mockAccounts,
  mockAccountsNoPositions,
  mockPositions,
  mockPositionsForLocked,
  mockCashBalance,
  mockCashBalanceForLocked,
  mockCashBalanceNull,
  mockOrders,
  mockReconciliationSummary,
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
 * Scenario 1: 초기 로딩 상태
 * ─────────────────────────────────────────── */
describe("Dashboard loading state", () => {
  it("shows LoadingSpinner on initial render", () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    expect(screen.getByText("로딩 중...")).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 2: 정상 데이터 로드 — 다중 계좌 + orders + reconciliation summary
 * API call sequence:
 *   getClients → getAccounts
 *   → getPositions(3x) + getCashBalance(3x) (parallel)
 *   → getOrders + getReconciliationSummary (parallel)
 * ─────────────────────────────────────────── */
describe("Dashboard with valid data", () => {
  it("renders summary cards with correct metrics", async () => {
    // Mock API calls in order:
    // 1. getClients() → mockClients
    // 2. getAccounts(clientId) → mockAccounts (3 accounts)
    // 3-5. getPositions(accountId) for each of 3 accounts
    // 6-8. getCashBalance(accountId) for each of 3 accounts
    // 9. getOrders() → mockOrders (2 orders)
    // 10. getReconciliationSummary() → mockReconciliationSummary
    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);          // getPositions(a1)
    mockFetchOnce(mockPositionsForLocked); // getPositions(a3)
    mockFetchOnce([]);                     // getPositions(a2)
    mockFetchOnce(mockCashBalance);        // getCashBalance(a1)
    mockFetchOnce(mockCashBalanceForLocked);// getCashBalance(a3)
    mockFetchOnce(mockCashBalanceNull);    // getCashBalance(a2)
    mockFetchOnce(mockOrders);             // getOrders()
    mockFetchOnce(mockReconciliationSummary); // getReconciliationSummary()

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Top 3 account/cash/position cards
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getAllByText("가용 현금").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("포지션").length).toBeGreaterThanOrEqual(1);

    // Restored metric cards — Recent Orders, Active Locks, Incomplete Recon
    // These appear both as metric card titles and section headings, so use getAllByText
    expect(screen.getAllByText("최근 주문").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("활성 잠금").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();

    // Removed metric cards — Paper/Live/Locked Accounts should NOT be present
    expect(screen.queryByText("Paper Accounts")).not.toBeInTheDocument();
    expect(screen.queryByText("Live Accounts")).not.toBeInTheDocument();
    expect(screen.queryByText("Locked Accounts")).not.toBeInTheDocument();

    // Metric values
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1); // Total Accounts = 3
    expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1); // Recent Orders = 2
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1); // Active Locks = 1, Incomplete Recon = 1
    expect(screen.getByText("945,000원")).toBeInTheDocument(); // 45,000 + 900,000
    expect(screen.getByText("45,000원")).toBeInTheDocument(); // a1 quick list orderable_amount
    expect(screen.getByText("900,000원")).toBeInTheDocument(); // a3 quick list orderable_amount

    // Account table rows (3 accounts)
    expect(screen.getByText("Paper Account 1")).toBeInTheDocument();
    expect(screen.getByText("Live Account 1")).toBeInTheDocument();
    expect(screen.getByText("Locked Paper Account")).toBeInTheDocument();

    // Status badges — StatusBadge uses acct.status.toUpperCase() (API field, not translated)
    expect(screen.getAllByText("ACTIVE").length).toBe(2);
    expect(screen.getByText("LOCKED")).toBeInTheDocument();

    // Environment labels
    expect(screen.getAllByText("paper").length).toBe(2);
    expect(screen.getByText("live")).toBeInTheDocument();

    // "View all accounts" navigation button
    expect(screen.getByRole("button", { name: /전체 계좌 보기/ })).toBeInTheDocument();

    // Recent Orders section — shows order rows
    expect(screen.getAllByText("AAPL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    // Active Locks section — shows lock rows
    expect(screen.getByText("Manual review required")).toBeInTheDocument();

    // Freshness indicator — "HH:mm:ss에 업데이트됨" appears in the page header
    expect(screen.getByText(/에 업데이트됨/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 3: 빈 상태 — 계좌 없음
 * ─────────────────────────────────────────── */
describe("Dashboard empty state", () => {
  it("shows empty state when no clients exist", async () => {
    mockFetchOnce([]); // getClients returns empty array
    // fetchAll() may trigger additional fetches during re-render;
    // provide all remaining mocks to prevent queue exhaustion.
    mockFetchOnce([]); // getAccounts
    mockFetchOnce([]); // getPositions (a1)
    mockFetchOnce([]); // getPositions (a3)
    mockFetchOnce([]); // getPositions (a2)
    mockFetchOnce([]); // getCashBalance (a1)
    mockFetchOnce([]); // getCashBalance (a3)
    mockFetchOnce([]); // getCashBalance (a2)
    mockFetchOnce([]); // getOrders
    mockFetchOnce(mockReconciliationSummary); // getReconciliationSummary()

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("계좌가 없습니다")).toBeInTheDocument();
    });

    // Empty state CTA
    expect(
      screen.getByRole("button", { name: /계좌로 이동/ }),
    ).toBeInTheDocument();

    // Freshness indicator also appears in empty state
    expect(screen.getByText(/에 업데이트됨/)).toBeInTheDocument();
  });

  it("shows empty state when clients exist but no accounts", async () => {
    mockFetchOnce(mockClients);  // getClients
    mockFetchOnce([]);           // getAccounts returns empty array
    // When allAccounts is empty, getPositions/getCashBalance are not called.
    // Only getOrders + getReconciliationSummary follow.
    mockFetchOnce([]);                          // getOrders
    mockFetchOnce(mockReconciliationSummary);   // getReconciliationSummary()

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("계좌가 없습니다")).toBeInTheDocument();
    });

    // Freshness indicator also appears in empty state
    expect(screen.getByText(/에 업데이트됨/)).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 4: 에러 상태 (API 실패)
 * ─────────────────────────────────────────── */
describe("Dashboard error state", () => {
  it("shows ErrorBanner when API calls fail", async () => {
    // First API call (getClients) fails with network error
    mockFetchNetworkError();

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        screen.getByText("Network error"),
      ).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * Scenario 5: Navigation links
 * ─────────────────────────────────────────── */
describe("Dashboard navigation links", () => {
  it("renders clickable navigation buttons", async () => {
    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(mockReconciliationSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // "View all accounts" button
    const accountsLink = screen.getByRole("button", { name: /전체 계좌 보기/ });
    expect(accountsLink).toBeInTheDocument();

    // "View all orders" button
    const ordersLink = screen.getByRole("button", { name: /전체 주문 보기/ });
    expect(ordersLink).toBeInTheDocument();

    // "View all locks" button
    const locksLink = screen.getByRole("button", { name: /전체 잠금 보기/ });
    expect(locksLink).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 6: 계좌 없음 — empty state에서 Accounts 이동 버튼
 * ─────────────────────────────────────────── */
describe("Dashboard empty state navigation", () => {
  it("shows Go to Accounts button in empty state", async () => {
    mockFetchOnce([]); // getClients returns empty
    // Provide remaining mocks to prevent queue exhaustion on re-render.
    mockFetchOnce([]); // getAccounts
    mockFetchOnce([]); // getPositions (a1)
    mockFetchOnce([]); // getPositions (a3)
    mockFetchOnce([]); // getPositions (a2)
    mockFetchOnce([]); // getCashBalance (a1)
    mockFetchOnce([]); // getCashBalance (a3)
    mockFetchOnce([]); // getCashBalance (a2)
    mockFetchOnce([]); // getOrders
    mockFetchOnce([]); // getReconciliationLocks
    mockFetchOnce([]); // getReconciliationRuns

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("계좌가 없습니다")).toBeInTheDocument();
    });

    const goButton = screen.getByRole("button", { name: /계좌로 이동/ });
    expect(goButton).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * Scenario 7: Dashboard reconciliation summary variations
 * ─────────────────────────────────────────── */
describe("Dashboard reconciliation StatusCard", () => {
  it("activeIssueCount > 0 → Dashboard renders correctly with warning state", async () => {
    // Create custom reconciliation summary with active issues
    const customSummary = {
      ...mockReconciliationSummary,
      activeIssueCount: 3,
      historicalFailedCount: 5,
    };

    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(customSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Dashboard should still render key metric cards
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getAllByText("가용 현금").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();

    // Metric values should be correct
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1); // Total Accounts = 3
    expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1); // Recent Orders = 2
  });

  it("activeIssueCount === 0 && historicalFailedCount > 0 → Dashboard renders correctly", async () => {
    // Create custom summary: no active issues but historical failures exist
    const customSummary = {
      ...mockReconciliationSummary,
      activeIssueCount: 0,
      historicalFailedCount: 3,
    };

    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(customSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Dashboard renders normally with no reconciliation issues
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();

    // Verify account data still renders
    expect(screen.getByText("Paper Account 1")).toBeInTheDocument();
    expect(screen.getByText("Live Account 1")).toBeInTheDocument();

    // historicalFailedCount는 Dashboard에 표시되지 않아야 함 (activeIssueCount만 기준)
    expect(screen.queryByText(/과거 실패/)).not.toBeInTheDocument();
  });

  it("both activeIssueCount and historicalFailedCount are 0 → Dashboard renders correctly", async () => {
    // Create custom summary: no issues at all
    const customSummary = {
      ...mockReconciliationSummary,
      activeIssueCount: 0,
      historicalFailedCount: 0,
    };

    mockFetchOnce(mockClients);
    mockFetchOnce(mockAccounts);
    mockFetchOnce(mockPositions);
    mockFetchOnce(mockPositionsForLocked);
    mockFetchOnce([]);
    mockFetchOnce(mockCashBalance);
    mockFetchOnce(mockCashBalanceForLocked);
    mockFetchOnce(mockCashBalanceNull);
    mockFetchOnce(mockOrders);
    mockFetchOnce(customSummary);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("개요")).toBeInTheDocument();
    });

    // Dashboard renders normally
    expect(screen.getByText("전체 계좌")).toBeInTheDocument();
    expect(screen.getByText("미완료 정합성")).toBeInTheDocument();
  });
});


/* ───────────────────────────────────────────
 * OperationsDashboardView — 로딩 구조 재배치(4단계 순차 → 독립 effect) 검증
 *
 * 2026-08-22: fetchAll() 하나가 core(health/readyz/reconciliation/summary/
 * orders/clients/session/operations-day) → 계좌 fan-out → snapshot-sync-runs
 * 등 보조 API까지 순차로 묶여 있던 구조를, core 완료만으로 화면 shell을
 * 그리고 계좌 상태/snapshot-sync-runs/buy-block-summary/최근 제출 실패는
 * 각자 독립된 effect로 분리했다. 이 파일의 mock은 이제 호출 "순서"가 아니라
 * "어떤 API가 어떤 값으로 응답하는가"만 지정한다(vi.spyOn(apiClient, ...) —
 * 순서 의존적인 fetch 큐 방식은 독립 effect 구조와 맞지 않는다).
 *
 * "Universe Selection / Market Overlay" 카드에서 쓰던 backend 호출
 * (coverage-summary, market-overlay-funnel, trade-decisions, session-events)
 * 는 이미 예전에 제거됐고, 이번에 "오늘 매수 주문 전환" 카드 자체와
 * freeze-summary(getActiveIntradayFreezeSummary) 호출도 완전히 제거했다.
 * ─────────────────────────────────────────── */

/** Mock health response for OperationsDashboardView */
const mockOpsHealth = {
  status: "ok",
  version: "1.0.0",
  timestamp: "2026-05-30T00:00:00Z",
  database: "connected",
  runtime_mode: "postgres",
  snapshot_sync_detail: null,
  snapshot_sync_stale: null,
  snapshot_sync_last_successful_run_at: null,
  snapshot_sync_consecutive_failures: null,
  scheduler: null,
};

/** Mock readyz response */
const mockReadyz = { "db": "ok", "cache": "ok" };

/** Mock session response */
const mockSessionResponse = {
  status: "ok",
  data: null,
  healthy: true,
  stale_seconds: null,
};

/** Mock operations-day response */
const mockOperationsDayResponse = {
  status: "ok",
  data: {
    operations_day_run_id: 7,
    run_date: "2026-05-30",
    scheduler_status: "intraday",
    is_trading_day: true,
    session_source: "kis_live",
    market_phase: "OPEN",
    pre_market_done: true,
    end_of_day_done: false,
    after_hours_mode: false,
    recovery_batch_done: false,
    submit_count: 2,
    held_position_sell_submit_count: 1,
    cycles: 14,
    last_phase_change_at: "2026-05-30T09:00:00+09:00",
    last_heartbeat_at: "2026-05-30T09:05:00+09:00",
    created_at: "2026-05-30T08:00:00+09:00",
    updated_at: "2026-05-30T09:05:00+09:00",
    summary_json: {
      command_results_count: 4,
      ok_count: 4,
    },
  },
  healthy: true,
  stale_seconds: 4,
};

/** Mock recent failures data (2건: rejected + exception 혼합) */
const mockRecentFailures = [
  {
    order_request_id: "fail-001",
    symbol: "AAPL",
    side: "BUY",
    latest_outcome: "rejected",
    latest_error_type: "INVALID_QUANTITY",
    latest_raw_code: "2011",
    latest_raw_message: "주문 수량이 1주 미만입니다.",
    last_submitted_at: "2026-05-30T14:32:10+09:00",
    created_at: "2026-05-30T14:32:00+09:00",
  },
  {
    order_request_id: "fail-002",
    symbol: "TSLA",
    side: "SELL",
    latest_outcome: "exception",
    latest_error_type: "TIMEOUT",
    latest_raw_code: null,
    latest_raw_message: null,
    last_submitted_at: "2026-05-30T14:33:00+09:00",
    created_at: "2026-05-30T14:33:00+09:00",
  },
];

/** Mock failure summary with data (오늘 2건) */
const mockFailureSummary = {
  last_1h_count: 1,
  last_24h_count: 3,
  rejected_count: 2,
  exception_count: 1,
  total_submissions_24h: 10,
  failure_rate_pct_24h: 30.0,
  today_count: 2,
  rejected_count_today: 1,
  exception_count_today: 1,
  total_submissions_today: 4,
  failure_rate_pct_today: 50.0,
};

/** Mock failure summary with zero failures */
const mockFailureSummaryEmpty = {
  last_1h_count: 0,
  last_24h_count: 0,
  rejected_count: 0,
  exception_count: 0,
  total_submissions_24h: 5,
  failure_rate_pct_24h: 0.0,
  today_count: 0,
  rejected_count_today: 0,
  exception_count_today: 0,
  total_submissions_today: 2,
  failure_rate_pct_today: 0.0,
};

const mockBuyBlockSummary = {
  date: "2026-05-30",
  timezone: "Asia/Seoul",
  total_buy_orders_count: 12,
  buy_submission_attempted_count: 2,
  blocked_count: 1,
  rejected_count: 1,
  exception_count: 0,
};

const mockIndexMembershipStalenessOk = {
  latest_effective_from: "2026-06-27",
  as_of: "2026-07-12",
  age_days: 15,
  threshold_days: 21,
  is_stale: false,
};

/** account_id별 계좌 스냅샷 — 계좌 3개(Paper/Live/Locked) 기준. */
function accountSnapshotFor(accountId: string) {
  if (accountId === mockAccounts[0].account_id) {
    return { positions: mockPositions, cash_balance: mockCashBalance };
  }
  if (accountId === mockAccounts[2].account_id) {
    return { positions: mockPositionsForLocked, cash_balance: mockCashBalanceForLocked };
  }
  return { positions: [], cash_balance: mockCashBalanceNull };
}

/**
 * OperationsDashboardView가 쓰는 API 전부를 기본값으로 mock한다. 이제
 * fetchAll() 하나가 아니라 독립된 여러 effect(core/계좌 상태/snapshot-sync/
 * buy-block-summary/최근 제출 실패)가 각자 fetch하므로, 호출 "순서"가 아니라
 * "함수별 응답"만 지정하면 된다. 개별 테스트는 필요한 함수만 다시
 * spyOn해서 덮어쓸 수 있다.
 */
function mockOpsDashboardCommon() {
  vi.spyOn(apiClient, "getHealth").mockResolvedValue(mockOpsHealth);
  vi.spyOn(apiClient, "getReadyz").mockResolvedValue(mockReadyz);
  vi.spyOn(apiClient, "getReconciliationSummary").mockResolvedValue(mockReconciliationSummary);
  vi.spyOn(apiClient, "getOrders").mockResolvedValue(mockOrders);
  vi.spyOn(apiClient, "getClients").mockResolvedValue(mockClients);
  vi.spyOn(apiClient, "getLatestMarketSession").mockResolvedValue(mockSessionResponse as never);
  vi.spyOn(apiClient, "getLatestOperationsDay").mockResolvedValue(mockOperationsDayResponse as never);
  vi.spyOn(apiClient, "getAccounts").mockResolvedValue(mockAccounts);
  vi.spyOn(apiClient, "getAccountSnapshots").mockImplementation(
    async (accountId: string) => accountSnapshotFor(accountId) as never,
  );
  vi.spyOn(apiClient, "getSnapshotSyncRuns").mockResolvedValue([]);
  vi.spyOn(apiClient, "getIndexMembershipStaleness").mockResolvedValue(mockIndexMembershipStalenessOk);
  vi.spyOn(apiClient, "getBuyBlockSummary").mockResolvedValue(mockBuyBlockSummary);
  vi.spyOn(apiClient, "getRecentFailures").mockResolvedValue([]);
  vi.spyOn(apiClient, "getFailureSummary").mockResolvedValue(mockFailureSummaryEmpty);
}

function renderOpsDashboard() {
  return render(
    <MemoryRouter>
      <OperationsDashboardView />
    </MemoryRouter>,
  );
}

describe("OperationsDashboardView — 상단 카드 구성", () => {
  it("상단 요약 카드에는 지정된 6개 항목만 남고, 제거된 카드는 보이지 않는다", async () => {
    mockOpsDashboardCommon();

    renderOpsDashboard();

    await screen.findByText("Ready 상태");
    expect(screen.getByText("Scheduler Status")).toBeInTheDocument();
    expect(screen.getByText("마지막 스냅샷 동기화")).toBeInTheDocument();
    expect(screen.getByText("운영 경고")).toBeInTheDocument();
    expect(screen.getByText("오늘 BUY 차단")).toBeInTheDocument();
    expect(await screen.findByText("최근 제출 실패")).toBeInTheDocument();

    // 상단 카드에서 제거된 항목들 — "오늘 주문 제출"은 삭제, "가용 현금"/
    // "현재 포지션"은 계좌 상태 영역으로 이동했으므로 상단 카드 타이틀로는
    // 더 이상 나타나지 않는다("계좌 상태" 섹션 안에는 별도로 나타난다).
    expect(screen.queryByText("오늘 주문 제출")).not.toBeInTheDocument();
  });

  it("계좌 상태 영역에 총자산/가용 현금/현재 포지션이 표시된다", async () => {
    mockOpsDashboardCommon();

    renderOpsDashboard();

    await screen.findByText("계좌 상태");
    await screen.findByText("총자산");
    expect(screen.getByText("가용 현금")).toBeInTheDocument();
    expect(screen.getByText("현재 포지션")).toBeInTheDocument();
    // 가용 현금 합계(45,000 + 900,000) — 기존 계좌 카드와 동일한 계산 로직 유지 확인.
    expect(screen.getByText("945,000원")).toBeInTheDocument();
  });

  it("오늘 매수 주문 전환 영역은 완전히 제거됐다", async () => {
    mockOpsDashboardCommon();

    renderOpsDashboard();

    await screen.findByText("Ready 상태");
    expect(screen.queryByText("오늘 매수 주문 전환")).not.toBeInTheDocument();
    expect(screen.queryByText("Universe Selection / Market Overlay")).not.toBeInTheDocument();
  });

  it("freeze-summary API는 더 이상 호출되지 않는다", async () => {
    mockOpsDashboardCommon();
    const freezeSpy = vi.spyOn(apiClient, "getActiveIntradayFreezeSummary");

    renderOpsDashboard();

    await screen.findByText("계좌 상태");
    await screen.findByText("총자산");
    expect(freezeSpy).not.toHaveBeenCalled();
  });
});

describe("OperationsDashboardView — 로딩 게이트 축소", () => {
  it("core(7개 API)만 끝나면 화면 shell과 상단 카드를 그린다 — 보조 API가 아직 응답하지 않아도 된다", async () => {
    mockOpsDashboardCommon();
    // buy-block-summary/최근 제출 실패/snapshot-sync-runs를 영원히 pending
    // 상태로 묶어둔다 — 그런데도 화면 shell(상단 카드 타이틀들)은 렌더링돼야
    // core 완료만으로 loading이 풀린다는 것이 증명된다.
    vi.spyOn(apiClient, "getBuyBlockSummary").mockReturnValue(new Promise(() => {}));
    vi.spyOn(apiClient, "getFailureSummary").mockReturnValue(new Promise(() => {}));
    vi.spyOn(apiClient, "getRecentFailures").mockReturnValue(new Promise(() => {}));
    vi.spyOn(apiClient, "getSnapshotSyncRuns").mockReturnValue(new Promise(() => {}));

    renderOpsDashboard();

    await screen.findByText("Ready 상태");
    // 아직 응답하지 않은 카드들은 "로딩 중"으로 남아 있다(화면 전체가 막힌 게 아님).
    expect(screen.getByText("마지막 스냅샷 동기화").closest("div")).toBeTruthy();
    const buyBlockLoading = screen.getAllByText("로딩 중...");
    expect(buyBlockLoading.length).toBeGreaterThan(0);
  });
});

describe("OperationsDashboardView — 최근 제출 실패 상태 표현", () => {
  it("최근 제출 실패 API 실패가 전체 대시보드 로딩 실패로 번지지 않는다", async () => {
    mockOpsDashboardCommon();
    vi.spyOn(apiClient, "getRecentFailures").mockRejectedValue(new Error("Network error"));
    vi.spyOn(apiClient, "getFailureSummary").mockRejectedValue(new Error("Network error"));

    renderOpsDashboard();

    // core는 정상 응답이므로 화면 shell 자체는 정상적으로 그려진다(에러
    // 화면으로 전체가 대체되지 않음).
    await screen.findByText("Ready 상태");
    await screen.findByText("계좌 상태");

    // "최근 제출 실패" 카드만 오류로 표시된다.
    await waitFor(() => {
      expect(screen.getAllByText("오류").length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/API 오류: Error: Network error/)).toBeInTheDocument();
  });

  it("renders recent submission failures card with data", async () => {
    mockOpsDashboardCommon();
    vi.spyOn(apiClient, "getRecentFailures").mockResolvedValue(mockRecentFailures as never);
    vi.spyOn(apiClient, "getFailureSummary").mockResolvedValue(mockFailureSummary as never);

    renderOpsDashboard();

    await screen.findByText("오늘 2건");
    expect(screen.getByText("Scheduler Status")).toBeInTheDocument();
    expect(screen.getAllByText("운영중").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/OPEN \| 제출 2 \/ HP매도 1 \/ cycles 14/)).toBeInTheDocument();
    expect(screen.getByText("오늘 BUY 차단")).toBeInTheDocument();
    expect(screen.getAllByText("1건").length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText(/실패율: 50% \(오늘\) \| 거절 1건 · 예외 1건/)).toBeInTheDocument();

    const symbols = screen.getAllByText("AAPL");
    expect(symbols.length).toBeGreaterThanOrEqual(1);
    const tslaSymbols = screen.getAllByText("TSLA");
    expect(tslaSymbols.length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Exception")).toBeInTheDocument();
    expect(screen.getByText("INVALID_QUANTITY")).toBeInTheDocument();
    expect(screen.getByText("TIMEOUT")).toBeInTheDocument();
    expect(screen.getByText("[2011]")).toBeInTheDocument();
    expect(screen.getByText(/주문 수량이 1주 미만입니다/)).toBeInTheDocument();

    const errorTypeSpan = screen.getByText(/INVALID_QUANTITY/).closest('span');
    expect(errorTypeSpan).toHaveAttribute('title', '주문 수량이 1주 미만입니다.');

    expect(screen.getByText("모든 실패 주문 보기 →")).toBeInTheDocument();
    const submissionLinks = screen.getAllByText("제출 이력 보기 →");
    expect(submissionLinks.length).toBe(2);
    expect(submissionLinks[0].closest('a')).toHaveAttribute(
      'href',
      '/orders/fail-001/submission-attempts'
    );
    expect(submissionLinks[1].closest('a')).toHaveAttribute(
      'href',
      '/orders/fail-002/submission-attempts'
    );
  });

  it("renders empty state when no failures", async () => {
    mockOpsDashboardCommon();

    renderOpsDashboard();

    await screen.findByText("오늘 0건");
    expect(screen.getByText(/실패율: 0% \(오늘\) \| 거절 0건 · 예외 0건/)).toBeInTheDocument();
  });

  it("renders failure summary with zero failures — neutral status", async () => {
    mockOpsDashboardCommon();

    renderOpsDashboard();

    await screen.findByText("오늘 0건");
    expect(screen.getByText(/실패율: 0% \(오늘\) \| 거절 0건 · 예외 0건/)).toBeInTheDocument();
    expect(screen.queryByText("Rejected")).not.toBeInTheDocument();
  });

  it("renders failure summary with 1h errors — error status", async () => {
    mockOpsDashboardCommon();
    vi.spyOn(apiClient, "getRecentFailures").mockResolvedValue(mockRecentFailures as never);
    vi.spyOn(apiClient, "getFailureSummary").mockResolvedValue({
      last_1h_count: 2,
      last_24h_count: 5,
      rejected_count: 3,
      exception_count: 2,
      total_submissions_24h: 20,
      failure_rate_pct_24h: 25.0,
      today_count: 4,
      rejected_count_today: 2,
      exception_count_today: 2,
      total_submissions_today: 8,
      failure_rate_pct_today: 50.0,
    } as never);

    renderOpsDashboard();

    await screen.findByText("오늘 4건");
    expect(screen.getByText(/실패율: 50% \(오늘\) \| 거절 2건 · 예외 2건/)).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Exception")).toBeInTheDocument();
  });
});

describe("OperationsDashboardView — 오늘 BUY 차단 상태 표현", () => {
  it("BUY 차단 API 실패는 오류로 표시되고 0건처럼 보이지 않는다", async () => {
    mockOpsDashboardCommon();
    vi.spyOn(apiClient, "getBuyBlockSummary").mockRejectedValue(new Error("Network error"));

    renderOpsDashboard();

    await screen.findByText("오늘 BUY 차단");
    await waitFor(() => {
      expect(screen.getByText(/API 오류: Error: Network error/)).toBeInTheDocument();
    });
    // "0건"이 아니라 명시적 오류 문구여야 한다.
    const buyBlockCard = screen.getByText("오늘 BUY 차단").closest("div")!.parentElement!;
    expect(buyBlockCard.textContent).not.toContain("0건");
  });
});

describe("OperationsDashboardView — 계좌 상태 부분/전체 실패", () => {
  it("계좌 스냅샷 일부 실패는 계좌 상태 영역에서 부분 실패로 표시된다(성공한 계좌만 반영)", async () => {
    mockOpsDashboardCommon();
    vi.spyOn(apiClient, "getAccountSnapshots").mockImplementation(async (accountId: string) => {
      if (accountId === mockAccounts[1].account_id) {
        throw new Error("스냅샷 조회 실패");
      }
      return accountSnapshotFor(accountId) as never;
    });

    renderOpsDashboard();

    await screen.findByText("계좌 상태");
    await waitFor(() => {
      expect(screen.getByText(/일부 계좌\(1개\) 스냅샷 조회 실패/)).toBeInTheDocument();
    });
    // 성공한 계좌(a1) 기준 총자산/포지션은 여전히 표시된다("0건"으로 뭉개지지 않음).
    expect(screen.getByText("총자산")).toBeInTheDocument();
  });

  it("계좌 목록 자체를 못 가져오면(클라이언트 조회 실패) 전체 실패로 명확히 표시된다", async () => {
    mockOpsDashboardCommon();
    vi.spyOn(apiClient, "getClients").mockRejectedValue(new Error("Network error"));

    renderOpsDashboard();

    await screen.findByText("계좌 상태");
    await waitFor(() => {
      expect(screen.getByText(/계좌 목록을 불러오지 못했습니다/)).toBeInTheDocument();
    });
  });
});
