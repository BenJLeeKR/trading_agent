import { useEffect, useRef } from "react";
import type { RealtimeQuoteLevel } from "../../types/api";

interface QuoteLadderProps {
  askLevels: RealtimeQuoteLevel[];
  bidLevels: RealtimeQuoteLevel[];
  prevClose: number;
  totalAskQuantity: number;
  totalBidQuantity: number;
  /** Whether real data has been received. `false` renders an empty grid
   * (10+10 rows, "—" placeholders) instead of collapsing the layout. */
  hasData: boolean;
}

const PLACEHOLDER = "—";

/** 직전(80) / 매도잔량(80) / 가격(100) / 대비율(80) / 매수잔량(80) / 직전(80) = 500px. */
const LADDER_COLUMNS = "grid-cols-[80px_80px_100px_80px_80px_80px]";

function pctValue(price: number, prevClose: number): number {
  if (!prevClose) return 0;
  return ((price - prevClose) / prevClose) * 100;
}

function pctLabel(value: number): string {
  return `${value.toFixed(2)}%`;
}

/** 대비율 부호에 따른 텍스트 색상 — 배경색과는 별개. */
function pctTextColor(value: number): string {
  if (value > 0) return "text-[#dc2626]"; // 상승 — 빨강
  if (value < 0) return "text-[#2563eb]"; // 하락 — 파랑
  return "text-[#334155]"; // 보합(0) — 짙은 회색
}

function fmt(n: number): string {
  return n.toLocaleString("ko-KR");
}

/** Pad/truncate to exactly 10 rows so the grid shape never changes. */
function toRows(levels: RealtimeQuoteLevel[]): (RealtimeQuoteLevel | null)[] {
  const rows: (RealtimeQuoteLevel | null)[] = levels.slice(0, 10);
  while (rows.length < 10) rows.push(null);
  return rows;
}

/**
 * KIS가 내려주지 않는 "직전 조회 대비 잔량 증감"을 클라이언트에서 계산하기 위한
 * in-memory 이력. 호가 단계는 매 tick 가격이 바뀔 수 있으므로 인덱스가 아니라
 * 가격을 키로 이전 잔량을 저장한다 — 그래야 같은 호가(가격)가 유지되는 동안만
 * 의미 있는 증감이 계산되고, 가격이 바뀐 자리는 "직전" 표시가 비게 된다(신규 호가).
 */
