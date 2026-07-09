import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  getRealtimeQuoteBootstrap,
  getRealtimeQuoteSnapshot,
  subscribeRealtimeQuote,
  unsubscribeRealtimeQuote,
} from "../api/client";
import type {
  RealtimeQuoteConnectionInfo,
  RealtimeQuoteSnapshotView,
  RealtimeQuoteSubscriptionView,
} from "../types/api";
import { Panel } from "./common/Panel";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import { WarningBanner } from "./common/WarningBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { DetailField } from "./common/DetailField";
import { QuoteLadder } from "./common/QuoteLadder";
import { formatKstTime } from "@/lib/utils";
import { Wifi, WifiOff, RefreshCcw, Search, X, TrendingUp, TrendingDown, Minus } from "lucide-react";

const POLL_INTERVAL_MS = 3000;
const STALE_THRESHOLD_MS = 10_000;
const SYMBOL_PATTERN = /^\d{6}$/;

/* ── helpers ── */

function formatNumber(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return val.toLocaleString("ko-KR");
}

/** 원 단위 금액을 억원 단위로 반올림해 "123,456 (억원)" 형태로 표시한다. */
function formatEokwon(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return `${Math.round(val / 100_000_000).toLocaleString("ko-KR")} (억원)`;
}

function changeColor(sign: string): string {
  if (sign === "up") return "text-[#dc2626]";
  if (sign === "down") return "text-[#2563eb]";
  return "text-[#64748b]";
}

function ChangeIcon({ sign }: { sign: string }) {
  if (sign === "up") return <TrendingUp className="h-4 w-4" />;
  if (sign === "down") return <TrendingDown className="h-4 w-4" />;
  return <Minus className="h-4 w-4" />;
}

function capacityColor(ratio: number): string {
  if (ratio >= 0.9) return "bg-red-500";
  if (ratio >= 0.7) return "bg-amber-500";
  return "bg-emerald-500";
}

function connectionLabel(state: string | undefined): string {
  if (state === "connected") return "연결됨";
  if (state === "reconnecting") return "재연결 중";
  return "연결 끊김";
}

/* ── main component ── */

