import { useState, Fragment, useCallback } from "react";
import { ChevronRight, ChevronDown, Copy } from "lucide-react";
import type { AgentRunResponse } from "../types/api";
import { AgentTypeBadge } from "./AgentTypeBadge";
import { StatusBadge } from "./common/StatusBadge";
import { cn, formatKstTime, formatKstDateTime } from "@/lib/utils";
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

/** 에이전트 타입 한글 라벨 */
function agentTypeLabel(agentType: string): string {
  if (agentType.includes("event_interpretation")) return "Event Interpretation";
  if (agentType.includes("ai_risk")) return "AI Risk";
  if (agentType.includes("final_decision_composer")) return "Final Decision Composer";
  return agentType;
}

/* ──────────────────────────────────────────────
 * 구조화된 출력 확장형 Key/Value 뷰
 * ────────────────────────────────────────────── */

/** 값 표시 규칙에 따라 렌더링 */
function StructuredValue({
  value,
  path,
  expandedPaths,
  onToggle,
  onCopy,
  copiedField,
}: {
  value: unknown;
  path: string;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  onCopy: (text: string, field: string) => void;
  copiedField: string | null;
}) {
  if (value === null || value === undefined) {
    return <span className="structured-output-value-null">-</span>;
  }

  if (typeof value === "string") {
    if (value.length < 50) {
      return <span className="structured-output-value">{value}</span>;
    }
    // 긴 문자열: 앞 50자 + 더보기
    const isExpanded = expandedPaths.has(path);
    if (isExpanded) {
      return (
        <span className="structured-output-value">
          {value}
          <button
            className="structured-output-value-toggle"
            onClick={(e) => { e.stopPropagation(); onToggle(path); }}
          >
            접기
          </button>
        </span>
      );
    }
    return (
      <span className="structured-output-value">
        {value.substring(0, 50)}
        <span className="structured-output-value-ellipsis">...</span>
        <button
          className="structured-output-value-toggle"
          onClick={(e) => { e.stopPropagation(); onToggle(path); }}
        >
          더보기
        </button>
      </span>
    );
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="structured-output-value">{String(value)}</span>;
  }

  if (Array.isArray(value)) {
    const isExpanded = expandedPaths.has(path);
    if (isExpanded) {
      return (
        <div className="structured-output-array">
          <button
            className="structured-output-nested-toggle"
            onClick={(e) => { e.stopPropagation(); onToggle(path); }}
          >
            ▼ 배열 ({value.length}개 항목)
          </button>
          <div className="structured-output-nested-content">
            {value.slice(0, 3).map((item, idx) => (
              <div key={idx} className="structured-output-array-item">
                <span className="structured-output-array-index">[{idx}]</span>
                <StructuredValue
                  value={item}
                  path={`${path}[${idx}]`}
                  expandedPaths={expandedPaths}
                  onToggle={onToggle}
                  onCopy={onCopy}
                  copiedField={copiedField}
                />
              </div>
            ))}
            {value.length > 3 && (
              <div className="structured-output-array-more">+{value.length - 3} more</div>
            )}
          </div>
        </div>
      );
    }
    return (
      <button
        className="structured-output-nested-toggle"
        onClick={(e) => { e.stopPropagation(); onToggle(path); }}
      >
        ▶ [{value.length}개 항목]
      </button>
    );
  }

  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>);
    const isExpanded = expandedPaths.has(path);
    if (isExpanded) {
      return (
        <div className="structured-output-nested-object">
          <button
            className="structured-output-nested-toggle"
            onClick={(e) => { e.stopPropagation(); onToggle(path); }}
          >
            ▼ 객체 ({keys.length}개 필드)
          </button>
          <div className="structured-output-nested-content">
            {keys.map((k) => (
              <StructuredKeyValueRow
                key={k}
                label={k}
                value={(value as Record<string, unknown>)[k]}
                parentPath={`${path}.${k}`}
                expandedPaths={expandedPaths}
                onToggle={onToggle}
                onCopy={onCopy}
                copiedField={copiedField}
              />
            ))}
          </div>
        </div>
      );
    }
    return (
      <button
        className="structured-output-nested-toggle"
        onClick={(e) => { e.stopPropagation(); onToggle(path); }}
      >
        ▶ 객체 ({keys.length}개 필드)
      </button>
    );
  }

  return <span className="structured-output-value">{String(value)}</span>;
}

function StructuredKeyValueRow({
  label,
  value,
  parentPath,
  expandedPaths,
  onToggle,
  onCopy,
  copiedField,
}: {
  label: string;
  value: unknown;
  parentPath: string;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  onCopy: (text: string, field: string) => void;
  copiedField: string | null;
}) {
  return (
    <div className="structured-output-key-value-row">
      <span className="structured-output-key">{label}</span>
      <StructuredValue
        value={value}
        path={parentPath}
        expandedPaths={expandedPaths}
        onToggle={onToggle}
        onCopy={onCopy}
        copiedField={copiedField}
      />
    </div>
  );
}

function StructuredOutputCell({ run }: { run: AgentRunResponse }) {
  const [expanded, setExpanded] = useState(false);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const so = run.structured_output_json;
  const hasStructuredOutput = so !== null && so !== undefined && typeof so === "object" && Object.keys(so).length > 0;

  const togglePath = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const copyToClipboard = useCallback((text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  }, []);

  if (!hasStructuredOutput) {
    return <span className="text-[#94a3b8]">-</span>;
  }

  const keys = Object.keys(so as Record<string, unknown>);
  const topKeys = keys.slice(0, 3);
  const remaining = keys.length - 3;

  if (!expanded) {
    return (
      <div className="structured-output-section">
        <span className="structured-output-collapsed-keys">
          {topKeys.join(", ")}
          {remaining > 0 && <span className="structured-output-more-indicator"> +{remaining} more</span>}
        </span>
        <button
          className="structured-output-toggle"
          onClick={(e) => { e.stopPropagation(); setExpanded(true); }}
        >
          <ChevronRight className="h-3 w-3" />
          구조화된 출력 펼치기
        </button>
      </div>
    );
  }

  return (
    <div className="structured-output-section">
      <div className="structured-output-header">
        <button
          className="structured-output-toggle"
          onClick={(e) => { e.stopPropagation(); setExpanded(false); }}
        >
          <ChevronDown className="h-3 w-3" />
          구조화된 출력
        </button>
        <button
          className="structured-output-copy-all"
          onClick={(e) => {
            e.stopPropagation();
            copyToClipboard(JSON.stringify(so, null, 2), "structured_output_json");
          }}
          title="전체 JSON 복사"
        >
          <Copy className={`h-3 w-3 ${copiedField === "structured_output_json" ? "text-[#16a34a]" : ""}`} />
          {copiedField === "structured_output_json" ? " 복사됨" : " 전체 JSON 복사"}
        </button>
      </div>
      <div className="structured-output-key-value">
        {keys.map((k) => (
          <StructuredKeyValueRow
            key={k}
            label={k}
            value={(so as Record<string, unknown>)[k]}
            parentPath={k}
            expandedPaths={expandedPaths}
            onToggle={togglePath}
            onCopy={copyToClipboard}
            copiedField={copiedField}
          />
        ))}
      </div>
    </div>
  );
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
              <th className="px-4 py-3 text-left text-xs font-medium text-[#64748b] uppercase tracking-wider">
                구조화된 출력
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
                  <td className="px-4 py-3 text-sm max-w-[300px]">
                    <StructuredOutputCell run={run} />
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