function usePrevQuantityByPrice(
  levels: RealtimeQuoteLevel[],
  hasData: boolean,
): Map<number, number> {
  const prevRef = useRef<Map<number, number>>(new Map());
  const snapshotForRender = prevRef.current;

  useEffect(() => {
    if (!hasData) return;
    const next = new Map<number, number>();
    for (const lvl of levels) next.set(lvl.price, lvl.quantity);
    prevRef.current = next;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [levels, hasData]);

  return snapshotForRender;
}

function formatDelta(delta: number | null): string {
  if (delta === null || delta === 0) return PLACEHOLDER;
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toLocaleString("ko-KR")}`;
}

function deltaTextColor(delta: number | null): string {
  if (delta === null || delta === 0) return "text-[#94a3b8]";
  return delta > 0 ? "text-[#dc2626]" : "text-[#2563eb]";
}

/**
 * 10단계 호가창 — 매도 10단계(위, 먼 호가부터) / 매수 10단계(아래, 가까운 호가부터).
 * 배경색은 매도/매수 구분(파란/분홍)을 고정 유지하고, `가격`/`대비율` 텍스트 색상은
 * 매도·매수 구분과 무관하게 기준가 대비 대비율 부호(양수=빨강/음수=파랑/0=짙은 회색)로
 * 결정한다.
 *
 * 데이터가 없을 때도(`hasData=false`) 그리드 구조(10+10행, 헤더, 잔량합계 행)는 그대로
 * 유지하고 값만 "—"로 표시한다 — 장 종료/수신 지연/초기 진입 시 화면 레이아웃이 통째로
 * 사라지거나 안내 문구로 대체되지 않도록 하기 위함.
 */
export function QuoteLadder({
  askLevels,
  bidLevels,
  prevClose,
  totalAskQuantity,
  totalBidQuantity,
  hasData,
}: QuoteLadderProps) {
  const askRows = (hasData ? toRows(askLevels) : toRows([])).reverse(); // 먼 호가 → 최우선 매도호가
  const bidRows = hasData ? toRows(bidLevels) : toRows([]); // 최우선 매수호가 → 먼 호가

  // "직전" 컬럼: 가격을 키로 직전 렌더 시점의 잔량과 비교한 증감.
  const prevAskQtyByPrice = usePrevQuantityByPrice(askLevels, hasData);
  const prevBidQtyByPrice = usePrevQuantityByPrice(bidLevels, hasData);

  function askDelta(lvl: RealtimeQuoteLevel | null): number | null {
    if (!lvl) return null;
    const prev = prevAskQtyByPrice.get(lvl.price);
    return prev === undefined ? null : lvl.quantity - prev;
  }

  function bidDelta(lvl: RealtimeQuoteLevel | null): number | null {
    if (!lvl) return null;
    const prev = prevBidQtyByPrice.get(lvl.price);
    return prev === undefined ? null : lvl.quantity - prev;
  }

  return (
    <div className="w-[500px] border border-[#e2e8f0] rounded-lg overflow-hidden text-sm">
      <div className={`grid ${LADDER_COLUMNS} bg-[#f8fafc] text-[10px] font-semibold text-[#64748b] uppercase py-2`}>
        <span className="text-center">직전</span>
        <span className="text-center">매도잔량</span>
        <span className="text-center">가격</span>
        <span className="text-center">대비율</span>
        <span className="text-center">매수잔량</span>
        <span className="text-center">직전</span>
      </div>

      {askRows.map((lvl, i) => {
        const value = lvl ? pctValue(lvl.price, prevClose) : 0;
        const color = pctTextColor(value);
        const delta = askDelta(lvl);
        return (
          <div
            key={`ask-${i}`}
            className={`grid ${LADDER_COLUMNS} py-1 bg-[#eff6ff] font-mono text-xs`}
          >
            <span className={`text-right ${deltaTextColor(delta)}`}>
              {lvl ? formatDelta(delta) : PLACEHOLDER}
            </span>
            <span className="text-right text-[#475569]">
              {lvl ? fmt(lvl.quantity) : PLACEHOLDER}
            </span>
            <span className={`text-center font-semibold ${color}`}>
              {lvl ? fmt(lvl.price) : PLACEHOLDER}
            </span>
            <span className={`text-center ${color}`}>
              {lvl ? pctLabel(value) : PLACEHOLDER}
            </span>
            <span />
            <span />
          </div>
        );
      })}

      {bidRows.map((lvl, i) => {
        const value = lvl ? pctValue(lvl.price, prevClose) : 0;
        const color = pctTextColor(value);
        const delta = bidDelta(lvl);
        return (
          <div
            key={`bid-${i}`}
            className={`grid ${LADDER_COLUMNS} py-1 bg-[#fef2f2] font-mono text-xs`}
          >
            <span />
            <span />
            <span className={`text-center font-semibold ${color}`}>
              {lvl ? fmt(lvl.price) : PLACEHOLDER}
            </span>
            <span className={`text-center ${color}`}>
              {lvl ? pctLabel(value) : PLACEHOLDER}
            </span>
            <span className="text-left text-[#475569]">
              {lvl ? fmt(lvl.quantity) : PLACEHOLDER}
            </span>
            <span className={`text-left ${deltaTextColor(delta)}`}>
              {lvl ? formatDelta(delta) : PLACEHOLDER}
            </span>
          </div>
        );
      })}

      <div className={`grid ${LADDER_COLUMNS} py-2 border-t border-[#e2e8f0] bg-[#f8fafc] text-xs font-semibold text-[#0f172a]`}>
        <span />
        <span className="text-right">{hasData ? fmt(totalAskQuantity) : PLACEHOLDER}</span>
        <span className="text-center col-span-2 text-[#64748b] font-normal">잔량합계</span>
        <span className="text-left">{hasData ? fmt(totalBidQuantity) : PLACEHOLDER}</span>
        <span />
      </div>
    </div>
  );
}