export default function RealtimeQuoteView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialSymbolRef = useRef(searchParams.get("symbol"));

  const [connection, setConnection] = useState<RealtimeQuoteConnectionInfo | null>(null);
  const [subscriptions, setSubscriptions] = useState<RealtimeQuoteSubscriptionView[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [quote, setQuote] = useState<RealtimeQuoteSnapshotView | null>(null);

  const [symbolInput, setSymbolInput] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  /* ── initial bootstrap (+ ?symbol= deep-link auto-subscribe/select) ── */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setBootstrapError(null);
      try {
        const initialSymbol = initialSymbolRef.current;
        let data = await getRealtimeQuoteBootstrap();

        if (
          initialSymbol &&
          SYMBOL_PATTERN.test(initialSymbol) &&
          !data.subscriptions.some((s) => s.symbol === initialSymbol)
        ) {
          try {
            data = await subscribeRealtimeQuote([initialSymbol]);
          } catch {
            // Deep-link subscribe failed (e.g. capacity) — fall back to
            // whatever bootstrap already returned.
          }
        }

        if (cancelled) return;
        setConnection(data.connection);
        setSubscriptions(data.subscriptions);

        const preferred =
          initialSymbol && data.subscriptions.some((s) => s.symbol === initialSymbol)
            ? initialSymbol
            : (data.subscriptions[0]?.symbol ?? null);
        setSelectedSymbol(preferred);
      } catch (err: unknown) {
        if (!cancelled) {
          setBootstrapError(
            err instanceof Error ? err.message : "초기 데이터를 불러오지 못했습니다"
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /* ── keep ?symbol= URL param in sync with the selected symbol ──
   * Uses the functional updater so any *other* query params are preserved —
   * only `symbol` is set/removed here. When there's no selected symbol
   * (e.g. after unsubscribing the last one), `symbol` is deleted from the
   * URL entirely rather than left dangling with a stale value. */
  useEffect(() => {
    // Skip while the initial bootstrap fetch is in flight — selectedSymbol
    // is still its initial `null` at that point, and syncing now would
    // briefly strip a `?symbol=` deep-link before bootstrap resolves it.
    if (loading) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (selectedSymbol) {
          next.set("symbol", selectedSymbol);
        } else {
          next.delete("symbol");
        }
        return next;
      },
      { replace: true }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol, loading]);

  /* ── polling snapshot for the selected symbol only (single-symbol focus) ── */
  const fetchSnapshot = useCallback(async () => {
    if (!selectedSymbol) {
      setQuote(null);
      return;
    }
    try {
      const data = await getRealtimeQuoteSnapshot([selectedSymbol]);
      setQuote(data.quotes[selectedSymbol] ?? null);
      setSnapshotError(null);
    } catch (err: unknown) {
      // Keep the last known quote on screen — degrade, don't blank the view.
      setSnapshotError(err instanceof Error ? err.message : "시세를 불러오지 못했습니다");
    }
  }, [selectedSymbol]);

  useEffect(() => {
    setQuote(null);
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchSnapshot]);

  /* ── actions ── */
  const handleSubscribe = async () => {
    const symbol = symbolInput.trim();
    if (!SYMBOL_PATTERN.test(symbol)) {
      setInputError("종목코드는 6자리 숫자로 입력하세요 (예: 005930)");
      return;
    }
    setInputError(null);
    setActionError(null);

    // Already subscribed — just switch the main view, no need to call the API again.
    if (subscriptions.some((s) => s.symbol === symbol)) {
      setSelectedSymbol(symbol);
      setSymbolInput("");
      return;
    }

    try {
      const data = await subscribeRealtimeQuote([symbol]);
      setConnection(data.connection);
      setSubscriptions(data.subscriptions);
      setSelectedSymbol(symbol);
      setSymbolInput("");
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "종목을 구독하지 못했습니다");
    }
  };

  const handleUnsubscribe = async (symbol: string) => {
    setActionError(null);
    try {
      const data = await unsubscribeRealtimeQuote([symbol]);
      setConnection(data.connection);
      setSubscriptions(data.subscriptions);
      if (selectedSymbol === symbol) {
        setSelectedSymbol(data.subscriptions[0]?.symbol ?? null);
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "구독을 해제하지 못했습니다");
    }
  };

  /* ── render: loading ── */
  if (loading) {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-[#0f172a] mb-4">실시간 현재가</h1>
        <LoadingSpinner text="실시간 현재가 화면을 불러오는 중..." />
      </div>
    );
  }

  /* ── render: hard error (bootstrap failed entirely) ── */
  if (bootstrapError && !connection) {
    return (
      <div className="p-6 space-y-4">
        <h1 className="text-xl font-semibold text-[#0f172a]">실시간 현재가</h1>
        <ErrorBanner message={bootstrapError} onDismiss={() => setBootstrapError(null)} />
      </div>
    );
  }

  // `activeSubscription` is best-effort metadata (name/market) looked up from
  // the subscriptions list — it must NOT gate whether the detail frame
  // renders. The frame's only precondition is "a symbol is selected"
  // (`selectedSymbol`). Gating on `activeSubscription` conflated two
  // different things: "no symbol selected" (real empty state) vs. "selected,
  // but the subscriptions list hasn't caught up yet / snapshot has no data
  // yet" (should still show the frame with a waiting state) — the latter
  // was incorrectly hiding the whole panel.
  const activeSubscription = selectedSymbol
    ? (subscriptions.find((s) => s.symbol === selectedSymbol) ?? null)
    : null;
  const displaySymbol = selectedSymbol ?? "";
  const displayName = activeSubscription?.name ?? quote?.name ?? displaySymbol;
  const displayMarket = activeSubscription?.market ?? quote?.market ?? "—";
  const capacityRatio =
    connection && connection.max_registrations > 0
      ? connection.registered_count / connection.max_registrations
      : 0;
  const atCapacity = connection ? subscriptions.length >= connection.symbol_capacity : false;
  const isStale =
    !!quote && Date.now() - new Date(quote.updated_at).getTime() > STALE_THRESHOLD_MS;
  const degraded =
    !!snapshotError || (connection ? connection.connection_state !== "connected" : false);

  return (
    <div className="p-6 space-y-4">
      {/* 헤더: 타이틀 + 환경 배지 */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[#0f172a]">실시간 현재가</h1>
        <StatusBadge variant={connection?.environment === "mock" ? "warning" : "success"}>
          {(connection?.environment ?? "unknown").toUpperCase()}
        </StatusBadge>
      </div>

      {/* A. 연결 상태 / 구독 한도 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="bg-white rounded-lg border border-[#e2e8f0] p-3">
          <div className="flex items-center gap-2">
            {connection?.connection_state === "connected" ? (
              <Wifi className="h-4 w-4 text-[#22c55e]" />
            ) : connection?.connection_state === "reconnecting" ? (
              <RefreshCcw className="h-4 w-4 text-[#f59e0b] animate-spin" />
            ) : (
              <WifiOff className="h-4 w-4 text-[#ef4444]" />
            )}
            <span className="text-sm font-medium text-[#0f172a]">
              {connectionLabel(connection?.connection_state)}
            </span>
            <span className="text-xs text-[#94a3b8]">
              데이터 출처: {connection?.data_source ?? "—"}
            </span>
          </div>
        </div>
        <div className="bg-white rounded-lg border border-[#e2e8f0] p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-[#64748b]">구독 한도</span>
            <span className="text-xs font-mono text-[#64748b]">
              {subscriptions.length}종목 · {connection?.registered_count ?? 0}/
              {connection?.max_registrations ?? 41}건
            </span>
          </div>
          <div className="h-2 bg-[#e2e8f0] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${capacityColor(capacityRatio)}`}
              style={{ width: `${Math.min(capacityRatio * 100, 100)}%` }}
            />
          </div>
        </div>
      </div>

      {/* F. 오류/재연결 상태 */}
      {actionError && (
        <WarningBanner
          variant="warning"
          title="요청을 처리하지 못했습니다"
          message={actionError}
          onDismiss={() => setActionError(null)}
        />
      )}
      {degraded && (
        <WarningBanner
          variant={connection?.connection_state === "disconnected" ? "error" : "warning"}
          title={
            connection?.connection_state === "reconnecting"
              ? "WebSocket 재연결 시도 중"
              : connection?.connection_state === "disconnected"
                ? "WebSocket 연결이 끊겼습니다"
                : "시세 갱신 중 오류가 발생했습니다"
          }
          message="화면에 표시된 값은 마지막 수신값(stale)일 수 있습니다."
        />
      )}

      {/* B. 종목 전환 바 — 타이틀 없이, 검색/추가와 구독 종목 목록을 한 행에 이어붙이고
          오른쪽 공간이 차면 자동으로 다음 줄로 넘어간다(flex-wrap). */}
      <Panel bodyClassName="py-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-56 shrink-0">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#94a3b8]" />
            <input
              type="text"
              inputMode="numeric"
              placeholder="종목코드 6자리 (예: 005930)"
              value={symbolInput}
              onChange={(e) => {
                setSymbolInput(e.target.value);
                if (inputError) setInputError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSubscribe();
              }}
              className="w-full pl-9 pr-3 py-1.5 text-sm border border-[#e2e8f0] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent"
            />
          </div>
          <button
            onClick={handleSubscribe}
            disabled={atCapacity && !subscriptions.some((s) => s.symbol === symbolInput.trim())}
            className="shrink-0 px-4 py-1.5 text-sm font-medium text-white bg-[#3b82f6] rounded-lg hover:bg-[#2563eb] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            title={atCapacity ? "구독 한도(등록 건수)에 도달했습니다" : undefined}
          >
            종목 추가
          </button>

          {subscriptions.length === 0 && (
            <p className="text-sm text-[#94a3b8]">
              구독 중인 종목이 없습니다. 종목코드를 입력해 조회를 시작하세요.
            </p>
          )}
          {subscriptions.map((s) => (
            // A native <button> can't legally contain another <button> (the
            // unsubscribe control below) — browsers silently reparent nested
            // buttons, which can break the click handler. Using a
            // div[role=button] here (with keyboard support) keeps the inner
            // unsubscribe control a real, focusable <button>.
            <div
              key={s.symbol}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedSymbol(s.symbol)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelectedSymbol(s.symbol);
                }
              }}
              className={`flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-full text-sm border transition-colors cursor-pointer ${
                selectedSymbol === s.symbol
                  ? "bg-[#eff6ff] border-[#3b82f6] text-[#1d4ed8]"
                  : "bg-white border-[#e2e8f0] text-[#0f172a] hover:bg-[#f8fafc]"
              }`}
            >
              <span className="font-medium">{s.name}</span>
              <span className="text-xs text-[#94a3b8] font-mono">{s.symbol}</span>
              <button
                type="button"
                aria-label={`${s.symbol} 구독 해제`}
                onClick={(e) => {
                  e.stopPropagation();
                  handleUnsubscribe(s.symbol);
                }}
                className="ml-1 text-[#94a3b8] hover:text-[#ef4444]"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
        {inputError && <p className="text-xs text-[#dc2626] mt-1">{inputError}</p>}
        {atCapacity && !inputError && (
          <p className="text-xs text-[#f59e0b] mt-1">
            구독 한도(등록 건수)에 도달했습니다 — 기존 종목을 해제한 뒤 다시 시도하세요.
          </p>
        )}
      </Panel>

      {/* 종목 없음 상태 — selectedSymbol이 없을 때만 (실제로 선택된 종목이 없는 경우) */}
      {!selectedSymbol && (
        <Panel>
          <div className="p-8 text-center text-sm text-[#94a3b8]">
            조회할 종목을 선택하거나 종목코드를 입력하세요.
          </div>
        </Panel>
      )}

      {selectedSymbol && (
        <>
          {/* C. 종목 헤더 + 현재가 바 */}
          <Panel>
            <div className="flex items-center gap-3 mb-3">
              <StatusBadge variant="info">{displayMarket}</StatusBadge>
              <span className="text-base font-semibold text-[#0f172a]">{displayName}</span>
              <span className="text-xs text-[#94a3b8] font-mono">{displaySymbol}</span>
            </div>
            {/* quote가 없어도 동일한 레이아웃을 유지하고 값만 "—"로 표시 */}
            <div className="flex items-baseline gap-4 flex-wrap">
              <span
                className={`text-2xl font-bold font-mono ${quote ? changeColor(quote.change_sign) : "text-[#94a3b8]"}`}
              >
                {quote ? formatNumber(quote.last_price) : "—"}
              </span>
              <span
                className={`inline-flex items-center gap-1 font-mono ${quote ? changeColor(quote.change_sign) : "text-[#94a3b8]"}`}
              >
                {quote && <ChangeIcon sign={quote.change_sign} />}
                {quote ? `${formatNumber(quote.change)} (${quote.change_rate.toFixed(2)}%)` : "—"}
              </span>
              <span className="text-sm text-[#94a3b8]">
                전일종가 {quote ? formatNumber(quote.prev_close) : "—"}
              </span>
            </div>
          </Panel>

          {/* D. 10단계 호가창 + E. 상세정보 패널 — quote 유무와 무관하게 그리드 구조는 항상 렌더 */}
          {/* 호가 프레임 폭 = 내부 QuoteLadder 고정폭(500px) + Panel 좌우 padding(p-3=24px)
              + Panel border(2px) = 526px — 내부 데이터가 프레임 밖으로 튀어나가지 않도록
              내부 컨텐츠를 감싸는 크기로 맞춘다. */}
          <div className="grid grid-cols-1 lg:grid-cols-[526px_1fr] gap-4">
            <Panel
              title="호가"
              headerRight={
                !quote && <span className="text-xs text-[#94a3b8]">수신 대기 중</span>
              }
              headerClassName="h-[30px] py-0"
              noPadding
              bodyClassName="p-3"
            >
              <QuoteLadder
                key={selectedSymbol}
                hasData={!!quote}
                askLevels={quote?.ask_levels ?? []}
                bidLevels={quote?.bid_levels ?? []}
                prevClose={quote?.prev_close ?? 0}
                totalAskQuantity={quote?.total_ask_quantity ?? 0}
                totalBidQuantity={quote?.total_bid_quantity ?? 0}
              />
            </Panel>

            <Panel
              title="종목 상세정보"
              headerRight={
                !quote && <span className="text-xs text-[#94a3b8]">수신 대기 중</span>
              }
              headerClassName="h-[30px] py-0"
            >
              {/* VI발동기준가/시간외 잔량은 UI 레이아웃 설계(§6-E)에 명시돼 있지만
                  RealtimeQuoteSnapshotView API contract에 아직 없어 의도적으로 생략함.
                  백엔드 스키마가 확장되면 여기에 필드를 추가한다. */}
              <div>
                <DetailField label="시간구분" value={quote?.hour_class ?? "—"} />
                <DetailField
                  label="거래정지 여부"
                  value={quote ? (quote.trading_halted ? "정지" : "정상거래") : "—"}
                />
                <DetailField label="상한가" value={formatNumber(quote?.upper_limit)} mono />
                <DetailField label="고가" value={formatNumber(quote?.high_price)} mono />
                <DetailField label="시가" value={formatNumber(quote?.open_price)} mono />
                <DetailField label="저가" value={formatNumber(quote?.low_price)} mono />
                <DetailField label="하한가" value={formatNumber(quote?.lower_limit)} mono />
                <DetailField label="기준가" value={formatNumber(quote?.prev_close)} mono />
                <DetailField
                  label="누적거래량"
                  value={formatNumber(quote?.accumulated_volume)}
                  mono
                />
                <DetailField
                  label="누적거래대금"
                  value={formatEokwon(quote?.accumulated_value)}
                  mono
                />
                <DetailField label="PER" value={quote?.per?.toFixed(2) ?? "—"} mono />
                <DetailField label="PBR" value={quote?.pbr?.toFixed(2) ?? "—"} mono />
                <DetailField label="EPS" value={formatNumber(quote?.eps)} mono />
                <DetailField label="BPS" value={formatNumber(quote?.bps)} mono />
              </div>
            </Panel>
          </div>

          {/* G. 수신 상태 / 데이터 출처 */}
          <div className="flex items-center gap-3 text-xs text-[#94a3b8]">
            {quote && (
              <>
                <span className={isStale ? "text-[#f59e0b] font-medium" : undefined}>
                  마지막 수신: {formatKstTime(quote.updated_at)}
                  {isStale ? " (지연됨)" : ""}
                </span>
                <span>·</span>
                <span>체결시각: {quote.trade_time || "—"}</span>
                <span>·</span>
                <span>데이터 출처: {quote.data_source}</span>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
