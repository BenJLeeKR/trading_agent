import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { DecisionContextDetail, ExternalEventView, TradeDecisionDetail } from "../types/api";
import { getDecisionContext, getRecentExternalEvents, getTradeDecisions } from "../api/client";
import AgentRunsPanel from "./AgentRunsPanel";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { FilterBar } from "./common/FilterBar";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { cn, formatKstDateTime, formatBiasLabel, formatConflictLabel, formatReasonCodeLabel } from "../lib/utils";
import { useEnumMetadata, getEnumLabel } from "../hooks/useEnumMetadata";
import type { Column } from "./common/DataTable";
import { X, Brain } from "lucide-react";

/* ───────────────────────────────────────────
 * formatTimeAgo — relative time display helper
 * ─────────────────────────────────────────── */
/* ───────────────────────────────────────────
 * executionStatusLabel — execution_status 표시 레이블
 * ─────────────────────────────────────────── */
function executionStatusLabel(status: string | null): string {
  const labels: Record<string, string> = {
    'trade_decision_only': '결정만 생성됨',
    'pipeline_stopped': '실행 중단',
    'non_trade': 'HOLD/WATCH',
    'order_created': '주문 생성됨',
    'submitted': '제출 완료',
    'rejected': '거부됨',
    'reconcile_required': '조정 필요',
  };
  return labels[status ?? ''] ?? status ?? '알 수 없음';
}

/* ───────────────────────────────────────────
 * formatTimeAgo — relative time display helper
 * ─────────────────────────────────────────── */
function formatTimeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return '방금';
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
}

/* ───────────────────────────────────────────
 * ConfidenceBar — progress bar with color threshold
 * ─────────────────────────────────────────── */
