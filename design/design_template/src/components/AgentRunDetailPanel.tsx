import { AgentRunResponse } from "@/types/agentRun"
import { Copy } from "lucide-react"
import { useState } from "react"

interface AgentRunDetailPanelProps {
  run: AgentRunResponse | null
}

export function AgentRunDetailPanel({ run }: AgentRunDetailPanelProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const copyToClipboard = (text: string, field: string) => {
    navigator.clipboard.writeText(text)
    setCopiedField(field)
    setTimeout(() => setCopiedField(null), 2000)
  }

  if (!run) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 flex items-center justify-center h-96">
        <p className="text-sm text-[#94a3b8]">Select an agent run to view details</p>
      </div>
    )
  }

  const formatTime = (dateString: string | null) => {
    if (!dateString) return "-"
    const date = new Date(dateString)
    return date.toLocaleString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
  }

  const agentTypeLabel = run.agent_type.includes("event_interpretation")
    ? "Event Interpretation"
    : run.agent_type.includes("ai_risk")
    ? "AI Risk"
    : run.agent_type.includes("final_decision_composer")
    ? "Final Decision Composer"
    : run.agent_type

  const MetadataField = ({
    label,
    value,
    copyable = false,
  }: {
    label: string
    value: string | number | null
    copyable?: boolean
  }) => {
    const displayValue = value ?? "-"
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
              title="Copy to clipboard"
            >
              <Copy
                className={`h-3 w-3 ${
                  copiedField === label
                    ? "text-[#16a34a]"
                    : "text-[#94a3b8]"
                }`}
              />
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] overflow-hidden flex flex-col h-96 md:h-[600px]">
      <div className="overflow-y-auto flex-1 p-4 md:p-6">
        {/* Metadata Section */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-[#0f172a] mb-3">Metadata</h3>
          <div className="space-y-0 text-xs">
            <MetadataField label="Agent Run ID" value={run.agent_run_id} copyable />
            <MetadataField
              label="Decision Context ID"
              value={run.decision_context_id}
              copyable
            />
            <MetadataField label="Agent Type" value={agentTypeLabel} />
            <MetadataField label="Status" value={run.status} />
            <MetadataField label="Started At" value={formatTime(run.started_at)} />
            <MetadataField
              label="Completed At"
              value={run.completed_at ? formatTime(run.completed_at) : "-"}
            />
            <MetadataField label="Model ID" value={run.model_id} copyable />
            <MetadataField label="Prompt ID" value={run.prompt_id} copyable />
            <MetadataField label="Temperature" value={run.temperature} />
            <MetadataField label="Seed" value={run.seed} />
          </div>
        </div>

        {/* Summary Section */}
        {run.structured_output_json && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-[#0f172a] mb-3">
              Structured Output
            </h3>
            <div className="bg-[#f8fafc] rounded-lg p-4 space-y-2 text-xs">
              {run.structured_output_json["summary"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">Summary</p>
                  <p className="text-[#0f172a]">
                    {String(run.structured_output_json["summary"])}
                  </p>
                </div>
              )}
              {run.structured_output_json["decision_type"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">Decision Type</p>
                  <p className="text-[#0f172a]">
                    {String(run.structured_output_json["decision_type"])}
                  </p>
                </div>
              )}
              {run.structured_output_json["risk_opinion"] && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">Risk Opinion</p>
                  <p className="text-[#0f172a]">
                    {String(run.structured_output_json["risk_opinion"])}
                  </p>
                </div>
              )}
              {Array.isArray(run.structured_output_json["reason_codes"]) && (
                <div>
                  <p className="text-[#64748b] font-medium mb-1">Reason Codes</p>
                  <div className="flex flex-wrap gap-1">
                    {(run.structured_output_json["reason_codes"] as string[]).map(
                      (code, idx) => (
                        <span
                          key={idx}
                          className="bg-[#e2e8f0] text-[#0f172a] px-2 py-1 rounded text-xs"
                        >
                          {code}
                        </span>
                      )
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
            <h3 className="text-sm font-semibold text-[#0f172a] mb-3">
              Raw Output
            </h3>
            <pre className="bg-[#f8fafc] rounded-lg p-4 overflow-auto text-[11px] text-[#0f172a] font-mono border border-[#e2e8f0] max-h-48">
              {JSON.stringify(run.structured_output_json, null, 2)}
            </pre>
          </div>
        )}

        {!run.structured_output_json && (
          <div className="bg-[#f8fafc] rounded-lg p-4 text-center">
            <p className="text-sm text-[#94a3b8]">No structured output available</p>
          </div>
        )}
      </div>
    </div>
  )
}
