import { render, screen, waitFor, fireEvent, act, cleanup } from "@testing-library/react";
import { describe, expect, it, afterEach, vi, beforeEach } from "vitest";
import RealizedPnlView from "../components/RealizedPnlView";
import { setStoredToken, clearStoredToken } from "../api/client";
import * as apiClient from "../api/client";
import { VALID_TOKEN, mockClients, mockAccounts } from "./test-utils/fixtures";
import type {
  RealizedPnlPositionView,
  RealizedPnlSummaryResponse,
  RealizedPnlDailyResponse,
  RealizedPnlEventsResponse,
  RealizedPnlEventView,
  RealizedPnlRecomputeQueueResponse,
} from "../types/api";

/* ───────────────────────────────────────────
 * Mock data — realized PnL
 * ─────────────────────────────────────────── */
const ACCOUNT_ID = mockAccounts[0].account_id;
const INSTRUMENT_A = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i1";
const INSTRUMENT_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00i2";

const mockPositions: RealizedPnlPositionView[] = [
  {
    account_id: ACCOUNT_ID,
    instrument_id: INSTRUMENT_A,
    symbol: "005930",
    instrument_name: "삼성전자",
    position_quantity: 10,
    average_cost: 70000,
    recompute_required: false,
    recompute_reason: null,
    realized_pnl_net_cumulative: 500000,
    updated_at: "2026-08-01T00:00:00Z",
  },
  {
    account_id: ACCOUNT_ID,
    instrument_id: INSTRUMENT_B,
    symbol: "000660",
    instrument_name: "SK하이닉스",
    position_quantity: 0,
    average_cost: 120000,
    recompute_required: true,
    recompute_reason: "out_of_order_fill",
    realized_pnl_net_cumulative: -20000,
    updated_at: "2026-08-02T00:00:00Z",
  },
];

const mockSummaryAllInstruments: RealizedPnlSummaryResponse = {
  account_id: ACCOUNT_ID,
  instrument_id: null,
  start_date: "2026-07-01",
  end_date: "2026-08-05",
  realized_pnl_net_sum: 130000,
  sell_event_count: 3,
  buy_amount_sum: 1000000,
  sell_amount_sum: 1130000,
  fee_tax_sum: 15000,
  recompute_pending_count: 1,
  by_instrument: [
    {
      instrument_id: INSTRUMENT_A,
      symbol: "005930",
      instrument_name: "삼성전자",
      realized_pnl_net_sum: 150000,
      sell_event_count: 2,
      buy_amount_sum: 800000,
      sell_amount_sum: 950000,
      fee_tax_sum: 10000,
      recompute_required: false,
    },
    {
      instrument_id: INSTRUMENT_B,
      symbol: "000660",
      instrument_name: "SK하이닉스",
      realized_pnl_net_sum: -20000,
      sell_event_count: 1,
      buy_amount_sum: 200000,
      sell_amount_sum: 180000,
      fee_tax_sum: 5000,
      recompute_required: true,
    },
  ],
};

const mockSummaryNoRecompute: RealizedPnlSummaryResponse = {
  ...mockSummaryAllInstruments,
  recompute_pending_count: 0,
  by_instrument: mockSummaryAllInstruments.by_instrument.map((row) => ({
    ...row,
    recompute_required: false,
  })),
};

const mockSummaryEmpty: RealizedPnlSummaryResponse = {
  account_id: ACCOUNT_ID,
  instrument_id: null,
  start_date: "2026-07-01",
  end_date: "2026-08-05",
  realized_pnl_net_sum: 0,
  sell_event_count: 0,
  buy_amount_sum: 0,
  sell_amount_sum: 0,
  fee_tax_sum: 0,
  recompute_pending_count: 0,
  by_instrument: [],
};

