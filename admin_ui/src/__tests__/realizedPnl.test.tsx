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
  RealizedPnlDailySummaryResponse,
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

// 탭 A(일자별) — 종목 "전체" 조회는 이제 daily-summary 단일 호출로 채운다
// (종목별 daily fan-out 없음). 값은 mockSummaryAllInstruments의 전체 합계와
// 굳이 일치시키지 않는다 — 탭 A는 날짜별 분해이고 이 테스트는 데이터 소스
// 전환(호출 경로) 자체를 검증하는 것이 목적이다.
// summary 응답(mockSummaryAllInstruments)과 값을 겹치지 않게 해 두 API 호출이
// 서로 다른 endpoint에서 온 값임을 텍스트 매칭으로도 구분할 수 있게 한다.
const mockDailySummaryAllInstruments: RealizedPnlDailySummaryResponse = {
  account_id: ACCOUNT_ID,
  start_date: "2026-07-01",
  end_date: "2026-08-05",
  daily: [
    {
      trade_date: "2026-08-01",
      realized_pnl_net_sum: 77000,
      sell_event_count: 3,
      buy_amount_sum: 400000,
      sell_amount_sum: 477000,
      fee_tax_sum: 4000,
    },
  ],
};

const mockDailySummaryEmpty: RealizedPnlDailySummaryResponse = {
  account_id: ACCOUNT_ID,
  start_date: "2026-07-01",
  end_date: "2026-08-05",
  daily: [],
};

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
      reason_code: "out_of_order_fill_detected",
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

const mockRecomputeQueueSingleInstrument: RealizedPnlRecomputeQueueResponse = {
  account_id: ACCOUNT_ID,
  instrument_id: INSTRUMENT_A,
  limit: 100,
  items: [
    {
      recompute_queue_id: "queue-2",
      account_id: ACCOUNT_ID,
      instrument_id: INSTRUMENT_A,
      reason_code: "ledger_write_failed",
      triggering_fill_event_id: "fill-42",
      requested_at: "2026-08-03T05:00:00Z",
    },
  ],
};

