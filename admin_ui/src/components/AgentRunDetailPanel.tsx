import type { AgentRunResponse } from "../types/api";
import { formatKstDateTime } from "@/lib/utils";

interface AgentRunDetailPanelProps {
  run: AgentRunResponse | null;
}


function agentTypeLabel(agentType: string): string {
  if (agentType.includes("event_interpretation")) return "Event Interpretation";
  if (agentType.includes("ai_risk")) return "AI Risk";
  if (agentType.includes("final_decision_composer")) return "Final Decision Composer";
  return agentType;
}

export function AgentRunDetailPanel({ run }: AgentRunDetailPanelProps) {
  if (!run) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 flex items-center justify-center min-h-[300px]">
        <p className="text-sm text-[#94a3b8]">에이전트 실행을 선택하면 상세 정보를 볼 수 있습니다.</p>
      </div>
    );
  }

  const MetadataField = ({
    label,
    value,
  }: {
    label: string;
    value: string | number | null;
  }) => {
    const displayValue = value ?? "-";
    return (
      <div className="flex justify-between items-start gap-2 py-2 border-b border-[#e2e8f0]">
        <span className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
          {label}
        </span>
        <span className="text-sm text-[#0f172a] font-mono text-right break-all">
          {String(displayValue)}
        </span>
      </div>
    );
  };

  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden flex flex-col">
      <div className="overflow-y-auto flex-1 p-4 md:p-6">
        {/* Metadata Section */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-[#0f172a] mb-3">메타데이터</h3>
          <div className="space-y-0 text-xs">
            <MetadataField label="에이전트 실행 ID" value={run.agent_run_id} />
            <MetadataField label="의사결정 컨텍스트 ID" value={run.decision_context_id} />
            <MetadataField label="에이전트 유형" value={agentTypeLabel(run.agent_type)} />
            <MetadataField label="상태" value={run.status} />
            <MetadataField label="시작" value={formatKstDateTime(run.started_at)} />
            <MetadataField
              label="완료"
              value={run.completed_at ? formatKstDateTime(run.completed_at) : "-"}
            />
            <MetadataField label="모델 ID" value={run.model_id} />
            <MetadataField label="프롬프트 ID" value={run.prompt_id} />
            <MetadataField label="Temperature" value={run.temperature} />
            <MetadataField label="Seed" value={run.seed} />
          </div>
        </div>

        {/* Summary Section */}
        {run.structured_output_json && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-[#0f172a] mb-3">구조화된 출력</h3>
            <div className="bg-[#f8fafc] rounded-lg p-4 space-y-2 text-xs">
              {!!(run.structured_output_json as Record<string, unknown>)["summary"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">요약</p>
                  <p className="text-[#0f172a]">{String((run.structured_output_json as Record<string, unknown>)["summary"])}</p>
                </div>
              )}
              {!!(run.structured_output_json as Record<string, unknown>)["decision_type"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">의사결정 유형</p>
                  <p className="text-[#0f172a]">
                    {String((run.structured_output_json as Record<string, unknown>)["decision_type"])}
                  </p>
                </div>
              )}
              {!!(run.structured_output_json as Record<string, unknown>)["risk_opinion"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">리스크 의견</p>
                  <p className="text-[#0f172a]">
                    {String((run.structured_output_json as Record<string, unknown>)["risk_opinion"])}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {!run.structured_output_json && (
          <div className="bg-[#f8fafc] rounded-lg p-4 text-center">
            <p className="text-sm text-[#94a3b8]">구조화된 출력이 없습니다.</p>
          </div>
        )}
      </div>
    </div>
  );
}