const mockSummarySingleInstrument: RealizedPnlSummaryResponse = {
  account_id: ACCOUNT_ID,
  instrument_id: INSTRUMENT_A,
  start_date: "2026-07-01",
  end_date: "2026-08-05",
  realized_pnl_net_sum: 150000,
  sell_event_count: 2,
  buy_amount_sum: 800000,
  sell_amount_sum: 950000,
  fee_tax_sum: 10000,
  recompute_pending_count: 0,
  by_instrument: [
    {
      instrument_id: INSTRUMENT_A,
      symbol: "005930",
      instrument_name: "삼성전자",
      realized_pnl_net_sum: 150000,
      sell_event_count: 2,
      buy_amount_sum: 800000,
      sell_amount_sum: 950000,
      fee_tax_sum: 10000,
      recompute_required: false,
    },
  ],
};

function makeDailyResponse(instrumentId: string): RealizedPnlDailyResponse {
  return {
    account_id: ACCOUNT_ID,
    instrument_id: instrumentId,
    start_date: "2026-07-01",
    end_date: "2026-08-05",
    daily: [
      {
        trade_date: "2026-08-01",
        realized_pnl_net_sum: 150000,
        sell_event_count: 2,
        buy_amount_sum: 800000,
        sell_amount_sum: 950000,
        fee_tax_sum: 10000,
      },
    ],
  };
}

function makeEvent(overrides?: Partial<RealizedPnlEventView>): RealizedPnlEventView {
  return {
    realized_pnl_event_id: "evt-1",
    account_id: ACCOUNT_ID,
    instrument_id: INSTRUMENT_A,
    fill_event_id: "fill-1",
    broker_order_id: "bo-1",
    order_request_id: "or-1",
    sell_quantity: 5,
    sell_price: 75000,
    avg_cost_basis_before: 70000,
    fee: 300,
    tax: 200,
    fee_tax_source: "reported",
    realized_pnl_gross: 25000,
    realized_pnl_net: 24500,
    position_quantity_after: 5,
    fill_timestamp: "2026-08-01T01:00:00Z",
    ...overrides,
  };
}

const mockRecomputeQueueWithItem: RealizedPnlRecomputeQueueResponse = {
  account_id: ACCOUNT_ID,
  instrument_id: null,
  limit: 100,
  items: [
    {
      recompute_queue_id: "queue-1",
      account_id: ACCOUNT_ID,
      instrument_id: INSTRUMENT_B,
      reason_code: "out_of_order_fill",
      triggering_fill_event_id: "fill-99",
      requested_at: "2026-08-02T03:00:00Z",
    },
  ],
};

const mockRecomputeQueueEmpty: RealizedPnlRecomputeQueueResponse = {
  account_id: ACCOUNT_ID,
  instrument_id: null,
  limit: 100,
  items: [],
};

const mockEventsSinglePage: RealizedPnlEventsResponse = {
  account_id: ACCOUNT_ID,
  instrument_id: INSTRUMENT_A,
  limit: 200,
  before: null,
  events: [makeEvent()],
};

/* ───────────────────────────────────────────
 * Shared setup helpers
 * ─────────────────────────────────────────── */

/** Stub the account-loading path (getDefaultClient → getClients → getAccounts). */
function mockAccountLoading() {
  vi.spyOn(apiClient, "getDefaultClient").mockResolvedValue(null);
  vi.spyOn(apiClient, "getClients").mockResolvedValue(mockClients);
  vi.spyOn(apiClient, "getAccounts").mockResolvedValue(mockAccounts);
}

const ACCOUNT_OPTION_LABEL = "CLIENT1-PAPER-PAPER · Paper Account 1 · ****1234";

async function selectAccount() {
  await waitFor(() => {
    expect(screen.getByRole("option", { name: ACCOUNT_OPTION_LABEL })).toBeInTheDocument();
  });
  await act(async () => {
    fireEvent.change(screen.getByLabelText(/계좌/), { target: { value: ACCOUNT_ID } });
  });
}

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredToken();
  cleanup();
});

/* ───────────────────────────────────────────
 * 1. 계좌 미선택 상태
 * ─────────────────────────────────────────── */
