import { useEffect, useState } from "react";
import { getRealtimeQuoteDailyPrice } from "../../api/client";
import type { RealtimeQuoteDailyPriceItem, RealtimeQuoteTradeTickView } from "../../types/api";

interface TradeHistoryPanelProps {
  symbol: string | null;
  recentTrades: RealtimeQuoteTradeTickView[];
  /** Whether the live snapshot has arrived yet — controls the 시별 탭 placeholder state. */
  hasData: boolean;
}

const PLACEHOLDER = "—";
const ROW_COUNT = 20;

type Tab = "tick" | "daily";

function fmt(n: number): string {
  return n.toLocaleString("ko-KR");
}

function changeTextColor(change: number): string {
  if (change > 0) return "text-[#dc2626]";
  if (change < 0) return "text-[#2563eb]";
  return "text-[#334155]";
}

function changeLabel(change: number, changeRate: number): string {
  const sign = change > 0 ? "+" : "";
  return `${sign}${fmt(change)} (${sign}${changeRate.toFixed(2)}%)`;
}

/** KIS raw "HHMMSS" → "HH:MM:SS" 표시용 포맷. 형식이 다르면 원본을 그대로 둔다. */
function formatTime(raw: string): string {
  if (!/^\d{6}$/.test(raw)) return raw;
  return `${raw.slice(0, 2)}:${raw.slice(2, 4)}:${raw.slice(4, 6)}`;
}

/** KIS raw "YYYYMMDD" → "YYYY-MM-DD" 표시용 포맷. 형식이 다르면 원본을 그대로 둔다. */
function formatDate(raw: string): string {
  if (!/^\d{8}$/.test(raw)) return raw;
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
}

/** Pad/truncate to exactly ``ROW_COUNT`` rows so the frame height never changes. */
function toRows<T>(items: T[]): (T | null)[] {
  const rows: (T | null)[] = items.slice(0, ROW_COUNT);
  while (rows.length < ROW_COUNT) rows.push(null);
  return rows;
}

/**
 * '실시간 체결가' 프레임 — 호가/종목상세정보 사이에 위치, 최소 400px 폭.
 * 시별 탭: WS로 들어온 최근 체결 tick(``H0STCNT0``, 최대 30개, 여기서는 20행만 표시).
 * 일별 탭: KIS 일자별 시세(``FHKST01010400``)를 종목/탭 진입 시 1회 REST 조회.
 *
 * 데이터가 없을 때도(수신 대기 중 / 아직 조회 전) 그리드 구조(20행)는 그대로 유지하고
 * 값만 "—"로 표시한다 — 다른 프레임과 동일한 "프레임 유지" 원칙.
 */
export function TradeHistoryPanel({ symbol, recentTrades, hasData }: TradeHistoryPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>("tick");
  const [dailyBars, setDailyBars] = useState<RealtimeQuoteDailyPriceItem[]>([]);
  const [dailySymbol, setDailySymbol] = useState<string | null>(null);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [dailyError, setDailyError] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== "daily" || !symbol || symbol === dailySymbol) return;
    let cancelled = false;
    setDailyLoading(true);
    setDailyError(null);
    getRealtimeQuoteDailyPrice(symbol)
      .then((res) => {
        if (cancelled) return;
        setDailyBars(res.bars);
        setDailySymbol(symbol);
      })
      .catch(() => {
        if (!cancelled) setDailyError("일별 시세를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setDailyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, symbol, dailySymbol]);

  // 종목이 바뀌면 일별 탭 캐시를 무효화 — 다음에 daily 탭을 열 때 새로 조회한다.
  useEffect(() => {
    setDailyBars([]);
    setDailySymbol(null);
    setDailyError(null);
  }, [symbol]);

  const tickRows = toRows(hasData ? recentTrades : []);
  const dailyRows = toRows(dailySymbol === symbol ? dailyBars : []);

  return (
    <div className="min-w-[400px] border border-[#e2e8f0] rounded-lg overflow-hidden text-sm">
      <div className="flex border-b border-[#e2e8f0]">
        <button
          type="button"
          onClick={() => setActiveTab("tick")}
          className={`flex-1 py-1.5 text-xs font-semibold ${
            activeTab === "tick"
              ? "text-[#0f172a] border-b-2 border-[#3b82f6]"
              : "text-[#94a3b8] hover:text-[#64748b]"
          }`}
        >
          시별
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("daily")}
          className={`flex-1 py-1.5 text-xs font-semibold ${
            activeTab === "daily"
              ? "text-[#0f172a] border-b-2 border-[#3b82f6]"
              : "text-[#94a3b8] hover:text-[#64748b]"
          }`}
        >
          일별
        </button>
      </div>

      {activeTab === "tick" ? (
        <div>
          <div className="grid grid-cols-4 bg-[#f8fafc] text-[10px] font-semibold text-[#64748b] uppercase px-3 py-2">
            <span className="text-center">시간</span>
            <span className="text-center">체결가</span>
            <span className="text-center">전일대비</span>
            <span className="text-center">체결량</span>
          </div>
          {tickRows.map((t, i) => (
            <div key={i} className="grid grid-cols-4 px-3 py-[3px] font-mono text-xs">
              <span className="text-center text-[#64748b]">{t ? formatTime(t.trade_time) : PLACEHOLDER}</span>
              <span className={`text-center font-semibold ${t ? changeTextColor(t.change) : ""}`}>
                {t ? fmt(t.price) : PLACEHOLDER}
              </span>
              <span className={`text-center ${t ? changeTextColor(t.change) : ""}`}>
                {t ? changeLabel(t.change, t.change_rate) : PLACEHOLDER}
              </span>
              <span className="text-center text-[#475569]">{t ? fmt(t.volume) : PLACEHOLDER}</span>
            </div>
          ))}
        </div>
      ) : (
        <div>
          <div className="grid grid-cols-4 bg-[#f8fafc] text-[10px] font-semibold text-[#64748b] uppercase px-3 py-2">
            <span className="text-center">날짜</span>
            <span className="text-center">종가</span>
            <span className="text-center">전일대비</span>
            <span className="text-center">거래량</span>
          </div>
          {dailyLoading && (
            <div className="px-3 py-2 text-xs text-[#94a3b8]">불러오는 중...</div>
          )}
          {dailyError && !dailyLoading && (
            <div className="px-3 py-2 text-xs text-[#dc2626]">{dailyError}</div>
          )}
          {!dailyLoading &&
            !dailyError &&
            dailyRows.map((b, i) => (
              <div key={i} className="grid grid-cols-4 px-3 py-[3px] font-mono text-xs">
                <span className="text-center text-[#64748b]">{b ? formatDate(b.date) : PLACEHOLDER}</span>
                <span className={`text-center font-semibold ${b ? changeTextColor(b.change) : ""}`}>
                  {b ? fmt(b.close) : PLACEHOLDER}
                </span>
                <span className={`text-center ${b ? changeTextColor(b.change) : ""}`}>
                  {b ? changeLabel(b.change, b.change_rate) : PLACEHOLDER}
                </span>
                <span className="text-center text-[#475569]">{b ? fmt(b.volume) : PLACEHOLDER}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
