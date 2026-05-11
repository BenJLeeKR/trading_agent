import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { DecisionContextDetail, TradeDecisionDetail } from "../types/api";
import { getDecisionContext, getTradeDecisions } from "../api/client";
import AgentRunsPanel from "./AgentRunsPanel";
import { DataTable } from "./common/DataTable";
import { StatusBadge } from "./common/StatusBadge";
import { FilterBar } from "./common/FilterBar";
import { ErrorBanner } from "./common/ErrorBanner";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { useEnumMetadata, getEnumLabel } from "../hooks/useEnumMetadata";
import type { Column } from "./common/DataTable";
import { X, Brain } from "lucide-react";

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

  const [decisions, setDecisions] = useState<TradeDecisionDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Selection state
  const [selectedDecision, setSelectedDecision] = useState<TradeDecisionDetail | null>(null);
  const [contextDetail, setContextDetail] = useState<DecisionContextDetail | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);

  // Filter state
  const [searchText, setSearchText] = useState("");
  const [sideFilter, setSideFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    const fetchPromise = contextIdParam
      ? getTradeDecisions(contextIdParam)
      : getTradeDecisions();
    fetchPromise
      .then(setDecisions)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "의사결정을 불러오지 못했습니다";
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [contextIdParam]);

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

  const filteredDecisions = useMemo(() => {
    return decisions.filter((d) => {
      const matchSide = !sideFilter || d.side === sideFilter;
      const matchSearch =
        !searchText || d.symbol.toLowerCase().includes(searchText.toLowerCase());
      return matchSide && matchSearch;
    });
  }, [decisions, searchText, sideFilter]);

  const decisionColumns: Column<TradeDecisionDetail>[] = [
    {
      key: "trade_decision_id",
      header: "의사결정 ID",
      render: (r) => <code className="text-xs">{r.trade_decision_id.slice(0, 8)}…</code>,
    },
    { key: "symbol", header: "심볼" },
    {
      key: "side",
      header: "매매",
      render: (r) => (
        <StatusBadge variant={r.side.toLowerCase() === "buy" ? "success" : r.side.toLowerCase() === "sell" ? "error" : "info"}>
          {getEnumLabel(fieldMap, "side", r.side)}
        </StatusBadge>
      ),
    },
    {
      key: "confidence",
      header: "신뢰도",
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
      render: (r) => new Date(r.created_at).toLocaleString(),
    },
  ];

  if (loading) return <LoadingSpinner />;
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
          <FilterBar
            searchPlaceholder="심볼 또는 의사결정 ID 검색..."
            searchValue={searchText}
            onSearchChange={setSearchText}
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
                onChange: setSideFilter,
              },
            ]}
            onClearAll={() => {
              setSearchText("");
              setSideFilter("");
            }}
          />
          <DataTable
            columns={decisionColumns}
            data={filteredDecisions}
            idKey="trade_decision_id"
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
                  <dd className="text-sm text-[#0f172a]">{new Date(selectedDecision.created_at).toLocaleString()}</dd>
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

              {/* Reason */}
              <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                <p className="text-xs font-semibold text-[#374151] mb-1">근거</p>
                <p className="text-xs leading-relaxed text-[#64748b]">
                  {selectedDecision.rationale_summary || "근거가 제공되지 않았습니다."}
                </p>
              </div>
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
                    <dd className="text-sm text-[#0f172a]">{new Date(contextDetail.market_timestamp).toLocaleString()}</dd>
                  </div>
                </dl>
              )}

              {!contextDetail && !contextLoading && !contextError && (
                <p className="text-sm text-[#94a3b8] text-center py-4">컨텍스트가 있는 의사결정을 선택하면 시장 데이터를 볼 수 있습니다.</p>
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