describe("RealizedPnlView — 계좌 미선택 상태", () => {
  it("shows guidance text and disables 조회 button", async () => {
    mockAccountLoading();
    render(<RealizedPnlView />);

    await waitFor(() => {
      expect(screen.getByText("조회할 계좌를 선택하세요.")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "조회" })).toBeDisabled();
  });
});

/* ───────────────────────────────────────────
 * 2. 계좌 + 기간 조회 성공 (종목 전체)
 * ─────────────────────────────────────────── */
describe("RealizedPnlView — 종목 전체 조회", () => {
  it("renders summary cards and by-instrument tab from the summary endpoint", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockImplementation((_account, instrumentId) =>
      Promise.resolve(makeDailyResponse(instrumentId)),
    );

    render(<RealizedPnlView />);
    await selectAccount();

    await waitFor(() => {
      expect(screen.getByRole("option", { name: /005930/ })).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });

    // 요약 카드 4개 — summary 응답 그대로.
    await waitFor(() => {
      expect(screen.getByText("+130,000원", { exact: false })).toBeInTheDocument();
    });
    expect(screen.getByText("3건", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("1,130,000원", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("15,000원", { exact: false })).toBeInTheDocument();

    // recompute 경고 배너 — recompute_pending_count=1이므로 노출된다.
    expect(screen.getByText("재계산 대기중 — 1개 종목")).toBeInTheDocument();
    expect(
      screen.getByText("이 종목들의 실현손익 값은 재계산 대기 중이라 변경될 수 있습니다."),
    ).toBeInTheDocument();

    // 종목별 탭 — summary.by_instrument 그대로.
    fireEvent.click(screen.getByRole("button", { name: "종목별" }));
    expect(screen.getByText("005930")).toBeInTheDocument();
    expect(screen.getByText("삼성전자")).toBeInTheDocument();
    expect(screen.getByText("000660")).toBeInTheDocument();
    expect(screen.getByText("SK하이닉스")).toBeInTheDocument();
    expect(screen.getByText("재계산 대기")).toBeInTheDocument(); // instrument_B badge
  });

  it("hides the recompute warning banner when recompute_pending_count is 0", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryNoRecompute);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockImplementation((_account, instrumentId) =>
      Promise.resolve(makeDailyResponse(instrumentId)),
    );

    render(<RealizedPnlView />);
    await selectAccount();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /005930/ })).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });

    await waitFor(() => {
      expect(screen.getByText("+130,000원", { exact: false })).toBeInTheDocument();
    });
    expect(screen.queryByText(/재계산 대기중/)).not.toBeInTheDocument();
  });

  it("clicking a by-instrument row drills down into that instrument's 체결별 tab", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockImplementation((_account, instrumentId) =>
      Promise.resolve(makeDailyResponse(instrumentId)),
    );
    vi.spyOn(apiClient, "getRealizedPnlEvents").mockResolvedValue(mockEventsSinglePage);

    render(<RealizedPnlView />);
    await selectAccount();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /005930/ })).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });
    await waitFor(() => expect(screen.getByText("재계산 대기중 — 1개 종목")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "종목별" }));
    const row = screen.getByText("005930").closest("tr");
    expect(row).not.toBeNull();
    await act(async () => {
      fireEvent.click(row!);
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /체결별 \(005930\)/ })).toBeInTheDocument();
    });
    expect(apiClient.getRealizedPnlEvents).toHaveBeenCalledWith(
      ACCOUNT_ID,
      INSTRUMENT_A,
      expect.objectContaining({ limit: 200 }),
    );
  });
});

/* ───────────────────────────────────────────
 * 2b. 재계산 대기 배너 드릴다운
 * ─────────────────────────────────────────── */
