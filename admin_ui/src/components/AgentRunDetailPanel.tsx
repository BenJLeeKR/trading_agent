import { useState } from "react";
import { Copy } from "lucide-react";
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
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const copyToClipboard = (text: string, field: string) => {
    // field is kept for potential future i18n use
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

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
    copyable = false,
  }: {
    label: string;
    value: string | number | null;
    copyable?: boolean;
  }) => {
    const displayValue = value ?? "-";
    return (
      <div className="flex justify-between items-start gap-2 py-2 border-b border-[#e2e8f0]">
        <span className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
          {label}
        </span>
        <div className="flex items-center gap-1">
          <span className="text-sm text-[#0f172a] font-mono text-right break-all">
            {String(displayValue)}
          </span>
          {copyable && displayValue !== "-" && (
            <button
              onClick={() => copyToClipboard(String(displayValue), label)}
              className="ml-2 p-1 hover:bg-[#f1f5f9] rounded transition-colors"
              title="클립보드에 복사"
            >
              <Copy
                className={`h-3 w-3 ${
                  copiedField === label ? "text-[#16a34a]" : "text-[#94a3b8]"
                }`}
              />
            </button>
          )}
        </div>
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
            <MetadataField label="에이전트 실행 ID" value={run.agent_run_id} copyable />
            <MetadataField label="의사결정 컨텍스트 ID" value={run.decision_context_id} copyable />
            <MetadataField label="에이전트 유형" value={agentTypeLabel(run.agent_type)} />
            <MetadataField label="상태" value={run.status} />
            <MetadataField label="시작" value={formatKstDateTime(run.started_at)} />
            <MetadataField
              label="완료"
              value={run.completed_at ? formatKstDateTime(run.completed_at) : "-"}
            />
            <MetadataField label="모델 ID" value={run.model_id} copyable />
            <MetadataField label="프롬프트 ID" value={run.prompt_id} copyable />
            <MetadataField label="Temperature" value={run.temperature} />
            <MetadataField label="Seed" value={run.seed} />
          </div>
        </div>

        {/* Summary Section */}
        {run.structured_output_json && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-[#0f172a] mb-3">구조화된 출력</h3>
            <div className="bg-[#f8fafc] rounded-lg p-4 space-y-2 text-xs">
              {!!run.structured_output_json["summary"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">요약</p>
                  <p className="text-[#0f172a]">
                    {String(run.structured_output_json["summary"])}
                  </p>
                </div>
              )}
              {!!run.structured_output_json["decision_type"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">의사결정 유형</p>
                  <p className="text-[#0f172a]">
                    {String(run.structured_output_json["decision_type"])}
                  </p>
                </div>
              )}
              {!!run.structured_output_json["risk_opinion"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">리스크 의견</p>
                  <p className="text-[#0f172a]">
                    {String(run.structured_output_json["risk_opinion"])}
                  </p>
                </div>
              )}
              {Array.isArray(run.structured_output_json["reason_codes"]) && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">사유 코드</p>
                  <div className="flex flex-wrap gap-1">
                    {(run.structured_output_json["reason_codes"] as string[]).map(
                      (code, idx) => (
                        <span
                          key={idx}
                          className="bg-[#e2e8f0] text-[#0f172a] px-2 py-1 rounded text-xs"
                        >
                          {code}
                        </span>
                      ),
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Raw JSON Section */}
        {run.structured_output_json && (
          <div>
            <h3 className="text-sm font-semibold text-[#0f172a] mb-3">원시 출력</h3>
            <pre className="bg-[#f8fafc] rounded-lg p-4 overflow-auto text-[11px] text-[#0f172a] font-mono border border-[#e2e8f0] max-h-48">
              {JSON.stringify(run.structured_output_json, null, 2)}
            </pre>
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
