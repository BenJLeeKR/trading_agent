import { useEffect, useState } from "react";
import type { BrokerCapacityResponse } from "../types/api";
import { getBrokerCapacity } from "../api/client";
import { StatusBadge } from "./common/StatusBadge";
import { ErrorBanner } from "./common/ErrorBanner";
import {
  Activity,
  Wifi,
  Server,
  AlertTriangle,
  CheckCircle,
} from "lucide-react";

/* ── helpers ── */

/** Map REST bucket key to a human-readable label. */
const BUCKET_LABELS: Record<string, string> = {
  auth: "인증",
  order: "주문",
  inquiry: "조회",
  reconciliation: "정합성 점검",
  market_data: "시장 데이터",
};

/** Return a colour class based on utilisation ratio. */
function utilisationColor(ratio: number): string {
  if (ratio >= 0.9) return "bg-red-500";
  if (ratio >= 0.8) return "bg-amber-500";
  if (ratio >= 0.6) return "bg-yellow-400";
  return "bg-emerald-500";
}

/** Format a float as a short percentage string. */
function pct(val: number): string {
  return `${Math.round(val * 100)}%`;
}

/* ── sub-components ── */

function ProgressBar({
  remaining,
  capacity,
  utilization,
}: {
  remaining: number;
  capacity: number;
  utilization: number;
}) {
  const pctWidth = capacity > 0 ? Math.min((remaining / capacity) * 100, 100) : 0;
  const barColor = utilisationColor(utilization);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-[#e2e8f0] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pctWidth}%` }}
        />
      </div>
      <span className="text-xs text-[#64748b] font-mono whitespace-nowrap min-w-[6rem] text-right">
        {remaining}/{capacity} ({pct(utilization)})
      </span>
    </div>
  );
}

/* ── main component ── */

export default function BrokerCapacityPanel() {
  const [capacity, setCapacity] = useState<BrokerCapacityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCapacity = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getBrokerCapacity();
      setCapacity(data);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "브로커 용량을 불러오지 못했습니다";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCapacity();
  }, []);

  /* ── loading (compact inline) ── */
  if (loading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">
            브로커 용량
          </h2>
        </div>
        <div className="bg-white rounded-xl border border-[#e2e8f0] p-6">
          <div className="flex items-center gap-3 text-sm text-[#64748b]">
            <Activity className="h-4 w-4 animate-pulse" />
            브로커 용량 로딩 중…
          </div>
        </div>
      </div>
    );
  }

  /* ── error ── */
  if (error) {
    const is503 =
      error.includes("503") ||
      error.includes("Broker adapter not configured") ||
      error.includes("not configured");
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[#0f172a]">
            브로커 용량
          </h2>
        </div>
        {is503 ? (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-6">
            <div className="flex items-start gap-3">
              <Server className="h-5 w-5 text-[#94a3b8] mt-0.5" />
              <div>
                <p className="text-sm font-medium text-[#0f172a]">
                  이 런타임에서는 용량 정보를 사용할 수 없습니다
                </p>
                <p className="text-xs text-[#94a3b8] mt-1">
                  브로커 어댑터가 설정되지 않았습니다
                </p>
              </div>
            </div>
          </div>
        ) : (
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        )}
      </div>
    );
  }

  /* ── no data (shouldn't happen after successful fetch) ── */
  if (!capacity) return null;

  /* ── main render ── */
  const { broker_name, environment, rest_budget, can_accept_new_entries, websocket, generated_at } =
    capacity;

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[#0f172a]">
          브로커 용량
        </h2>
      </div>

      <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
        {/* Summary row */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#e2e8f0] bg-[#f8fafc]">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-medium text-[#0f172a] capitalize">
              {broker_name}
            </span>
            <span className="text-xs font-mono text-[#64748b] uppercase">
              {environment}
            </span>
            <span className="text-xs text-[#94a3b8]">
              스냅샷 {new Date(generated_at).toLocaleTimeString("ko-KR")}
            </span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-[#64748b]">신규 접수:</span>
            {can_accept_new_entries ? (
              <StatusBadge variant="success">
                <CheckCircle className="h-3 w-3" />
                허용
              </StatusBadge>
            ) : (
              <StatusBadge variant="warning">
                <AlertTriangle className="h-3 w-3" />
                차단
              </StatusBadge>
            )}
          </div>
        </div>

        {/* REST Budget */}
        <div className="px-5 py-4 border-b border-[#e2e8f0]">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="h-4 w-4 text-[#64748b]" />
            <span className="text-sm font-medium text-[#0f172a]">
              REST 예산
            </span>
          </div>
          <div className="space-y-2.5">
            {Object.entries(rest_budget).map(([key, bucket]) => (
              <div key={key} className="grid grid-cols-[7rem_1fr] items-center gap-3">
                <span className="text-xs text-[#64748b] font-medium">
                  {BUCKET_LABELS[key] ?? key}
                </span>
                <ProgressBar
                  remaining={bucket.remaining}
                  capacity={bucket.capacity}
                  utilization={bucket.utilization}
                />
              </div>
            ))}
          </div>
        </div>

        {/* WebSocket */}
        <div className="px-5 py-4">
          <div className="flex items-center gap-2 mb-3">
            <Wifi className="h-4 w-4 text-[#64748b]" />
            <span className="text-sm font-medium text-[#0f172a]">
              웹소켓
            </span>
            {websocket.ws_connected ? (
              <StatusBadge variant="success">
                <CheckCircle className="h-3 w-3" />
                연결됨
              </StatusBadge>
            ) : (
              <StatusBadge variant="error">
                <AlertTriangle className="h-3 w-3" />
                연결 끊김
              </StatusBadge>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-[#94a3b8]">구독</p>
              <p className="text-sm font-mono text-[#0f172a]">
                {websocket.total_used} / {websocket.max_subscriptions}
              </p>
            </div>
            <div>
              <p className="text-xs text-[#94a3b8]">잔여</p>
              <p className="text-sm font-mono text-[#0f172a]">
                {websocket.remaining}
              </p>
            </div>
            <div>
              <p className="text-xs text-[#94a3b8]">중요</p>
              <p className="text-sm font-mono text-[#0f172a]">
                {websocket.current_critical} / {websocket.critical_limit}
              </p>
            </div>
            <div>
              <p className="text-xs text-[#94a3b8]">선택</p>
              <p className="text-sm font-mono text-[#0f172a]">
                {websocket.current_optional} / {websocket.optional_limit}
              </p>
            </div>
            <div>
              <p className="text-xs text-[#94a3b8]">시장데이터 구독</p>
              <p className="text-sm font-mono text-[#0f172a]">
                {capacity.market_data_subscriptions}
              </p>
            </div>
            <div>
              <p className="text-xs text-[#94a3b8]">주문이벤트 계좌</p>
              <p className="text-sm font-mono text-[#0f172a]">
                {capacity.order_event_accounts.length}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