describe("RealizedPnlView — 재계산 대기 드릴다운", () => {
  async function queryAllInstruments() {
    await selectAccount();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /005930/ })).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });
    await waitFor(() => expect(screen.getByText("재계산 대기중 — 1개 종목")).toBeInTheDocument());
  }

  it("상세 보기를 누르면 pending 큐 항목(종목/사유/등록시각)이 펼쳐진다", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockImplementation((_account, instrumentId) =>
      Promise.resolve(makeDailyResponse(instrumentId)),
    );
    const getQueueMock = vi
      .spyOn(apiClient, "getRealizedPnlRecomputeQueue")
      .mockResolvedValue(mockRecomputeQueueWithItem);

    render(<RealizedPnlView />);
    await queryAllInstruments();

    expect(screen.queryByText("out_of_order_fill")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기" }));
    });

    await waitFor(() => {
      expect(screen.getByText("out_of_order_fill")).toBeInTheDocument();
    });
    const queueRow = screen.getByText("out_of_order_fill").closest("tr");
    expect(queueRow).not.toBeNull();
    expect(queueRow!.textContent).toContain("000660");
    expect(getQueueMock).toHaveBeenCalledWith(ACCOUNT_ID, { instrumentId: undefined });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    });
    expect(screen.queryByText("out_of_order_fill")).not.toBeInTheDocument();
  });

  it("pending 큐가 비어 있으면 빈 상태 문구를 보여준다", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockImplementation((_account, instrumentId) =>
      Promise.resolve(makeDailyResponse(instrumentId)),
    );
    vi.spyOn(apiClient, "getRealizedPnlRecomputeQueue").mockResolvedValue(mockRecomputeQueueEmpty);

    render(<RealizedPnlView />);
    await queryAllInstruments();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기" }));
    });

    await waitFor(() => {
      expect(screen.getByText("재계산 대기 항목이 없습니다.")).toBeInTheDocument();
    });
  });

  it("큐 조회가 실패하면 드릴다운 영역에만 오류를 표시한다", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockImplementation((_account, instrumentId) =>
      Promise.resolve(makeDailyResponse(instrumentId)),
    );
    vi.spyOn(apiClient, "getRealizedPnlRecomputeQueue").mockRejectedValue(
      new Error("재계산 대기 큐 조회 실패"),
    );

    render(<RealizedPnlView />);
    await queryAllInstruments();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기" }));
    });

    await waitFor(() => {
      expect(screen.getByText("재계산 대기 큐 조회 실패")).toBeInTheDocument();
    });
    // 요약 카드는 여전히 정상 표시된다 — 큐 조회 실패가 전체 화면을 무너뜨리지 않는다.
    expect(screen.getByText("+130,000원", { exact: false })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * 3. 단일 종목 조회
 * ─────────────────────────────────────────── */
describe("RealizedPnlView — 단일 종목 조회", () => {
  async function selectInstrumentAndQuery() {
    await selectAccount();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /005930/ })).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/종목/), { target: { value: INSTRUMENT_A } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });
  }

  it("switches to the 체결별 tab and renders events, with no 더 보기 button under the page limit", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummarySingleInstrument);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockResolvedValue(makeDailyResponse(INSTRUMENT_A));
    vi.spyOn(apiClient, "getRealizedPnlEvents").mockResolvedValue(mockEventsSinglePage);

    render(<RealizedPnlView />);
    await selectInstrumentAndQuery();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /체결별 \(005930\)/ })).toBeInTheDocument();
    });
    // 체결별이 기본 활성 탭이므로 바로 이벤트 행이 보인다.
    expect(screen.getByText("70,000원", { exact: false })).toBeInTheDocument(); // 매수단가
    expect(screen.getByText("75,000원", { exact: false })).toBeInTheDocument(); // 매도단가
    expect(screen.queryByRole("button", { name: "더 보기" })).not.toBeInTheDocument();

    // "종목별" 탭은 단일 종목 모드에서 노출되지 않는다.
    expect(screen.queryByRole("button", { name: "종목별" })).not.toBeInTheDocument();
  });

  it("shows 더 보기 when the events page is full, and fetches the next page with a before cursor", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummarySingleInstrument);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockResolvedValue(makeDailyResponse(INSTRUMENT_A));

    const fullPage: RealizedPnlEventView[] = Array.from({ length: 200 }, (_, i) =>
      makeEvent({
        realized_pnl_event_id: `evt-${i}`,
        fill_timestamp: `2026-08-01T${String(i % 24).padStart(2, "0")}:00:00Z`,
      }),
    );
    const secondPage: RealizedPnlEventsResponse = {
      account_id: ACCOUNT_ID,
      instrument_id: INSTRUMENT_A,
      limit: 200,
      before: null,
      events: [makeEvent({ realized_pnl_event_id: "evt-next" })],
    };
    const getEventsMock = vi
      .spyOn(apiClient, "getRealizedPnlEvents")
      .mockResolvedValueOnce({ ...mockEventsSinglePage, events: fullPage })
      .mockResolvedValueOnce(secondPage);

    render(<RealizedPnlView />);
    await selectInstrumentAndQuery();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "더 보기" })).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "더 보기" }));
    });

    await waitFor(() => {
      expect(getEventsMock).toHaveBeenCalledTimes(2);
    });
    expect(getEventsMock.mock.calls[1][2]).toMatchObject({
      before: fullPage[fullPage.length - 1].fill_timestamp,
    });
  });
});

