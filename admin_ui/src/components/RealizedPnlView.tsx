import { useEffect, useMemo, useState } from "react";
import type {
  AccountSummary,
  ClientDetail,
  RealizedPnlPositionView,
  RealizedPnlDailyAggregateView,
  RealizedPnlEventView,
  RealizedPnlSummaryResponse,
  RealizedPnlSummaryInstrumentView,
  RealizedPnlRecomputeQueueItemView,
} from "../types/api";
import {
  getClients,
  getDefaultClient,
  getAccounts,
  getRealizedPnlPositions,
  getRealizedPnlDaily,
  getRealizedPnlDailySummary,
  getRealizedPnlEvents,
  getRealizedPnlSummary,
  getRealizedPnlRecomputeQueue,
} from "../api/client";
import { DataTable } from "./common/DataTable";
import type { Column } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { WarningBanner } from "./common/WarningBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { formatKrw, formatKstDateTime, getKstTodayString } from "@/lib/utils";

/* ───────────────────────────────────────────
 * 기간 프리셋 (design/realized_pnl_screen_spec.md §1 — 항상 날짜 범위)
 * ─────────────────────────────────────────── */

function kstDateDaysAgo(days: number): string {
  return getKstTodayString(new Date(Date.now() - days * 86400_000));
}

function kstDateMonthsAgo(months: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return getKstTodayString(d);
}

function kstYearStart(): string {
  return `${getKstTodayString().slice(0, 4)}-01-01`;
}

const PERIOD_PRESETS: { label: string; start: () => string }[] = [
  { label: "오늘", start: () => getKstTodayString() },
  { label: "1주", start: () => kstDateDaysAgo(7) },
  { label: "1개월", start: () => kstDateMonthsAgo(1) },
  { label: "3개월", start: () => kstDateMonthsAgo(3) },
  { label: "올해", start: () => kstYearStart() },
];

/* ───────────────────────────────────────────
 * recompute-queue reason_code → 사람이 읽기 쉬운 라벨.
 * 원본 코드는 숨기지 않는다 — 표에서 라벨 옆 보조 텍스트로 항상 같이 노출한다
 * (운영 디버깅 시 실제 코드값이 필요할 수 있음, realized_pnl_ledger_service.py
 * `_record_recompute()` 호출부 참고). 알려지지 않은 코드는 그대로 표시한다 —
 * 이 코드는 도메인 계층에서 의도적으로 "닫힌 enum이 아닌 str"로 유지되고
 * 있어(entities.py의 RealizedPnlRecomputeQueueEntity 문서 참고) 새 값이
 * 늘어날 수 있다.
 * ─────────────────────────────────────────── */
const RECOMPUTE_REASON_LABELS: Record<string, string> = {
  out_of_order_fill_detected: "역순 체결 감지",
  ledger_write_failed: "원장 기록 실패",
};

function recomputeReasonLabel(reasonCode: string): string {
  return RECOMPUTE_REASON_LABELS[reasonCode] ?? reasonCode;
}

function accountLabel(a: AccountSummary): string {
  return [a.account_code, a.account_alias, a.account_masked].filter(Boolean).join(" · ") || a.account_id;
}

function pnlClass(val: number): string {
  return val >= 0 ? "text-[#16a34a]" : "text-[#dc2626]";
}

function formatSignedKrw(val: number): string {
  return `${val >= 0 ? "+" : ""}${formatKrw(val)}`;
}

type TabKey = "daily" | "byInstrument" | "events";

const EVENTS_PAGE_LIMIT = 200;

/* ───────────────────────────────────────────
 * RealizedPnlView
 * ─────────────────────────────────────────── */
