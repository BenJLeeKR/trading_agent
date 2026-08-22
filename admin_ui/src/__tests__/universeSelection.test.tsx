import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach, vi } from "vitest";
import UniverseSelectionView from "../components/UniverseSelectionView";
import { mockFetchOnce, mockFetchError, mockFetchNetworkError } from "./test-utils/mockFetch";
import type { TradingUniverseFreezeView } from "../types/api";

/**
 * 이 화면은 성능 원칙상 GET /instruments/trading-universe/freeze-summary
 * 단 하나로만 렌더링돼야 한다 — orders/accounts/health/reconciliation 같은
 * 다른 API를 호출하지 않는지가 이 파일의 핵심 검증 대상이다.
 */

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

function makeFreezeView(
  overrides: Partial<TradingUniverseFreezeView> = {},
): TradingUniverseFreezeView {
  return {
    universe_freeze_run_id: "freeze-001",
    freeze_purpose: "decision_loop_intraday",
    business_date: "2026-08-21",
    frozen_at: "2026-08-21T00:05:00Z",
    selection_version: "decision_loop_intraday.freeze.v1",
    target_count: 5,
    source_type_counts: { core: 2, market_overlay: 1, event_overlay: 1, held_position: 1 },
    inclusion_reason_counts: {},
    items: [
      { symbol: "005930", market: "KRX", source_type: "core", inclusion_reason: "core_universe", priority: 1 },
      { symbol: "000660", market: "KRX", source_type: "core", inclusion_reason: "core_universe", priority: 2 },
      { symbol: "035420", market: "KRX", source_type: "market_overlay", inclusion_reason: "trade_strength", priority: 3 },
      { symbol: "005380", market: "KRX", source_type: "event_overlay", inclusion_reason: "disclosure", priority: 4 },
      { symbol: "051910", market: "KRX", source_type: "held_position", inclusion_reason: "held_position_mandatory", priority: 5 },
    ],
    ...overrides,
  };
}

function renderView(initialEntry = "/operations/universe-selection") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <UniverseSelectionView />
    </MemoryRouter>,
  );
}

describe("UniverseSelectionView — 초기 로딩", () => {
  it("초기 렌더는 freeze-summary 1회만 호출한다(다른 API를 호출하지 않는다)", async () => {
    const spy = mockFetchOnce(makeFreezeView());

    renderView();

    await screen.findByText("core (2건)");

    expect(spy).toHaveBeenCalledTimes(1);
    const [url] = spy.mock.calls[0];
    expect(String(url)).toContain("/instruments/trading-universe/freeze-summary");
  });

  it("URL에 date가 없으면 화면이 계산한 KST 오늘 날짜로 조회한다", async () => {
    const spy = mockFetchOnce(makeFreezeView());

    renderView();

    await screen.findByText("core (2건)");

    const [url] = spy.mock.calls[0];
    // getKstTodayString()이 계산한 오늘 날짜가 조회일 input의 기본값이자
    // 실제 호출 파라미터로 그대로 쓰인다(화면-URL-API가 어긋나지 않음).
    const dateInput = screen.getByLabelText("조회일") as HTMLInputElement;
    expect(String(url)).toContain(`business_date=${dateInput.value}`);
  });
});

describe("UniverseSelectionView — 날짜 변경", () => {
  it("날짜를 바꾸면 새 business_date로 freeze-summary를 다시 호출한다", async () => {
    const firstSpy = mockFetchOnce(makeFreezeView({ business_date: "2026-08-21" }));
    renderView();
    await screen.findByText("core (2건)");

    mockFetchOnce(makeFreezeView({ business_date: "2026-08-20", target_count: 9 }));
    const dateInput = screen.getByLabelText("조회일");
    fireEvent.change(dateInput, { target: { value: "2026-08-20" } });

    await screen.findByText("9건");

    // 두 번째 호출은 firstSpy와 동일한 spy 객체(같은 global fetch)로 누적된다.
    expect(firstSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    const [secondUrl] = firstSpy.mock.calls[1];
    expect(String(secondUrl)).toContain("business_date=2026-08-20");
  });
});

describe("UniverseSelectionView — 상태 표현", () => {
  it("API 실패는 ErrorBanner로 표시되고 0건/미수집처럼 보이지 않는다", async () => {
    mockFetchNetworkError();

    renderView();

    await screen.findByText(/불러오지 못했습니다/);
    expect(screen.queryByText("0건")).not.toBeInTheDocument();
    expect(screen.queryByText("미수집")).not.toBeInTheDocument();
  });

  it("401은 '인증 만료'로 표시되고 '해당 날짜 freeze 없음'으로 보이지 않는다", async () => {
    mockFetchError(401, "Unauthorized");

    renderView();

    await screen.findByText(/인증이 만료/);
    expect(screen.queryByText(/freeze 결과가 없습니다/)).not.toBeInTheDocument();
  });

  it("403은 '권한 없음'으로 표시되고 '해당 날짜 freeze 없음'으로 보이지 않는다", async () => {
    mockFetchError(403, "Forbidden");

    renderView();

    await screen.findByText(/권한이 없어/);
    expect(screen.queryByText(/freeze 결과가 없습니다/)).not.toBeInTheDocument();
  });

  it("응답이 null이면 '해당 날짜 freeze 없음'으로 표시되고 미수집 배지가 붙는다(0건 아님)", async () => {
    mockFetchOnce(null);

    renderView();

    await screen.findByText(/freeze 결과가 없습니다/);
    expect(screen.getAllByText("미수집").length).toBeGreaterThan(0);
    expect(screen.queryByText("0건")).not.toBeInTheDocument();
  });

  it("조회 성공 + 특정 bucket 0건은 '0건'으로 표시된다(미수집과 섞이지 않음)", async () => {
    mockFetchOnce(
      makeFreezeView({
        target_count: 2,
        source_type_counts: { core: 2 },
        items: [
          { symbol: "005930", market: "KRX", source_type: "core", inclusion_reason: "core_universe", priority: 1 },
          { symbol: "000660", market: "KRX", source_type: "core", inclusion_reason: "core_universe", priority: 2 },
        ],
      }),
    );

    renderView();

    await screen.findByText("core (2건)");
    expect(screen.getByText("market_overlay (0건)")).toBeInTheDocument();
    expect(screen.getByText("event_overlay (0건)")).toBeInTheDocument();
    expect(screen.queryByText("미수집")).not.toBeInTheDocument();
  });
});

describe("UniverseSelectionView — bucket별 리스트", () => {
  it("core/market_overlay/event_overlay 종목이 각각의 섹션에만 나타난다", async () => {
    mockFetchOnce(makeFreezeView());

    renderView();

    await screen.findByText("core (2건)");
    expect(screen.getByText("005930")).toBeInTheDocument();
    expect(screen.getByText("000660")).toBeInTheDocument();
    expect(screen.getByText("035420")).toBeInTheDocument();
    expect(screen.getByText("005380")).toBeInTheDocument();
  });

  it("기타(core/market/event 외) source_type은 숨기지 않고 원본 문자열과 함께 노출한다", async () => {
    mockFetchOnce(makeFreezeView());

    renderView();

    await screen.findByText(/기타\(reconciliation_overlay/);
    const otherSection = screen.getByText(/기타\(reconciliation_overlay/);
    fireEvent.click(otherSection);
    expect(await screen.findByText("051910")).toBeInTheDocument();
    expect(screen.getByText("held_position")).toBeInTheDocument();
  });
});