// 단일 종목 조회에서도 recompute 배너가 뜨는 시나리오 검증용 — 그 종목만
// recompute_required=true.
const mockSummarySingleInstrumentRecompute: RealizedPnlSummaryResponse = {
  ...mockSummarySingleInstrument,
  recompute_pending_count: 1,
  by_instrument: mockSummarySingleInstrument.by_instrument.map((row) => ({
    ...row,
    recompute_required: true,
  })),
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
    const getDailyMock = vi.spyOn(apiClient, "getRealizedPnlDaily");
    const getDailySummaryMock = vi
      .spyOn(apiClient, "getRealizedPnlDailySummary")
      .mockResolvedValue(mockDailySummaryAllInstruments);

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

    // 탭 A(일자별)는 기본 활성 탭이고 daily-summary 단일 호출로 채워진다 —
    // 종목별 daily fan-out(N+1)은 더 이상 호출되지 않는다.
    expect(screen.getByText("2026-08-01")).toBeInTheDocument();
    expect(getDailySummaryMock).toHaveBeenCalledWith(
      ACCOUNT_ID,
      expect.objectContaining({ startDate: expect.any(String), endDate: expect.any(String) }),
    );
    expect(getDailyMock).not.toHaveBeenCalled();

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
    const getDailyMock = vi.spyOn(apiClient, "getRealizedPnlDaily");
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryAllInstruments);

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
    expect(getDailyMock).not.toHaveBeenCalled();
  });

  it("clicking a by-instrument row drills down into that instrument's 체결별 tab", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    const getDailyMock = vi.spyOn(apiClient, "getRealizedPnlDaily");
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryAllInstruments);
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
    expect(getDailyMock).not.toHaveBeenCalled();
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

  it("상세 보기를 누르면 pending 큐 항목이 사람이 읽기 쉬운 사유 라벨(+원본 코드)과 함께 펼쳐진다", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    const getDailyMock = vi.spyOn(apiClient, "getRealizedPnlDaily");
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryAllInstruments);
    const getQueueMock = vi
      .spyOn(apiClient, "getRealizedPnlRecomputeQueue")
      .mockResolvedValue(mockRecomputeQueueWithItem);

    render(<RealizedPnlView />);
    await queryAllInstruments();
    expect(getDailyMock).not.toHaveBeenCalled();

    expect(screen.queryByText("역순 체결 감지")).not.toBeInTheDocument();

    // 종목 전체 조회에서는 "상세 보기" 버튼에 대기 종목 수가 함께 표시된다.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기(1개 종목)" }));
    });

    // 종목 전체 조회 문맥 안내 문구.
    expect(
      screen.getByText(/계좌 전체 종목 중 재계산 대기 중인 항목입니다/),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("역순 체결 감지")).toBeInTheDocument();
    });
    // 원본 reason_code는 숨기지 않고 라벨 옆에 보조 텍스트로 계속 노출한다.
    expect(screen.getByText("(out_of_order_fill_detected)")).toBeInTheDocument();
    const queueRow = screen.getByText("역순 체결 감지").closest("tr");
    expect(queueRow).not.toBeNull();
    expect(queueRow!.textContent).toContain("000660");
    expect(getQueueMock).toHaveBeenCalledWith(ACCOUNT_ID, { instrumentId: undefined });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    });
    expect(screen.queryByText("역순 체결 감지")).not.toBeInTheDocument();
  });

  it("큐 항목 행을 클릭하면 그 종목의 체결별 탭으로 드릴다운된다(다음 액션)", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockResolvedValue(makeDailyResponse(INSTRUMENT_B));
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlRecomputeQueue").mockResolvedValue(mockRecomputeQueueWithItem);
    vi.spyOn(apiClient, "getRealizedPnlEvents").mockResolvedValue(mockEventsSinglePage);

    render(<RealizedPnlView />);
    await queryAllInstruments();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기(1개 종목)" }));
    });
    await waitFor(() => {
      expect(screen.getByText("역순 체결 감지")).toBeInTheDocument();
    });

    const queueRow = screen.getByText("역순 체결 감지").closest("tr");
    await act(async () => {
      fireEvent.click(queueRow!);
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /체결별 \(000660\)/ })).toBeInTheDocument();
    });
    expect(apiClient.getRealizedPnlEvents).toHaveBeenCalledWith(
      ACCOUNT_ID,
      INSTRUMENT_B,
      expect.objectContaining({ limit: 200 }),
    );
  });

  it("단일 종목 조회에서는 안내 문구와 버튼 라벨이 '현재 선택한 종목' 기준으로 표시된다", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummarySingleInstrumentRecompute);
    vi.spyOn(apiClient, "getRealizedPnlDaily").mockResolvedValue(makeDailyResponse(INSTRUMENT_A));
    vi.spyOn(apiClient, "getRealizedPnlEvents").mockResolvedValue(mockEventsSinglePage);
    const getQueueMock = vi
      .spyOn(apiClient, "getRealizedPnlRecomputeQueue")
      .mockResolvedValue(mockRecomputeQueueSingleInstrument);

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
    await waitFor(() => expect(screen.getByText("재계산 대기중 — 1개 종목")).toBeInTheDocument());

    // 단일 종목 조회에서는 종목 수를 덧붙이지 않고 "상세 보기"만 표시한다.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기" }));
    });

    expect(
      screen.getByText(/현재 선택한 종목\(005930\) 기준 재계산 대기 항목입니다/),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("원장 기록 실패")).toBeInTheDocument();
    });
    expect(getQueueMock).toHaveBeenCalledWith(ACCOUNT_ID, { instrumentId: INSTRUMENT_A });
  });

  it("pending 큐가 비어 있으면 운영 의미가 드러나는 빈 상태 문구를 보여준다", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    const getDailyMock = vi.spyOn(apiClient, "getRealizedPnlDaily");
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlRecomputeQueue").mockResolvedValue(mockRecomputeQueueEmpty);

    render(<RealizedPnlView />);
    await queryAllInstruments();
    expect(getDailyMock).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기(1개 종목)" }));
    });

    await waitFor(() => {
      expect(
        screen.getByText(/요약 배지의 대기 종목 수와 차이가 있다면 방금 처리가 완료됐을 수 있습니다/),
      ).toBeInTheDocument();
    });
  });

  it("큐 조회가 실패하면 드릴다운 영역에만, 요약 정보는 정상임을 알리는 오류 문구를 표시한다", async () => {
    mockAccountLoading();
    vi.spyOn(apiClient, "getRealizedPnlPositions").mockResolvedValue(mockPositions);
    vi.spyOn(apiClient, "getRealizedPnlSummary").mockResolvedValue(mockSummaryAllInstruments);
    const getDailyMock = vi.spyOn(apiClient, "getRealizedPnlDaily");
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryAllInstruments);
    vi.spyOn(apiClient, "getRealizedPnlRecomputeQueue").mockRejectedValue(
      new Error("재계산 대기 큐 조회 실패"),
    );

    render(<RealizedPnlView />);
    await queryAllInstruments();
    expect(getDailyMock).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "상세 보기(1개 종목)" }));
    });

    await waitFor(() => {
      expect(
        screen.getByText(/재계산 대기 상세 조회 실패\(요약 정보는 정상입니다\) — 재계산 대기 큐 조회 실패/),
      ).toBeInTheDocument();
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
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryEmpty);

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
    vi.spyOn(apiClient, "getRealizedPnlDailySummary").mockResolvedValue(mockDailySummaryEmpty);

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
    const getDailySummaryMock = vi
      .spyOn(apiClient, "getRealizedPnlDailySummary")
      .mockResolvedValue(mockDailySummaryEmpty);

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

    // 탭 A(일자별)도 같은 프리셋 날짜로 daily-summary를 호출한다.
    expect(getDailySummaryMock).toHaveBeenCalled();
    const [, dailySummaryOptions] = getDailySummaryMock.mock.calls[0];
    expect(dailySummaryOptions.startDate).toBe(options.startDate);
    expect(dailySummaryOptions.endDate).toBe(options.endDate);
  });
});
