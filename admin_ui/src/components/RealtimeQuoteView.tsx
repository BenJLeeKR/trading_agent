import { useCallback, useEffect, useState } from "react";
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
import { formatKstTime } from "@/lib/utils";
import { Wifi, WifiOff, Search, X, TrendingUp, TrendingDown, Minus } from "lucide-react";

const POLL_INTERVAL_MS = 3000;

/* ── helpers ── */

function formatNumber(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return val.toLocaleString("ko-KR");
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

/* ── main component ── */

export default function RealtimeQuoteView() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [connection, setConnection] = useState<RealtimeQuoteConnectionInfo | null>(null);
  const [subscriptions, setSubscriptions] = useState<RealtimeQuoteSubscriptionView[]>([]);
  const [quotes, setQuotes] = useState<Record<string, RealtimeQuoteSnapshotView>>({});
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(
    searchParams.get("symbol")
  );
  const [symbolInput, setSymbolInput] = useState("");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  /* ── initial bootstrap ── */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const initialSymbol = searchParams.get("symbol");
        let data = await getRealtimeQuoteBootstrap();

        // Deep-link support: if a ?symbol= was provided and isn't already
        // subscribed, auto-subscribe it (see [DESIGN]_kis_realtime_quote_screen_ui_layout.md §3.1).
        if (
          initialSymbol &&
          !data.subscriptions.some((s) => s.symbol === initialSymbol.toUpperCase())
        ) {
          try {
            data = await subscribeRealtimeQuote([initialSymbol]);
          } catch {
            // Fall back to whatever bootstrap already returned.
          }
        }

        if (cancelled) return;
        setConnection(data.connection);
        setSubscriptions(data.subscriptions);
        if (!selectedSymbol && data.subscriptions.length > 0) {
          setSelectedSymbol(data.subscriptions[0].symbol);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "초기 데이터를 불러오지 못했습니다");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── keep ?symbol= URL param in sync with the selected symbol ── */
  useEffect(() => {
    if (selectedSymbol) {
      setSearchParams({ symbol: selectedSymbol }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol]);

  /* ── polling snapshot for subscribed symbols ── */
  const fetchSnapshot = useCallback(async () => {
    if (subscriptions.length === 0) {
      setQuotes({});
      return;
    }
    try {
      const symbols = subscriptions.map((s) => s.symbol);
      const data = await getRealtimeQuoteSnapshot(symbols);
      setQuotes(data.quotes);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "시세를 불러오지 못했습니다");
    }
  }, [subscriptions]);

  useEffect(() => {
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchSnapshot]);

  /* ── actions ── */
  const handleSubscribe = async () => {
    const symbol = symbolInput.trim().toUpperCase();
    if (!symbol) return;
    setActionError(null);
    try {
      const data = await subscribeRealtimeQuote([symbol]);
      setConnection(data.connection);
      setSubscriptions(data.subscriptions);
      setSelectedSymbol(symbol);
      setSymbolInput("");
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "종목을 구독하지 못했습니다"
      );
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
      setActionError(
        err instanceof Error ? err.message : "구독을 해제하지 못했습니다"
      );
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
  if (error && subscriptions.length === 0 && !connection) {
    return (
      <div className="p-6 space-y-4">
        <h1 className="text-xl font-semibold text-[#0f172a]">실시간 현재가</h1>
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
      </div>
    );
  }

  const selectedQuote = selectedSymbol ? quotes[selectedSymbol] : undefined;
  const capacityRatio =
    connection && connection.max_registrations > 0
      ? connection.registered_count / connection.max_registrations
      : 0;

  return (
    <div className="p-6 space-y-4">
      {/* Header: title + environment badge */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[#0f172a]">실시간 현재가</h1>
        <StatusBadge variant={connection?.environment === "mock" ? "warning" : "success"}>
          {(connection?.environment ?? "unknown").toUpperCase()}
        </StatusBadge>
      </div>

      {/* A. Connection status / capacity */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="bg-white rounded-lg border border-[#e2e8f0] p-3">
          <div className="flex items-center gap-2">
            {connection?.connection_state === "connected" ? (
              <Wifi className="h-4 w-4 text-[#22c55e]" />
            ) : (
              <WifiOff className="h-4 w-4 text-[#ef4444]" />
            )}
            <span className="text-sm font-medium text-[#0f172a]">
              {connection?.connection_state === "connected" ? "연결됨" : "연결 끊김"}
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

      {actionError && (
        <WarningBanner
          variant="warning"
          title="요청을 처리하지 못했습니다"
          message={actionError}
          onDismiss={() => setActionError(null)}
        />
      )}

      {error && (subscriptions.length > 0 || connection) && (
        <WarningBanner
          variant="error"
          title="시세 갱신 중 오류가 발생했습니다"
          message={error}
          onDismiss={() => setError(null)}
        />
      )}

      {/* B. 종목 입력 */}
      <Panel title="종목 구독">
        <div className="flex items-center gap-2">
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#94a3b8]" />
            <input
              type="text"
              placeholder="종목코드 입력 (예: 005930)"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSubscribe();
              }}
              className="w-full pl-9 pr-3 py-2 text-sm border border-[#e2e8f0] rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent"
            />
          </div>
          <button
            onClick={handleSubscribe}
            className="px-4 py-2 text-sm font-medium text-white bg-[#3b82f6] rounded-lg hover:bg-[#2563eb] transition-colors"
          >
            구독 추가
          </button>
        </div>

        {/* C. 구독 목록 */}
        <div className="flex flex-wrap gap-2 mt-4">
          {subscriptions.length === 0 && (
            <p className="text-sm text-[#94a3b8]">
              구독 중인 종목이 없습니다. 종목코드를 입력해 추가하세요.
            </p>
          )}
          {subscriptions.map((s) => (
            <button
              key={s.symbol}
              onClick={() => setSelectedSymbol(s.symbol)}
              className={`flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-full text-sm border transition-colors ${
                selectedSymbol === s.symbol
                  ? "bg-[#eff6ff] border-[#3b82f6] text-[#1d4ed8]"
                  : "bg-white border-[#e2e8f0] text-[#0f172a] hover:bg-[#f8fafc]"
              }`}
            >
              <span className="font-medium">{s.name}</span>
              <span className="text-xs text-[#94a3b8] font-mono">{s.symbol}</span>
              <span
                role="button"
                aria-label={`${s.symbol} 구독 해제`}
                onClick={(e) => {
                  e.stopPropagation();
                  handleUnsubscribe(s.symbol);
                }}
                className="ml-1 text-[#94a3b8] hover:text-[#ef4444]"
              >
                <X className="h-3.5 w-3.5" />
              </span>
            </button>
          ))}
        </div>
      </Panel>

      {/* D. 현재가 표시 (subscribed symbols) */}
      <Panel title="현재가" noPadding>
        {subscriptions.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#94a3b8]">
            구독 중인 종목이 없습니다.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-[#64748b] uppercase">종목</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-[#64748b] uppercase">현재가</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-[#64748b] uppercase">전일대비</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-[#64748b] uppercase">등락률</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-[#64748b] uppercase">체결시각</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-[#64748b] uppercase">상태</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0]">
                {subscriptions.map((s) => {
                  const q = quotes[s.symbol];
                  return (
                    <tr
                      key={s.symbol}
                      onClick={() => setSelectedSymbol(s.symbol)}
                      className={`cursor-pointer hover:bg-[#f8fafc] transition-colors ${
                        selectedSymbol === s.symbol ? "bg-[#eff6ff]" : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        <span className="font-medium text-[#0f172a]">{s.name}</span>{" "}
                        <span className="text-xs text-[#94a3b8] font-mono">{s.symbol}</span>
                      </td>
                      <td className={`px-4 py-3 text-right font-mono ${q ? changeColor(q.change_sign) : ""}`}>
                        {q ? formatNumber(q.last_price) : "—"}
                      </td>
                      <td className={`px-4 py-3 text-right font-mono ${q ? changeColor(q.change_sign) : ""}`}>
                        <span className="inline-flex items-center gap-1 justify-end">
                          {q && <ChangeIcon sign={q.change_sign} />}
                          {q ? formatNumber(q.change) : "—"}
                        </span>
                      </td>
                      <td className={`px-4 py-3 text-right font-mono ${q ? changeColor(q.change_sign) : ""}`}>
                        {q ? `${q.change_rate.toFixed(2)}%` : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-[#64748b]">
                        {q?.trade_time ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {q ? (
                          <StatusBadge variant="success">수신중</StatusBadge>
                        ) : (
                          <StatusBadge variant="neutral">대기</StatusBadge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* E. 선택 종목 상세 */}
      {selectedQuote && (
        <Panel title={`${selectedQuote.name} (${selectedQuote.symbol}) 상세`}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            <div>
              <DetailField label="시장" value={selectedQuote.market} />
              <DetailField label="시가" value={formatNumber(selectedQuote.open_price)} mono />
              <DetailField label="고가" value={formatNumber(selectedQuote.high_price)} mono />
              <DetailField label="저가" value={formatNumber(selectedQuote.low_price)} mono />
              <DetailField label="상한가" value={formatNumber(selectedQuote.upper_limit)} mono />
              <DetailField label="하한가" value={formatNumber(selectedQuote.lower_limit)} mono />
              <DetailField label="기준가" value={formatNumber(selectedQuote.prev_close)} mono />
            </div>
            <div>
              <DetailField label="누적거래량" value={formatNumber(selectedQuote.accumulated_volume)} mono />
              <DetailField label="누적거래대금" value={formatNumber(selectedQuote.accumulated_value)} mono />
              <DetailField label="PER" value={selectedQuote.per?.toFixed(2) ?? "—"} mono />
              <DetailField label="PBR" value={selectedQuote.pbr?.toFixed(2) ?? "—"} mono />
              <DetailField label="EPS" value={formatNumber(selectedQuote.eps)} mono />
              <DetailField label="BPS" value={formatNumber(selectedQuote.bps)} mono />
              <DetailField
                label="매도1 / 매수1"
                value={`${formatNumber(selectedQuote.ask_levels[0]?.price)} / ${formatNumber(
                  selectedQuote.bid_levels[0]?.price
                )}`}
                mono
              />
            </div>
          </div>
          <p className="text-xs text-[#94a3b8] mt-3">
            데이터 출처: {selectedQuote.data_source} · 마지막 수신:{" "}
            {formatKstTime(selectedQuote.updated_at)}
          </p>
        </Panel>
      )}
    </div>
  );
}
