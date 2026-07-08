import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Column } from "./common/DataTable";
import { DataTable } from "./common/DataTable";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { Panel } from "./common/Panel";
import { StatusBadge } from "./common/StatusBadge";
import { getFillHistory, getFillSyncRunSummary, getFillSyncRuns } from "../api/client";
import type { FillHistoryItem, FillSyncRunHealthSummary, FillSyncRunSummary } from "../types/api";
import { formatKstDateTime } from "../lib/utils";

function todayKst(): string {
  const formatter = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(new Date());
}

function formatHms(value: string | null): string {
  if (!value || value.length !== 6) return "-";
  return `${value.slice(0, 2)}:${value.slice(2, 4)}:${value.slice(4, 6)}`;
}

function formatNumber(value: number): string {
  return value.toLocaleString("ko-KR");
}

function statusVariant(status: string | null): "success" | "warning" | "error" | "neutral" {
  switch (status) {
    case "completed":
      return "success";
    case "partial":
      return "warning";
    case "failed":
      return "error";
    default:
      return "neutral";
  }
}

export default function FillHistoryView() {
  const navigate = useNavigate();
  const [targetDate, setTargetDate] = useState(todayKst());
  const [rows, setRows] = useState<FillHistoryItem[]>([]);
  const [runSummary, setRunSummary] = useState<FillSyncRunHealthSummary | null>(null);
  const [latestRuns, setLatestRuns] = useState<FillSyncRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      getFillHistory(targetDate),
      getFillSyncRunSummary(),
      getFillSyncRuns(5),
    ])
      .then(([history, summary, runs]) => {
        if (cancelled) return;
        setRows(history);
        setRunSummary(summary);
        setLatestRuns(runs);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message ?? "체결내역 조회 실패");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [targetDate]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error} />;

  const latestRun = latestRuns[0] ?? null;
  const columns: Column<FillHistoryItem>[] = [
    { key: "account_alias", header: "계좌", render: (row) => row.account_alias ?? row.account_code ?? row.account_id },
    {
      key: "symbol",
      header: "종목",
      render: (row) => (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/operations/realtime-quotes?symbol=${encodeURIComponent(row.symbol)}`);
          }}
          title="실시간 현재가 보기"
          className="text-sm font-medium text-[#3b82f6] hover:text-[#2563eb] hover:underline transition-colors"
        >
          {row.symbol}
        </button>
      ),
    },
    {
      key: "instrument_name",
      header: "종목명",
      render: (row) => (
        <span className="block max-w-[180px] truncate" title={row.instrument_name ?? undefined}>
          {row.instrument_name ?? "-"}
        </span>
      ),
    },
    {
      key: "side",
      header: "매매",
      render: (row) => <StatusBadge variant={row.side === "buy" ? "error" : "info"}>{row.side === "buy" ? "BUY" : "SELL"}</StatusBadge>,
    },
    { key: "broker_native_order_id", header: "ODNO", render: (row) => <span className="font-mono">{row.broker_native_order_id}</span> },
    { key: "broker_fill_id", header: "체결번호", render: (row) => row.broker_fill_id ?? "-" },
    { key: "ordered_quantity", header: "주문수량", align: "right", render: (row) => row.ordered_quantity ?? "-" },
    { key: "filled_quantity", header: "체결수량", align: "right", render: (row) => row.filled_quantity },
    { key: "fill_price", header: "체결가격", align: "right", render: (row) => formatNumber(row.fill_price) },
    {
      key: "fill_amount",
      header: "체결금액",
      align: "right",
      render: (row) => formatNumber(row.filled_quantity * row.fill_price),
    },
    { key: "order_status_code", header: "주문상태", render: (row) => row.order_status_code ?? "-" },
    { key: "order_time", header: "주문시각", render: (row) => formatHms(row.order_time) },
    { key: "fill_time", header: "체결시각", render: (row) => formatHms(row.fill_time) },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[#0f172a]">체결내역</h2>
          <p className="text-sm text-[#64748b]">VTTC0081R 기반 체결 스냅샷 조회</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-[#475569]" htmlFor="fill-date">조회일</label>
          <input
            id="fill-date"
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            className="rounded-md border border-[#cbd5e1] px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Panel>
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-[#94a3b8]">오늘 조회 건수</p>
            <p className="text-2xl font-semibold text-[#0f172a]">{rows.length}건</p>
            <p className="text-sm text-[#64748b]">조회일: {targetDate}</p>
          </div>
        </Panel>
        <Panel>
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-[#94a3b8]">마지막 동기화</p>
            <p className="text-sm font-medium text-[#0f172a]">{latestRun ? formatKstDateTime(latestRun.started_at) : "-"}</p>
            {latestRun && (
              <StatusBadge variant={statusVariant(latestRun.status)}>
                {latestRun.status}
              </StatusBadge>
            )}
          </div>
        </Panel>
        <Panel>
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-[#94a3b8]">동기화 상태</p>
            <p className="text-sm text-[#0f172a]">
              {runSummary?.is_stale ? "지연" : "정상"}
            </p>
            <p className="text-sm text-[#64748b]">
              연속 실패 {runSummary?.consecutive_failures ?? 0}회
            </p>
          </div>
        </Panel>
      </div>

      {rows.length === 0 ? (
        <Panel>
          <p className="text-sm text-[#64748b]">선택한 날짜의 VTTC0081R 조회 내역이 없습니다.</p>
        </Panel>
      ) : (
        <Panel noPadding>
          <DataTable columns={columns} data={rows} idKey="broker_fill_snapshot_id" compact />
        </Panel>
      )}
    </div>
  );
}
