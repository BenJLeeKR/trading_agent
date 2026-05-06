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
          const msg = err instanceof Error ? err.message : "Failed to load agent runs";
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
        <LoadingSpinner text="Loading agent runs..." />
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
        <h1 className="text-2xl font-semibold text-[#0f172a]">Agent Runs</h1>
        <p className="text-sm text-[#64748b] mt-1">
          Review AI execution traces for trading decisions
        </p>
      </div>

      {/* Filters and Search */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 space-y-4">
        {/* Search Input */}
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-[#94a3b8]" />
          <input
            type="text"
            placeholder="Search by Decision Context ID or Agent Run ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-[#e2e8f0] rounded-lg text-sm text-[#0f172a] placeholder-[#94a3b8] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent"
          />
        </div>

        {/* Filter Row */}
        <div className="flex flex-wrap gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
              Agent Type
            </label>
            <select
              aria-label="Agent Type"
              value={agentTypeFilter}
              onChange={(e) => setAgentTypeFilter(e.target.value)}
              className="px-3 py-2 border border-[#e2e8f0] rounded-lg text-sm text-[#0f172a] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent cursor-pointer"
            >
              <option value="all">All</option>
              <option value="event_interpretation">Event Interpretation (EI)</option>
              <option value="ai_risk">AI Risk (AR)</option>
              <option value="final_decision_composer">Final Decision Composer (FDC)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
              Status
            </label>
            <select
              aria-label="Status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 border border-[#e2e8f0] rounded-lg text-sm text-[#0f172a] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent cursor-pointer"
            >
              <option value="all">All</option>
              <option value="completed">Completed</option>
              <option value="running">Running</option>
              <option value="failed">Failed</option>
            </select>
          </div>

          <div className="flex items-end">
            <span className="text-xs text-[#94a3b8]">
              {filteredRuns.length} result{filteredRuns.length !== 1 ? "s" : ""}
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
