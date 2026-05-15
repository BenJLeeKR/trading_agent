import { useEffect, useState } from "react";
import { getAgentRuns } from "../api/client";
import type { AgentRunResponse } from "../types/api";
import { LoadingSpinner } from "./common/LoadingSpinner";
import { ErrorBanner } from "./common/ErrorBanner";
import { AgentTypeBadge } from "./AgentTypeBadge";
import { formatKstDateTime } from "../lib/utils";

/* ───────────────────────────────────────────
 * Status badge colour
 * ─────────────────────────────────────────── */
function statusVariant(status: string): "success" | "warning" | "error" | "info" {
  switch (status) {
    case "completed": return "success";
    case "running": return "info";
    case "failed": return "error";
    default: return "warning";
  }
}

const STATUS_STYLES: Record<string, string> = {
  success: "bg-[#f0fdf4] text-[#16a34a]",
  warning: "bg-[#fffbeb] text-[#d97706]",
  error: "bg-[#fef2f2] text-[#dc2626]",
  info: "bg-[#eff6ff] text-[#2563eb]",
};

/* ───────────────────────────────────────────
 * Props
 * ─────────────────────────────────────────── */
interface AgentRunsPanelProps {
  decisionContextId: string | null;
}

/* ───────────────────────────────────────────
 * Component
 * ─────────────────────────────────────────── */
export default function AgentRunsPanel({ decisionContextId }: AgentRunsPanelProps) {
  const [runs, setRuns] = useState<AgentRunResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRunIds, setExpandedRunIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!decisionContextId) {
      setRuns([]);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentRuns(decisionContextId)
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
  }, [decisionContextId]);

  function toggleExpand(runId: string) {
    setExpandedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  }

  /* ── No context selected ── */
  if (!decisionContextId) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <h4 className="text-sm font-medium text-[#0f172a] mb-4">에이전트 실행</h4>
        <p className="text-sm text-[#94a3b8] text-center py-4">
          의사결정을 선택하면 AI 에이전트 실행 상세를 볼 수 있습니다.
        </p>
      </div>
    );
  }

  /* ── Loading ── */
  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <h4 className="text-sm font-medium text-[#0f172a] mb-4">에이전트 실행</h4>
        <LoadingSpinner text="에이전트 실행 기록 로딩 중..." />
      </div>
    );
  }

  /* ── Error ── */
  if (error) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <h4 className="text-sm font-medium text-[#0f172a] mb-4">에이전트 실행</h4>
        <ErrorBanner message={error} onDismiss={() => setError(null)} />
      </div>
    );
  }

  /* ── Empty ── */
  if (runs.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
        <h4 className="text-sm font-medium text-[#0f172a] mb-4">에이전트 실행</h4>
        <p className="text-sm text-[#94a3b8] text-center py-4">
          이 의사결정 컨텍스트에 대한 에이전트 실행 기록이 없습니다.
        </p>
      </div>
    );
  }

  /* ── Data ── */
  return (
    <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
      <h4 className="text-sm font-medium text-[#0f172a] mb-4">에이전트 실행</h4>
      <div className="space-y-3">
        {runs.map((run) => {
          const sv = statusVariant(run.status);
          const isExpanded = expandedRunIds.has(run.agent_run_id);

          return (
            <div
              key={run.agent_run_id}
              className="rounded-lg border border-[#e2e8f0] p-3"
            >
              {/* Header row */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <AgentTypeBadge agentType={run.agent_type} />
                  <span className="text-xs text-[#64748b]">
                    {formatKstDateTime(run.started_at)}
                  </span>
                </div>
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[sv]}`}
                >
                  {run.status}
                </span>
              </div>

              {/* Structured output summary — limited key fields */}
              {run.structured_output_json && (
                <div className="text-xs text-[#475569] space-y-0.5 mb-2">
                  {run.structured_output_json.summary !== undefined && (
                    <p><span className="font-medium text-[#64748b]">summary:</span> {String(run.structured_output_json.summary)}</p>
                  )}
                  {run.structured_output_json.reason_codes !== undefined && (
                    <p><span className="font-medium text-[#64748b]">reason_codes:</span> {String(run.structured_output_json.reason_codes)}</p>
                  )}
                  {run.structured_output_json.decision_type !== undefined && (
                    <p><span className="font-medium text-[#64748b]">decision_type:</span> {String(run.structured_output_json.decision_type)}</p>
                  )}
                  {run.structured_output_json.risk_opinion !== undefined && (
                    <p><span className="font-medium text-[#64748b]">risk_opinion:</span> {String(run.structured_output_json.risk_opinion)}</p>
                  )}
                </div>
              )}

              {/* JSON detail toggle */}
              <button
                onClick={() => toggleExpand(run.agent_run_id)}
                className="text-xs text-[#3b82f6] hover:text-[#2563eb] transition-colors"
              >
                {isExpanded ? "원시 출력 숨기기" : "원시 출력 보기"}
              </button>

              {isExpanded && (
                <pre className="mt-2 p-2 bg-[#f8fafc] rounded text-xs text-[#334155] overflow-x-auto max-h-48 overflow-y-auto">
                  {JSON.stringify(run.structured_output_json ?? {}, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
