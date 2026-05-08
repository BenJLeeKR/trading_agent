import { useEffect, useState, useMemo } from "react";
import { Search } from "lucide-react";
import { getAgentRuns } from "../api/client";
import type { AgentRunResponse } from "../types/api";
import { AgentRunsTable } from "./AgentRunsTable";
import { AgentRunDetailPanel } from "./AgentRunDetailPanel";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";

export default function AgentRunsView() {
  const [runs, setRuns] = useState<AgentRunResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [agentTypeFilter, setAgentTypeFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  /* ── Fetch all agent runs on mount ── */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentRuns()
      .then((data) => {
        if (!cancelled) {
          setRuns(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "에이전트 실행 기록을 불러오지 못했습니다";
          setError(msg);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  /* ── Client-side filtering ── */
  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      const matchesSearch =
        run.agent_run_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        run.decision_context_id.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesAgentType =
        agentTypeFilter === "all" || run.agent_type.includes(agentTypeFilter);

      const matchesStatus =
        statusFilter === "all" || run.status.toLowerCase() === statusFilter.toLowerCase();

      return matchesSearch && matchesAgentType && matchesStatus;
    });
  }, [runs, searchQuery, agentTypeFilter, statusFilter]);

  const selectedRun = selectedRunId
    ? filteredRuns.find((r) => r.agent_run_id === selectedRunId) || null
    : null;

  /* ── Loading ── */
  if (loading) {
    return (
      <div className="p-6">
        <LoadingSpinner text="에이전트 실행 기록 로딩 중..." />
      </div>
    );
  }

  /* ── Error ── */
  if (error) {
    return (
      <div className="p-6">
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
      </div>
    );
  }

  /* ── Data ── */
  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">에이전트 실행</h1>
        <p className="text-sm text-[#64748b] mt-1">
          AI 에이전트 실행 추적 검토
        </p>
      </div>

      {/* Filters and Search */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 space-y-4">
        {/* Search Input */}
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-[#94a3b8]" />
          <input
            type="text"
            placeholder="의사결정 컨텍스트 ID 또는 에이전트 실행 ID 검색..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-[#e2e8f0] rounded-lg text-sm text-[#0f172a] placeholder-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent"
          />
        </div>

        {/* Filter Row */}
        <div className="flex flex-wrap gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
              에이전트 유형
            </label>
            <select
              aria-label="에이전트 유형"
              value={agentTypeFilter}
              onChange={(e) => setAgentTypeFilter(e.target.value)}
              className="px-3 py-2 border border-[#e2e8f0] rounded-lg text-sm text-[#0f172a] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent cursor-pointer"
            >
              <option value="all">전체</option>
              <option value="event_interpretation">이벤트 해석 (EI)</option>
              <option value="ai_risk">AI 리스크 (AR)</option>
              <option value="final_decision_composer">최종 의사결정 (FDC)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
              상태
            </label>
            <select
              aria-label="상태"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 border border-[#e2e8f0] rounded-lg text-sm text-[#0f172a] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent cursor-pointer"
            >
              <option value="all">전체</option>
              <option value="completed">완료</option>
              <option value="running">실행 중</option>
              <option value="failed">실패</option>
            </select>
          </div>

          <div className="flex items-end">
            <span className="text-xs text-[#94a3b8]">
              {filteredRuns.length}개 결과
            </span>
          </div>
        </div>
      </div>

      {/* Main Content - Table and Detail Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Agent Runs Table */}
        <div className="lg:col-span-2">
          <AgentRunsTable
            runs={filteredRuns}
            selectedId={selectedRunId ?? undefined}
            onRowClick={(run) => setSelectedRunId(run.agent_run_id)}
          />
        </div>

        {/* Right: Detail Panel */}
        <div className="lg:col-span-1">
          <AgentRunDetailPanel run={selectedRun} />
        </div>
      </div>
    </div>
  );
}
