import type { AgentRunResponse } from "../types/api";
import { AgentTypeBadge } from "./AgentTypeBadge";
import { StatusBadge } from "./common/StatusBadge";
import { cn, formatKstTime } from "@/lib/utils";
import { Link } from "react-router-dom";

interface AgentRunsTableProps {
  runs: AgentRunResponse[];
  selectedId?: string;
  onRowClick?: (run: AgentRunResponse) => void;
  loading?: boolean;
}

function truncateId(id: string, length = 12) {
  return id.length > length ? `${id.substring(0, length)}...` : id;
}

export function AgentRunsTable({ runs, selectedId, onRowClick, loading }: AgentRunsTableProps) {
  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
        <p className="text-sm text-[#94a3b8]">로딩 중...</p>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
        <p className="text-sm text-[#94a3b8]">에이전트 실행 기록이 없습니다</p>
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
                에이전트 유형
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                상태
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                의사결정 컨텍스트
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                시작
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                요약
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
                    <Link
                      to={`/decisions?contextId=${encodeURIComponent(run.decision_context_id)}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-[#3b82f6] hover:underline"
                      title={run.decision_context_id}
                    >
                      {truncateId(run.decision_context_id)}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-[#0f172a]">
                    {formatKstTime(run.started_at)}
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
