import type { AgentRunResponse } from "../types/api";
import { AgentTypeBadge } from "./AgentTypeBadge";
import { StatusBadge } from "./common/StatusBadge";
import { cn } from "@/lib/utils";

interface AgentRunsTableProps {
  runs: AgentRunResponse[];
  selectedId?: string;
  onRowClick?: (run: AgentRunResponse) => void;
  loading?: boolean;
}

function truncateId(id: string, length = 12) {
  return id.length > length ? `${id.substring(0, length)}...` : id;
}

function formatTime(dateString: string | null) {
  if (!dateString) return "-";
  const date = new Date(dateString);
  return date.toLocaleTimeString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AgentRunsTable({ runs, selectedId, onRowClick, loading }: AgentRunsTableProps) {
  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
        <p className="text-sm text-[#94a3b8]">Loading...</p>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
        <p className="text-sm text-[#94a3b8]">No agent runs found</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#e2e8f0] bg-[#f8fafc]">
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                Agent Type
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                Status
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                Decision Context
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                Started
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                Summary
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e2e8f0]">
            {runs.map((run) => {
              const isSelected = selectedId === run.agent_run_id;
              const summary = run.structured_output_json?.["summary"] as string | undefined;
              return (
                <tr
                  key={run.agent_run_id}
                  onClick={() => onRowClick?.(run)}
                  className={cn(
                    "transition-colors cursor-pointer hover:bg-[#f8fafc]",
                    isSelected && "bg-[#eff6ff]",
                  )}
                >
                  <td className="px-4 py-3 text-sm">
                    <AgentTypeBadge agentType={run.agent_type} />
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <StatusBadge status={run.status}>{run.status}</StatusBadge>
                  </td>
                  <td className="px-4 py-3 text-sm text-[#0f172a] font-mono text-xs">
                    {truncateId(run.decision_context_id)}
                  </td>
                  <td className="px-4 py-3 text-sm text-[#0f172a]">
                    {formatTime(run.started_at)}
                  </td>
                  <td className="px-4 py-3 text-sm text-[#64748b] truncate max-w-xs">
                    {summary ? (
                      <span className="text-[#0f172a]">{summary}</span>
                    ) : (
                      <span>-</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
