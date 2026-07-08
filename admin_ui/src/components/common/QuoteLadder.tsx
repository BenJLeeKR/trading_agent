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

function pct(price: number, prevClose: number): string {
  if (!prevClose) return "0.00%";
  return `${(((price - prevClose) / prevClose) * 100).toFixed(2)}%`;
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
 * 10단계 호가창 — 매도 10단계(위, 먼 호가부터) / 매수 10단계(아래, 가까운 호가부터).
 * ([DESIGN]_kis_realtime_quote_screen_ui_layout.md §4/§6-D 색상 컨벤션: 매도=파란 배경/빨간
 * 텍스트, 매수=분홍 배경/파란 텍스트)
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

  return (
    <div className="border border-[#e2e8f0] rounded-lg overflow-hidden text-sm">
      <div className="grid grid-cols-4 bg-[#f8fafc] text-[10px] font-semibold text-[#64748b] uppercase px-3 py-2">
        <span className="text-right">매도잔량</span>
        <span className="text-center">가격</span>
        <span className="text-center">대비율</span>
        <span className="text-left">매수잔량</span>
      </div>

      {askRows.map((lvl, i) => (
        <div
          key={`ask-${i}`}
          className="grid grid-cols-4 px-3 py-1 bg-[#eff6ff] font-mono text-xs"
        >
          <span className="text-right text-[#475569]">
            {lvl ? fmt(lvl.quantity) : PLACEHOLDER}
          </span>
          <span className="text-center font-semibold text-[#dc2626]">
            {lvl ? fmt(lvl.price) : PLACEHOLDER}
          </span>
          <span className="text-center text-[#dc2626]">
            {lvl ? pct(lvl.price, prevClose) : PLACEHOLDER}
          </span>
          <span />
        </div>
      ))}

      {bidRows.map((lvl, i) => (
        <div
          key={`bid-${i}`}
          className="grid grid-cols-4 px-3 py-1 bg-[#fef2f2] font-mono text-xs"
        >
          <span />
          <span className="text-center font-semibold text-[#2563eb]">
            {lvl ? fmt(lvl.price) : PLACEHOLDER}
          </span>
          <span className="text-center text-[#2563eb]">
            {lvl ? pct(lvl.price, prevClose) : PLACEHOLDER}
          </span>
          <span className="text-left text-[#475569]">
            {lvl ? fmt(lvl.quantity) : PLACEHOLDER}
          </span>
        </div>
      ))}

      <div className="grid grid-cols-4 px-3 py-2 border-t border-[#e2e8f0] bg-[#f8fafc] text-xs font-semibold text-[#0f172a]">
        <span className="text-right">{hasData ? fmt(totalAskQuantity) : PLACEHOLDER}</span>
        <span className="text-center col-span-2 text-[#64748b] font-normal">잔량합계</span>
        <span className="text-left">{hasData ? fmt(totalBidQuantity) : PLACEHOLDER}</span>
      </div>
    </div>
  );
}