export default function RealizedPnlView() {
  // ── 계좌 목록 (AccountsView와 동일한 client → account 로딩 흐름) ──
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [accountsError, setAccountsError] = useState<string | null>(null);

  useEffect(() => {
    setAccountsLoading(true);
    setAccountsError(null);
    (async () => {
      try {
        const defaultClient = await getDefaultClient();
        const allClients = await getClients();
        if (allClients.length === 0) {
          setAccounts([]);
          return;
        }
        const target: ClientDetail =
          (defaultClient && allClients.find((c) => c.client_id === defaultClient.client_id)) ??
          allClients[0];
        const accts = await getAccounts(target.client_id);
        if (accts) setAccounts(accts);
      } catch (err: unknown) {
        setAccountsError(err instanceof Error ? err.message : "계좌를 불러오지 못했습니다");
      } finally {
        setAccountsLoading(false);
      }
    })();
  }, []);

  // ── 조회 조건 바 상태 (계좌/기간/종목, 한 프레임 한 행) ──
  const [accountId, setAccountId] = useState("");
  const [startDate, setStartDate] = useState(() => kstDateMonthsAgo(1));
  const [endDate, setEndDate] = useState(() => getKstTodayString());
  const [instrumentId, setInstrumentId] = useState(""); // "" = 전체

  // 계좌 선택 시 종목 후보 목록(all-time, 기간 무관) — positions 후보 열거는
  // quantity로 필터링하지 않는다(설계서 "전체매도 종목도 빠지지 않는다" 절 준수).
  const [instrumentOptions, setInstrumentOptions] = useState<RealizedPnlPositionView[]>([]);
  const [instrumentOptionsError, setInstrumentOptionsError] = useState<string | null>(null);

  useEffect(() => {
    setInstrumentOptions([]);
    setInstrumentOptionsError(null);
    if (!accountId) return;
    getRealizedPnlPositions(accountId)
      .then(setInstrumentOptions)
      .catch((err: unknown) => {
        setInstrumentOptionsError(err instanceof Error ? err.message : "종목 목록을 불러오지 못했습니다");
      });
  }, [accountId]);

  // ── 조회 결과 상태 ──
  const [hasQueried, setHasQueried] = useState(false);
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("daily");

  // 요약 카드 + 종목별 탭 + recompute 배지 — GET .../summary 단일 호출로 채운다
  // (계좌 전체든 단일 종목이든 동일 경로 — 아래 "먼저 판단" 주석 참고).
  const [summaryData, setSummaryData] = useState<RealizedPnlSummaryResponse | null>(null);

  // 탭 A(일자별) 전용 날짜별 행 — summary는 날짜별 분해를 제공하지 않으므로
  // (설계서상 의도적 범위 제외) 이 탭만 별도 조회가 필요하다. 종목 "전체"면
  // daily-summary(계좌 전체, 날짜별 단일 호출)를, 단일 종목이면 기존 daily를
  // 그대로 쓴다 — 둘 다 이미 날짜별로 정렬된 행을 반환하므로 프런트에서
  // 다시 합산/재그룹할 필요가 없다(N+1은 "전체" 경로에서 제거됨).
  const [dailyRows, setDailyRows] = useState<RealizedPnlDailyAggregateView[]>([]);

  const [events, setEvents] = useState<RealizedPnlEventView[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsHasMore, setEventsHasMore] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);

  // ── 재계산 대기 배너 드릴다운 — "상세 보기" 클릭 시에만 조회(불필요한 호출 회피).
  const [recomputeQueueExpanded, setRecomputeQueueExpanded] = useState(false);
  const [recomputeQueueLoading, setRecomputeQueueLoading] = useState(false);
  const [recomputeQueueError, setRecomputeQueueError] = useState<string | null>(null);
  const [recomputeQueueItems, setRecomputeQueueItems] = useState<RealizedPnlRecomputeQueueItemView[] | null>(null);

  const selectedAccount = useMemo(
    () => accounts.find((a) => a.account_id === accountId) ?? null,
    [accounts, accountId]
  );

  async function fetchEvents(forInstrumentId: string, before?: string) {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const res = await getRealizedPnlEvents(accountId, forInstrumentId, {
        before,
        limit: EVENTS_PAGE_LIMIT,
      });
      setEvents((prev) => (before ? [...prev, ...res.events] : res.events));
      setEventsHasMore(res.events.length === EVENTS_PAGE_LIMIT);
    } catch (err: unknown) {
      setEventsError(err instanceof Error ? err.message : "체결 내역을 불러오지 못했습니다");
    } finally {
      setEventsLoading(false);
    }
  }

  async function toggleRecomputeQueue() {
    if (recomputeQueueExpanded) {
      setRecomputeQueueExpanded(false);
      return;
    }
    setRecomputeQueueExpanded(true);
    setRecomputeQueueLoading(true);
    setRecomputeQueueError(null);
    try {
      const res = await getRealizedPnlRecomputeQueue(accountId, {
        instrumentId: instrumentId || undefined,
      });
      setRecomputeQueueItems(res.items);
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "알 수 없는 오류";
      setRecomputeQueueError(`재계산 대기 상세 조회 실패(요약 정보는 정상입니다) — ${detail}`);
    } finally {
      setRecomputeQueueLoading(false);
    }
  }

  async function handleQuery() {
    if (!accountId) return;
    setQueryLoading(true);
    setQueryError(null);
    setHasQueried(true);
    setEvents([]);
    setEventsHasMore(false);
    setRecomputeQueueExpanded(false);
    setRecomputeQueueItems(null);
    setRecomputeQueueError(null);

    try {
      // 요약 카드 + 종목별 탭 + recompute 배지는 계좌 전체든 단일 종목이든
      // 동일하게 summary 단일 호출로 채운다(아래 "판단" 참고). 탭 A(일자별)는
      // summary가 제공하지 않는 날짜별 분해가 필요해 별도 조회를 쓴다 —
      // 종목 "전체"면 daily-summary(단일 호출, N+1 제거), 단일 종목이면
      // 그 종목 하나만 조회하는 기존 daily(원래도 N+1이 아니었음)를 쓴다.
      const dailyPromise = instrumentId
        ? getRealizedPnlDaily(accountId, instrumentId, { startDate, endDate }).then((r) => r.daily)
        : getRealizedPnlDailySummary(accountId, { startDate, endDate }).then((r) => r.daily);

      const [summaryRes, dailyResultRows] = await Promise.all([
        getRealizedPnlSummary(accountId, { startDate, endDate, instrumentId: instrumentId || undefined }),
        dailyPromise,
      ]);

      setSummaryData(summaryRes);
      setDailyRows(dailyResultRows);
      setActiveTab(instrumentId ? "events" : "daily");

      if (instrumentId) {
        await fetchEvents(instrumentId);
      }
    } catch (err: unknown) {
      setQueryError(err instanceof Error ? err.message : "실현손익 조회에 실패했습니다");
    } finally {
      setQueryLoading(false);
    }
  }

  // 종목별 탭 행 클릭, recompute-queue 드릴다운 행 클릭 모두 이 경로로
  // 그 종목의 체결별 탭으로 좁혀 들어간다 — "다음 액션"을 일관되게 유도한다.
  function drillDownToInstrument(targetInstrumentId: string) {
    setInstrumentId(targetInstrumentId);
    setActiveTab("events");
    setEvents([]);
    setEventsHasMore(false);
    fetchEvents(targetInstrumentId);
  }

  function handleSelectInstrumentRow(row: RealizedPnlSummaryInstrumentView) {
    drillDownToInstrument(row.instrument_id);
  }

  const dailyColumns: Column<RealizedPnlDailyAggregateView>[] = [
    { key: "trade_date", header: "날짜" },
    { key: "sell_event_count", header: "매도 건수", align: "right", render: (r) => r.sell_event_count.toLocaleString() },
    { key: "buy_amount_sum", header: "매수금액", align: "right", render: (r) => formatKrw(r.buy_amount_sum) },
    { key: "sell_amount_sum", header: "매도금액", align: "right", render: (r) => formatKrw(r.sell_amount_sum) },
    { key: "fee_tax_sum", header: "비용", align: "right", render: (r) => formatKrw(r.fee_tax_sum) },
    {
      key: "realized_pnl_net_sum",
      header: "실현손익(순)",
      align: "right",
      render: (r) => <span className={pnlClass(r.realized_pnl_net_sum)}>{formatSignedKrw(r.realized_pnl_net_sum)}</span>,
    },
  ];

  const instrumentColumns: Column<RealizedPnlSummaryInstrumentView>[] = [
    { key: "symbol", header: "심볼", render: (r) => r.symbol ?? "—" },
    { key: "instrument_name", header: "종목", render: (r) => r.instrument_name ?? "—" },
    { key: "sell_event_count", header: "매도 건수", align: "right", render: (r) => r.sell_event_count.toLocaleString() },
    { key: "buy_amount_sum", header: "매수금액", align: "right", render: (r) => formatKrw(r.buy_amount_sum) },
    { key: "sell_amount_sum", header: "매도금액", align: "right", render: (r) => formatKrw(r.sell_amount_sum) },
    { key: "fee_tax_sum", header: "비용", align: "right", render: (r) => formatKrw(r.fee_tax_sum) },
    {
      key: "realized_pnl_net_sum",
      header: "실현손익(순)",
      align: "right",
      render: (r) => <span className={pnlClass(r.realized_pnl_net_sum)}>{formatSignedKrw(r.realized_pnl_net_sum)}</span>,
    },
    {
      key: "recompute_required",
      header: "상태",
      align: "center",
      render: (r) => (r.recompute_required ? <StatusBadge variant="warning">재계산 대기</StatusBadge> : null),
    },
  ];

  const eventColumns: Column<RealizedPnlEventView>[] = [
    { key: "fill_timestamp", header: "체결시각", render: (r) => formatKstDateTime(r.fill_timestamp) },
    { key: "sell_quantity", header: "수량", align: "right", render: (r) => r.sell_quantity.toLocaleString() },
    { key: "avg_cost_basis_before", header: "매수단가", align: "right", render: (r) => formatKrw(r.avg_cost_basis_before) },
    { key: "sell_price", header: "매도단가", align: "right", render: (r) => formatKrw(r.sell_price) },
    { key: "fee_tax", header: "비용", align: "right", render: (r) => formatKrw(r.fee + r.tax) },
    {
      key: "realized_pnl_net",
      header: "실현손익(순)",
      align: "right",
      render: (r) => <span className={pnlClass(r.realized_pnl_net)}>{formatSignedKrw(r.realized_pnl_net)}</span>,
    },
  ];

  function resolveInstrumentLabel(iid: string): string {
    const p = instrumentOptions.find((o) => o.instrument_id === iid);
    if (!p) return iid;
    return [p.symbol, p.instrument_name].filter(Boolean).join(" · ") || iid;
  }

  const recomputeQueueColumns: Column<RealizedPnlRecomputeQueueItemView>[] = [
    {
      key: "instrument_id",
      header: "종목",
      render: (r) => (
        <span title={r.instrument_id}>{resolveInstrumentLabel(r.instrument_id)}</span>
      ),
    },
    {
      key: "reason_code",
      header: "사유",
      render: (r) => (
        <span className="inline-flex items-baseline gap-1.5">
          <span>{recomputeReasonLabel(r.reason_code)}</span>
          <span className="text-xs text-[#94a3b8]">({r.reason_code})</span>
        </span>
      ),
    },
    {
      key: "requested_at",
      header: "대기 시작(KST)",
      render: (r) => (r.requested_at ? formatKstDateTime(r.requested_at) : "—"),
    },
  ];

  const selectedInstrumentLabel = instrumentId
    ? instrumentOptions.find((p) => p.instrument_id === instrumentId)?.symbol ?? instrumentId
    : null;

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold text-[#0f172a]">실현손익</h1>

      {accountsError && <ErrorBanner message={accountsError} onDismiss={() => setAccountsError(null)} />}
      {instrumentOptionsError && (
        <ErrorBanner message={instrumentOptionsError} onDismiss={() => setInstrumentOptionsError(null)} />
      )}

      {/* 1. 조회 조건 바 — 계좌/기간/종목 한 프레임 한 행 (design §1) */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-[#475569]">
          계좌:
          <select
            value={accountId}
            onChange={(e) => {
              setAccountId(e.target.value);
              setInstrumentId("");
              setHasQueried(false);
            }}
            disabled={accountsLoading}
            className="h-9 rounded border border-[#e2e8f0] bg-white px-2 text-sm text-[#0f172a] focus:outline-none focus:ring-1 focus:ring-[#3b82f6]"
          >
            <option value="">{accountsLoading ? "불러오는 중..." : "계좌 선택"}</option>
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {accountLabel(a)}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-center gap-1">
          {PERIOD_PRESETS.map((preset) => (
            <button
              key={preset.label}
              type="button"
              onClick={() => {
                setStartDate(preset.start());
                setEndDate(getKstTodayString());
              }}
              className="h-9 px-2.5 rounded border border-[#e2e8f0] text-xs font-medium text-[#64748b] hover:bg-[#f1f5f9] transition-colors"
            >
              {preset.label}
            </button>
          ))}
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="h-9 rounded border border-[#e2e8f0] bg-white px-2 text-sm text-[#0f172a] focus:outline-none focus:ring-1 focus:ring-[#3b82f6]"
          />
          <span className="text-[#94a3b8]">~</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="h-9 rounded border border-[#e2e8f0] bg-white px-2 text-sm text-[#0f172a] focus:outline-none focus:ring-1 focus:ring-[#3b82f6]"
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-[#475569]">
          종목:
          <select
            value={instrumentId}
            onChange={(e) => setInstrumentId(e.target.value)}
            disabled={!accountId}
            className="h-9 rounded border border-[#e2e8f0] bg-white px-2 text-sm text-[#0f172a] focus:outline-none focus:ring-1 focus:ring-[#3b82f6]"
          >
            <option value="">전체</option>
            {instrumentOptions.map((p) => (
              <option key={p.instrument_id} value={p.instrument_id}>
                {p.symbol ?? p.instrument_id} {p.instrument_name ? `· ${p.instrument_name}` : ""}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={handleQuery}
          disabled={!accountId || startDate > endDate || queryLoading}
          className="h-9 px-4 rounded bg-[#3b82f6] text-sm font-medium text-white hover:bg-[#2563eb] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          조회
        </button>
      </div>

      {!accountId && (
        <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
          <p className="text-sm text-[#94a3b8]">조회할 계좌를 선택하세요.</p>
        </div>
      )}

      {accountId && startDate > endDate && (
        <ErrorBanner message="시작일은 종료일보다 앞서야 합니다." />
      )}

      {accountId && !hasQueried && startDate <= endDate && (
        <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
          <p className="text-sm text-[#94a3b8]">
            {selectedAccount ? `${accountLabel(selectedAccount)} — ` : ""}
            기간과 종목을 확인한 뒤 [조회]를 눌러주세요.
          </p>
        </div>
      )}

      {queryError && <ErrorBanner message={queryError} onDismiss={() => setQueryError(null)} />}

      {hasQueried && !queryError && (
        <>
          {/* 2. 요약 영역 — 작은 카드 4개, 카드 내부는 "라벨 : 값" 1줄 (design §2) */}
          {queryLoading ? (
            <LoadingSpinner text="실현손익 조회 중..." />
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-white rounded-xl border border-[#e2e8f0] px-4 py-3 text-sm text-[#475569]">
                  실현손익 합계 :{" "}
                  <span className={`font-semibold ${pnlClass(summaryData?.realized_pnl_net_sum ?? 0)}`}>
                    {formatSignedKrw(summaryData?.realized_pnl_net_sum ?? 0)}
                  </span>
                </div>
                <div className="bg-white rounded-xl border border-[#e2e8f0] px-4 py-3 text-sm text-[#475569]">
                  매도 건수 :{" "}
                  <span className="font-semibold text-[#0f172a]">
                    {(summaryData?.sell_event_count ?? 0).toLocaleString()}건
                  </span>
                </div>
                <div className="bg-white rounded-xl border border-[#e2e8f0] px-4 py-3 text-sm text-[#475569]">
                  매도금액 합계 :{" "}
                  <span className="font-semibold text-[#0f172a]">{formatKrw(summaryData?.sell_amount_sum ?? 0)}</span>
                </div>
                <div className="bg-white rounded-xl border border-[#e2e8f0] px-4 py-3 text-sm text-[#475569]">
                  비용 합계 :{" "}
                  <span className="font-semibold text-[#0f172a]">{formatKrw(summaryData?.fee_tax_sum ?? 0)}</span>
                </div>
              </div>

              {(summaryData?.recompute_pending_count ?? 0) > 0 && (
                <div className="space-y-2">
                  <WarningBanner
                    variant="warning"
                    title={`재계산 대기중 — ${summaryData?.recompute_pending_count}개 종목`}
                    message="이 종목들의 실현손익 값은 재계산 대기 중이라 변경될 수 있습니다."
                  />
                  <button
                    type="button"
                    onClick={toggleRecomputeQueue}
                    className="h-8 px-3 rounded border border-[#fbbf24] text-xs font-medium text-[#92400e] hover:bg-[#fef3c7] transition-colors"
                  >
                    {recomputeQueueExpanded
                      ? "닫기"
                      : instrumentId
                        ? "상세 보기"
                        : `상세 보기(${summaryData?.recompute_pending_count}개 종목)`}
                  </button>

                  {recomputeQueueExpanded && (
                    <>
                      {recomputeQueueError && (
                        <ErrorBanner message={recomputeQueueError} onDismiss={() => setRecomputeQueueError(null)} />
                      )}
                      {!recomputeQueueError && (
                        <>
                          <p className="text-xs text-[#64748b] px-1">
                            {instrumentId
                              ? `현재 선택한 종목(${selectedInstrumentLabel}) 기준 재계산 대기 항목입니다. 각 항목의 "사유"를 확인해 언제부터, 왜 대기 중인지 파악한 뒤 필요 시 재계산 배치/운영 로그를 점검하세요.`
                              : "계좌 전체 종목 중 재계산 대기 중인 항목입니다. 종목을 눌러 조회 조건을 그 종목으로 좁히면 체결별 탭에서 상세 원인을 이어서 확인할 수 있습니다."}
                          </p>
                          <DataTable
                            columns={recomputeQueueColumns}
                            data={recomputeQueueItems ?? []}
                            idKey="recompute_queue_id"
                            isLoading={recomputeQueueLoading}
                            onRowClick={
                              instrumentId ? undefined : (row) => drillDownToInstrument(row.instrument_id)
                            }
                            emptyMessage="재계산 대기 항목을 찾지 못했습니다. 요약 배지의 대기 종목 수와 차이가 있다면 방금 처리가 완료됐을 수 있습니다 — 조회를 다시 실행해 확인하세요."
                          />
                        </>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* 3. 탭 구조 */}
              <div className="flex items-center gap-1 border-b border-[#e2e8f0]">
                <button
                  type="button"
                  onClick={() => setActiveTab("daily")}
                  className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                    activeTab === "daily" ? "border-[#3b82f6] text-[#3b82f6]" : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                  }`}
                >
                  일자별
                </button>
                {!instrumentId && (
                  <button
                    type="button"
                    onClick={() => setActiveTab("byInstrument")}
                    className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                      activeTab === "byInstrument" ? "border-[#3b82f6] text-[#3b82f6]" : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                    }`}
                  >
                    종목별
                  </button>
                )}
                {instrumentId && (
                  <button
                    type="button"
                    onClick={() => setActiveTab("events")}
                    className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                      activeTab === "events" ? "border-[#3b82f6] text-[#3b82f6]" : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                    }`}
                  >
                    체결별{selectedInstrumentLabel ? ` (${selectedInstrumentLabel})` : ""}
                  </button>
                )}
              </div>

              {activeTab === "daily" && (
                <DataTable columns={dailyColumns} data={dailyRows} idKey="trade_date" emptyMessage="이 기간 동안 실현손익이 없습니다." />
              )}

              {activeTab === "byInstrument" && !instrumentId && (
                <DataTable
                  columns={instrumentColumns}
                  data={summaryData?.by_instrument ?? []}
                  idKey="instrument_id"
                  onRowClick={handleSelectInstrumentRow}
                  emptyMessage="이 기간 동안 실현손익이 없습니다."
                />
              )}

              {activeTab === "events" && instrumentId && (
                <>
                  {eventsError && <ErrorBanner message={eventsError} onDismiss={() => setEventsError(null)} />}
                  <DataTable
                    columns={eventColumns}
                    data={events}
                    idKey="realized_pnl_event_id"
                    isLoading={eventsLoading}
                    emptyMessage="이 종목의 체결 내역이 없습니다."
                  />
                  {eventsHasMore && !eventsLoading && (
                    <div className="flex justify-center">
                      <button
                        type="button"
                        onClick={() => fetchEvents(instrumentId, events[events.length - 1]?.fill_timestamp)}
                        className="h-9 px-4 rounded border border-[#e2e8f0] text-sm font-medium text-[#64748b] hover:bg-[#f1f5f9] transition-colors"
                      >
                        더 보기
                      </button>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