function ConfidenceBar({ value }: { value: number }) {
  const pct = value * 100;
  const color = value >= 0.7 ? "#22c55e" : value >= 0.4 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden bg-[#f3f4f6]">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-xs font-semibold tabular-nums shrink-0" style={{ color, minWidth: 32 }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

/* ───────────────────────────────────────────
 * DecisionsView
 * ─────────────────────────────────────────── */
export default function DecisionsView() {
  const { fieldMap } = useEnumMetadata();
  const [searchParams, setSearchParams] = useSearchParams();
  const contextIdParam = searchParams.get("contextId");

  // Server-side pagination state
  const [decisions, setDecisions] = useState<TradeDecisionDetail[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Selection state
  const [selectedDecision, setSelectedDecision] = useState<TradeDecisionDetail | null>(null);
  const [contextDetail, setContextDetail] = useState<DecisionContextDetail | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);

  // Recent events state
  const [recentEvents, setRecentEvents] = useState<ExternalEventView[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [eventsExpanded, setEventsExpanded] = useState(false);

  // Filter & pagination state
  const [searchText, setSearchText] = useState("");
  const [sideFilter, setSideFilter] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Server-side page fetch: contextIdParam, currentPage, pageSize 변경 시 재조회
  // 페이지 전환 시 이전 데이터를 유지하면서 loading 표시 (전체 화면 초기화 방지)
  useEffect(() => {
    setLoading(true);
    setError(null);
    const offset = (currentPage - 1) * pageSize;
    const fetchPromise = contextIdParam
      ? getTradeDecisions(contextIdParam, pageSize, offset)
      : getTradeDecisions(undefined, pageSize, offset);
    fetchPromise
      .then((resp) => {
        setDecisions(resp.items ?? []);
        setTotalCount(resp.total ?? 0);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "의사결정을 불러오지 못했습니다";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [contextIdParam, currentPage, pageSize]);

  // Lazy-load decision context on row select (with stale-response guard)
  useEffect(() => {
    const contextId = selectedDecision?.decision_context_id;
    if (!contextId) {
      setContextDetail(null);
      return;
    }
    let cancelled = false;
    setContextLoading(true);
    setContextError(null);
    getDecisionContext(contextId)
      .then((result) => {
        if (!cancelled) setContextDetail(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setContextError(err instanceof Error ? err.message : "컨텍스트를 불러오지 못했습니다");
        }
      })
      .finally(() => {
        if (!cancelled) setContextLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDecision?.decision_context_id]);

  // Recent events — load when selected decision changes
  useEffect(() => {
    if (!selectedDecision?.symbol) {
      setRecentEvents([]);
      return;
    }
    let cancelled = false;
    setEventsLoading(true);
    setEventsError(null);
    getRecentExternalEvents(selectedDecision.symbol, 5)
      .then((data) => {
        if (!cancelled) setRecentEvents(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setEventsError(err instanceof Error ? err.message : "이벤트를 불러오지 못했습니다");
        }
      })
      .finally(() => {
        if (!cancelled) setEventsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDecision]);

  // "더보기" handler — load up to 10 events
  const handleLoadMoreEvents = useCallback(async () => {
    if (!selectedDecision?.symbol) return;
    try {
      setEventsLoading(true);
      const data = await getRecentExternalEvents(selectedDecision.symbol, 10);
      setRecentEvents(data);
      setEventsExpanded(true);
    } catch (err: unknown) {
      setEventsError(err instanceof Error ? err.message : "이벤트를 불러오지 못했습니다");
    } finally {
      setEventsLoading(false);
    }
  }, [selectedDecision]);

  // Client-side filter는 현재 페이지 데이터에만 적용 (search/filter는 전체 데이터셋이 아닌
  // 현재 서버 페이지 내에서만 동작). 서버사이드 search/filter는 향후 확장 가능.
  const filteredDecisions = useMemo(() => {
    return decisions.filter((d) => {
      const matchSide = !sideFilter || d.side === sideFilter;
      const matchSearch =
        !searchText || d.symbol.toLowerCase().includes(searchText.toLowerCase());
      return matchSide && matchSearch;
    });
  }, [decisions, searchText, sideFilter]);

  // totalPages는 서버 totalCount 기준 (client-side filter는 현재 페이지만)
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  // filteredDecisions는 이미 서버에서 받은 현재 페이지 데이터이므로 추가 slice 불필요

  const decisionColumns: Column<TradeDecisionDetail>[] = [
    {
      key: "trade_decision_id",
      header: "의사결정 ID",
      width: "100px",
      render: (r) => <code className="text-xs">{r.trade_decision_id.slice(0, 8)}…</code>,
    },
    { key: "symbol", header: "종목", width: "80px", render: (r) => (
      <span className="text-sm font-medium text-[#0f172a]">{r.symbol ?? "—"}</span>
    )},
    { key: "instrument_name", header: "종목명", width: "180px", render: (r) => (
      <span className="block max-w-[180px] truncate text-sm text-[#334155]" title={r.instrument_name ?? undefined}>
        {r.instrument_name || "—"}
      </span>
    )},
    {
      key: "side",
      header: "매매",
      width: "80px",
      render: (r) => (
        <StatusBadge variant={r.side.toLowerCase() === "buy" ? "success" : r.side.toLowerCase() === "sell" ? "error" : "info"}>
          {getEnumLabel(fieldMap, "side", r.side)}
        </StatusBadge>
      ),
    },
    {
      key: "confidence",
      header: "신뢰도",
      width: "130px",
      render: (r) => <ConfidenceBar value={r.confidence ?? 0} />,
    },
    {
      key: "rationale_summary",
      header: "근거",
      render: (r) => r.rationale_summary || "—",
    },
    {
      key: "created_at",
      header: "시각",
      width: "170px",
      render: (r) => formatKstDateTime(r.created_at),
    },
  ];

  if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0f172a]">의사결정</h1>
          <p className="text-sm text-[#64748b] mt-1">AI 거래 의사결정 및 관련 컨텍스트 조회</p>
        </div>
        {contextIdParam && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#eff6ff] border border-[#bfdbfe] shrink-0">
            <Brain className="h-3.5 w-3.5 text-[#1d4ed8]" />
            <span className="text-xs font-medium text-[#1d4ed8]">
              컨텍스트별 필터링: {contextIdParam.slice(0, 12)}…
            </span>
            <button
              onClick={() => {
                setSearchParams({});
                setSelectedDecision(null);
                setContextDetail(null);
              }}
              className="ml-1 p-0.5 rounded text-[#1d4ed8] hover:text-[#1e40af] hover:bg-[#dbeafe] transition-colors"
              aria-label="컨텍스트 필터 초기화"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Decisions List */}
        <div className={selectedDecision ? "col-span-7" : "col-span-12"}>
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 mb-4">
            <FilterBar
              searchPlaceholder="심볼 또는 의사결정 ID 검색..."
              searchValue={searchText}
              onSearchChange={(v) => { setSearchText(v); setCurrentPage(1); }}
              filters={[
                {
                  key: "side",
                  label: "매매",
                  options: [
                    { label: "매수", value: "buy" },
                    { label: "매도", value: "sell" },
                    { label: "보류", value: "hold" },
                  ],
                  value: sideFilter,
                  onChange: (v) => { setSideFilter(v); setCurrentPage(1); },
                },
              ]}
              onClearAll={() => {
                setSearchText("");
                setSideFilter("");
                setCurrentPage(1);
              }}
            />
          </div>
          <DataTable
            columns={decisionColumns}
            data={filteredDecisions}
            idKey="trade_decision_id"
            isLoading={loading}
            currentPage={safePage}
            pageSize={pageSize}
            totalItems={totalCount}
            onPageChange={setCurrentPage}
            onPageSizeChange={(size) => { setPageSize(size); setCurrentPage(1); }}
            onRowClick={(row) => setSelectedDecision(
              selectedDecision?.trade_decision_id === row.trade_decision_id ? null : row
            )}
            selectedId={selectedDecision?.trade_decision_id}
            emptyMessage="의사결정이 없습니다."
          />
        </div>

        {/* Decision Detail Panel */}
        {selectedDecision && (
          <div className="col-span-5 space-y-4">
            {/* Decision Detail card */}
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-[#0f172a]">의사결정 상세</h3>
                <button
                  onClick={() => { setSelectedDecision(null); setContextDetail(null); }}
                  className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Action + confidence banner */}
              <div className={`flex items-center justify-between px-3 py-2 rounded-lg mb-4 ${
                (selectedDecision.confidence ?? 0) >= 0.7 ? "bg-[#f0fdf4]" :
                (selectedDecision.confidence ?? 0) >= 0.4 ? "bg-[#fffbeb]" :
                "bg-[#fef2f2]"
              }`}>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-[#16a34a]">{getEnumLabel(fieldMap, "side", selectedDecision.side)}</span>
                  <span className="text-sm font-semibold text-[#0f172a]">{selectedDecision.symbol}</span>
                </div>
                <StatusBadge variant={
                  (selectedDecision.confidence ?? 0) >= 0.7 ? "success" :
                  (selectedDecision.confidence ?? 0) >= 0.4 ? "warning" : "error"
                }>
                  {((selectedDecision.confidence ?? 0) * 100).toFixed(0)}%
                </StatusBadge>
              </div>

              {/* Execution Status Badge */}
              {selectedDecision.execution_status && (
                <div className="mb-4">
                  <span className={cn(
                    "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
                    selectedDecision.execution_status === 'trade_decision_only' && "bg-red-100 text-red-800",
                    selectedDecision.execution_status === 'pipeline_stopped' && "bg-orange-100 text-orange-800",
                    selectedDecision.execution_status === 'non_trade' && "bg-gray-100 text-gray-800",
                    selectedDecision.execution_status === 'order_created' && "bg-blue-100 text-blue-800",
                    selectedDecision.execution_status === 'submitted' && "bg-green-100 text-green-800",
                    selectedDecision.execution_status === 'rejected' && "bg-red-100 text-red-800",
                    selectedDecision.execution_status === 'reconcile_required' && "bg-yellow-100 text-yellow-800",
                  )}>
                    {executionStatusLabel(selectedDecision.execution_status)}
                  </span>
                </div>
              )}

              {/* Execution Attempt Summary (Phase 5) */}
              {(selectedDecision.latest_execution_attempt_id || selectedDecision.latest_stop_phase) && (
                <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 mb-4">
                  <div className="flex items-center justify-between mb-1">
                    <h4 className="text-xs font-semibold text-orange-800">Execution Attempt</h4>
                    {selectedDecision.latest_execution_attempt_id && (
                      <a
                        href={`/execution-attempts/${selectedDecision.latest_execution_attempt_id}`}
                        className="text-xs text-blue-600 hover:underline"
                        onClick={(e) => { e.preventDefault(); window.open(`/execution-attempts/${selectedDecision.latest_execution_attempt_id}`, '_blank'); }}
                      >
                        #{selectedDecision.latest_execution_attempt_id.slice(0, 8)}
                      </a>
                    )}
                  </div>
                  <dl className="space-y-1 text-xs">
                    <div className="flex justify-between">
                      <dt className="text-[#64748b]">중단 단계</dt>
                      <dd className="font-mono">{selectedDecision.latest_stop_phase ?? "-"}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-[#64748b]">중단 사유</dt>
                      <dd className="font-mono">{selectedDecision.latest_stop_reason ?? "-"}</dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-[#64748b]">완료 시각</dt>
                      <dd className="font-mono">
                        {selectedDecision.latest_completed_at
                          ? new Date(selectedDecision.latest_completed_at).toLocaleString()
                          : "-"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-[#64748b]">Phase 수</dt>
                      <dd className="font-mono">
                        {selectedDecision.latest_phase_count != null
                          ? `${selectedDecision.latest_phase_count}개`
                          : "-"}
                      </dd>
                    </div>
                  </dl>
                </div>
              )}

              {/* 실행 Phase 이력 — latest_phase_count 축약 표시 */}
              {selectedDecision.latest_execution_attempt_id && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-4">
                  <h4 className="text-xs font-semibold text-gray-700 mb-2">실행 Phase 이력</h4>
                  <p className="text-xs text-gray-500">
                    phase_count: {selectedDecision.latest_phase_count ?? 0}개
                    (execution_attempt #{selectedDecision.latest_execution_attempt_id.slice(0, 8)})
                  </p>
                </div>
              )}

              {/* Order Info */}
              {selectedDecision.order_request_id && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4">
                  <h4 className="text-xs font-semibold text-blue-800 mb-1">주문 정보</h4>
                  <dl className="space-y-1 text-xs">
                    <div className="flex justify-between">
                      <dt className="text-gray-500">Order ID</dt>
                      <dd className="font-mono text-xs truncate max-w-[200px]">{selectedDecision.order_request_id}</dd>
                    </div>
                    {selectedDecision.order_status && (
                      <div className="flex justify-between">
                        <dt className="text-gray-500">상태</dt>
                        <dd className="font-mono">{selectedDecision.order_status}</dd>
                      </div>
                    )}
                  </dl>
                </div>
              )}

              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">의사결정 ID</dt>
                  <dd className="text-sm font-mono text-[#0f172a]">{selectedDecision.trade_decision_id.slice(0, 16)}…</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">의사결정 유형</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{getEnumLabel(fieldMap, "decision_type", selectedDecision.decision_type)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">전략 ID</dt>
                  <dd className="text-sm font-mono text-[#0f172a]">{selectedDecision.strategy_id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">수량</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{String(selectedDecision.quantity ?? "—")}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">생성일</dt>
                  <dd className="text-sm text-[#0f172a]">{formatKstDateTime(selectedDecision.created_at)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">컨텍스트 ID</dt>
                  <dd className="text-sm font-mono text-[#3b82f6]">{selectedDecision.decision_context_id.slice(0, 12)}…</dd>
                </div>
              </dl>

              {/* Confidence bar */}
              <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                <p className="text-xs text-[#64748b] mb-2">신뢰도</p>
                <ConfidenceBar value={selectedDecision.confidence ?? 0} />
              </div>

              {/* FDC Reason (종합 판단 근거) */}
              <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                <p className="text-xs font-semibold text-[#374151] mb-1">종합 판단 근거</p>
                <p className="text-xs leading-relaxed text-[#64748b]">
                  {selectedDecision.rationale_summary || "근거가 제공되지 않았습니다."}
                </p>
              </div>

              {/* EI Reason — decision_json에서 event_bias 표시 (formatter 적용) */}
              {selectedDecision.decision_json?.event_bias != null && (
                <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                  <p className="text-xs font-semibold text-[#374151] mb-1">이벤트 해석 (EI)</p>
                  <p className="text-xs leading-relaxed text-[#64748b]">
                    성향: {formatBiasLabel(selectedDecision.decision_json?.event_bias as string)}
                    {(selectedDecision.decision_json?.event_conflict != null &&
                      formatConflictLabel(selectedDecision.decision_json.event_conflict as boolean) !== '—') && (
                      <span className="ml-2 text-yellow-600">
                        ({formatConflictLabel(selectedDecision.decision_json.event_conflict as boolean)})
                      </span>
                    )}
                  </p>

                  {/* 결정 사유 (event_reason_codes) — formatter 적용 chip */}
                  {Array.isArray((selectedDecision as any).decision_json?.event_reason_codes) &&
                    (selectedDecision as any).decision_json.event_reason_codes.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs font-semibold text-[#374151] mb-1">결정 사유</p>
                      <div className="flex flex-wrap gap-1">
                        {((selectedDecision as any).decision_json.event_reason_codes as string[]).map((code: string, i: number) => (
                          <span key={i} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                            {formatReasonCodeLabel(code)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* event_reason_codes가 비어있거나 null인 경우 — 사유 정보 없음 메시지 */}
                  {((selectedDecision as any).decision_json?.event_reason_codes == null ||
                    (Array.isArray((selectedDecision as any).decision_json?.event_reason_codes) &&
                     (selectedDecision as any).decision_json.event_reason_codes.length === 0)) && (
                    <div className="mt-2">
                      <p className="text-xs font-semibold text-[#374151] mb-1">결정 사유</p>
                      <p className="text-xs leading-relaxed text-[#64748b]">사유 정보 없음</p>
                    </div>
                  )}
                </div>
              )}

              {/* AR Reason — decision_json에서 risk_opinion 표시 */}
              {selectedDecision.decision_json?.risk_opinion != null && (
                <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                  <p className="text-xs font-semibold text-[#374151] mb-1">리스크 평가 (AR)</p>
                  <p className="text-xs leading-relaxed text-[#64748b]">
                    의견: {selectedDecision.decision_json.risk_opinion as string}
                    {Array.isArray(selectedDecision.decision_json.risk_flags) &&
                     selectedDecision.decision_json.risk_flags.length > 0 && (
                      <span className="ml-2">
                        (플래그: {(selectedDecision.decision_json.risk_flags as string[]).join(', ')})
                      </span>
                    )}
                  </p>
                </div>
              )}
            </div>

            {/* Signals card */}
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <h4 className="text-sm font-medium text-[#0f172a] mb-4">시그널</h4>
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">전략 ID</dt>
                  <dd className="text-sm font-mono text-[#0f172a]">{selectedDecision.strategy_id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">매매 시그널</dt>
                  <dd>
                    <StatusBadge variant={selectedDecision.side.toLowerCase() === "buy" ? "success" : selectedDecision.side.toLowerCase() === "sell" ? "error" : "info"}>
                      {getEnumLabel(fieldMap, "side", selectedDecision.side)}
                    </StatusBadge>
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">신뢰도 점수</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{((selectedDecision.confidence ?? 0) * 100).toFixed(0)}%</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">수량</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{String(selectedDecision.quantity ?? "—")}</dd>
                </div>
              </dl>
            </div>

            {/* Market Context card */}
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <h4 className="text-sm font-medium text-[#0f172a] mb-4">시장 컨텍스트</h4>

              {contextLoading && (
                <LoadingSpinner text="컨텍스트 로딩 중..." />
              )}

              {contextError && (
                <ErrorBanner message={contextError} onDismiss={() => setContextError(null)} />
              )}

              {contextDetail && (
                <dl className="space-y-3">
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">전략 ID</dt>
                    <dd className="text-sm font-mono text-[#0f172a]">{contextDetail.strategy_id}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">계좌 ID</dt>
                    <dd className="text-sm font-mono text-[#0f172a]">{contextDetail.account_id}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">세션 ID</dt>
                    <dd className="text-sm text-[#0f172a]">{contextDetail.trading_session_id ?? "—"}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">설정 버전</dt>
                    <dd className="text-sm font-mono text-[#0f172a]">{contextDetail.config_version_id}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">상관관계 ID</dt>
                    <dd className="text-sm font-mono text-[#3b82f6]">{contextDetail.correlation_id}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-sm text-[#64748b]">시장 시각</dt>
                    <dd className="text-sm text-[#0f172a]">{formatKstDateTime(contextDetail.market_timestamp)}</dd>
                  </div>
                </dl>
              )}

              {!contextDetail && !contextLoading && !contextError && (
                <p className="text-sm text-[#94a3b8] text-center py-4">컨텍스트가 있는 의사결정을 선택하면 시장 데이터를 볼 수 있습니다.</p>
              )}
            </div>

            {/* ===== Recent Events Card ===== */}
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <h4 className="text-sm font-medium text-[#0f172a] mb-4">최근 이벤트 (Recent Events)</h4>

              {eventsLoading && recentEvents.length === 0 ? (
                <LoadingSpinner />
              ) : eventsError ? (
                <ErrorBanner message={eventsError} onDismiss={() => setEventsError(null)} />
              ) : recentEvents.length === 0 ? (
                <p className="text-sm text-gray-500">최근 이벤트가 없습니다.</p>
              ) : (
                <ul className="divide-y divide-gray-100">
                  {recentEvents.map((event) => (
                    <li key={event.event_id} className="py-2 flex items-start gap-2">
                      {/* Source tier badge */}
                      <span
                        className={`inline-flex items-center px-1.5 py-0.5 text-xs font-medium rounded ${
                          event.source_reliability_tier === 'T1'
                            ? 'bg-blue-100 text-blue-800'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {event.source_reliability_tier || 'T3'}
                      </span>
                      {/* Source name */}
                      <span className="text-xs text-gray-500 min-w-[80px]">
                        {event.source_name === 'opendart'
                          ? 'OpenDART'
                          : event.source_name === 'naver_news'
                            ? 'Seeded News'
                            : event.source_name}
                      </span>
                      {/* Headline */}
                      <span
                        className="flex-1 text-sm text-gray-700 truncate max-w-[300px]"
                        title={event.headline || ''}
                      >
                        {event.headline || '(제목 없음)'}
                      </span>
                      {/* Time */}
                      <span className="text-xs text-gray-400 whitespace-nowrap">
                        {formatTimeAgo(event.published_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {/* "더보기" button */}
              {!eventsExpanded && recentEvents.length >= 5 && (
                <button
                  onClick={handleLoadMoreEvents}
                  className="mt-2 text-xs text-blue-600 hover:text-blue-800"
                >
                  더보기 (최대 10건)
                </button>
              )}
            </div>

            {/* Agent Runs card */}
            <AgentRunsPanel decisionContextId={selectedDecision?.decision_context_id ?? null} />
          </div>
        )}
      </div>
    </div>
  );
}