/* ───────────────────────────────────────────
 * 4. 오류 상태
 * ─────────────────────────────────────────── */
describe("RealizedPnlView — 오류 상태", () => {
  it("shows an error banner when the summary request fails", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue([]);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockRejectedValue(
      new Error("summary 조회 실패"),
    );
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockResolvedValue(makeDailyResponse(INSTRUMENT_A));

    render(<RealizedPnlView />);
    await selectAccount();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });

    await waitFor(() => {
      expect(screen.getByText("summary 조회 실패")).toBeInTheDocument();
    });
  });

  it("shows an error banner scoped to the 체결별 tab when the events request fails", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummarySingleInstrument);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockResolvedValue(makeDailyResponse(INSTRUMENT_A));
    vi.spyOn(apiClient, "getRealizedPnlEvents").mockRejectedValue(
      new Error("체결 내역 조회 실패"),
    );

    render(<RealizedPnlView />);
    await selectAccount();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /005930/ })).toBeInTheDocument();
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/종목/), { target: { value: INSTRUMENT_A } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });

    await waitFor(() => {
      expect(screen.getByText("체결 내역 조회 실패")).toBeInTheDocument();
    });
    // 전체 조회 자체는 실패로 처리되지 않는다 — 요약 카드는 정상 렌더된다.
    expect(screen.getByText("+150,000원", { exact: false })).toBeInTheDocument();
  });
});

/* ───────────────────────────────────────────
 * 5. 빈 상태
 * ─────────────────────────────────────────── */
describe("RealizedPnlView — 빈 상태", () => {
  it("shows the designed empty message when there is no activity in range", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue([]);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryEmpty);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockResolvedValue(makeDailyResponse(INSTRUMENT_A));

    render(<RealizedPnlView />);
    await selectAccount();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });

    await waitFor(() => {
      expect(screen.getByText("이 기간 동안 실현손익이 없습니다.")).toBeInTheDocument();
    });
  });
});

/* ───────────────────────────────────────────
 * 6. 기간 프리셋
 * ─────────────────────────────────────────── */
describe("RealizedPnlView — 기간 프리셋", () => {
  it("applies the preset date range to the summary/daily query", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue([]);
    const getSummaryMock = vi
      .spyOn(apiClient, "getRealizedPnlSummary")
      .mockResolvedValue(mockSummaryEmpty);

    render(<RealizedPnlView />);
    await selectAccount();

    fireEvent.click(screen.getByRole("button", { name: "오늘" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "조회" }));
    });

    await waitFor(() => {
      expect(getSummaryMock).toHaveBeenCalled();
    });
    const [, options] = getSummaryMock.mock.calls[0];
    expect(options.startDate).toBe(options.endDate);
  });
});
