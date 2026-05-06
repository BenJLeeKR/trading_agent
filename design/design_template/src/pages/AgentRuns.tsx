import { useState, useMemo } from "react"
import { Search } from "lucide-react"
import { AgentRunResponse } from "@/types/agentRun"
import { AgentRunsTable } from "@/components/AgentRunsTable"
import { AgentRunDetailPanel } from "@/components/AgentRunDetailPanel"

// Mock data - in production, this would come from an API
const mockAgentRuns: AgentRunResponse[] = [
  {
    agent_run_id: "ar_20240115_001",
    decision_context_id: "dc_2024011509302500",
    agent_type: "event_interpretation",
    started_at: "2024-01-15T09:30:25.000Z",
    completed_at: "2024-01-15T09:30:28.500Z",
    model_id: "gpt-4-turbo",
    prompt_id: "prompt_ei_v2",
    temperature: 0.7,
    seed: 42,
    raw_output_uri: "s3://outputs/ar_20240115_001.json",
    structured_output_json: {
      summary: "Market volatility spike detected in tech sector",
      decision_type: "alert",
      reason_codes: ["VOL_SPIKE", "TECH_SECTOR"],
    },
    status: "completed",
    created_at: "2024-01-15T09:30:25.000Z",
  },
  {
    agent_run_id: "ar_20240115_002",
    decision_context_id: "dc_2024011509282100",
    agent_type: "ai_risk",
    started_at: "2024-01-15T09:28:21.000Z",
    completed_at: "2024-01-15T09:28:35.200Z",
    model_id: "gpt-4-turbo",
    prompt_id: "prompt_ar_v3",
    temperature: 0.5,
    seed: 123,
    raw_output_uri: "s3://outputs/ar_20240115_002.json",
    structured_output_json: {
      summary: "Risk score elevated for position XYZ",
      risk_opinion: "high_risk",
      reason_codes: ["POSITION_CONCENTRATION", "MARKET_EXPOSURE"],
    },
    status: "completed",
    created_at: "2024-01-15T09:28:21.000Z",
  },
  {
    agent_run_id: "ar_20240115_003",
    decision_context_id: "dc_2024011509252100",
    agent_type: "final_decision_composer",
    started_at: "2024-01-15T09:25:21.000Z",
    completed_at: "2024-01-15T09:25:45.800Z",
    model_id: "gpt-4",
    prompt_id: "prompt_fdc_v1",
    temperature: 0.3,
    seed: 789,
    raw_output_uri: "s3://outputs/ar_20240115_003.json",
    structured_output_json: {
      summary: "Final recommendation: reduce position by 25%",
      decision_type: "reduce_position",
      reason_codes: ["RISK_THRESHOLD", "PROFIT_TAKING"],
    },
    status: "completed",
    created_at: "2024-01-15T09:25:21.000Z",
  },
  {
    agent_run_id: "ar_20240115_004",
    decision_context_id: "dc_2024011509151000",
    agent_type: "event_interpretation",
    started_at: "2024-01-15T09:15:10.000Z",
    completed_at: null,
    model_id: "gpt-4-turbo",
    prompt_id: "prompt_ei_v2",
    temperature: 0.7,
    seed: null,
    raw_output_uri: null,
    structured_output_json: null,
    status: "running",
    created_at: "2024-01-15T09:15:10.000Z",
  },
  {
    agent_run_id: "ar_20240115_005",
    decision_context_id: "dc_2024011509100500",
    agent_type: "ai_risk",
    started_at: "2024-01-15T09:10:05.000Z",
    completed_at: "2024-01-15T09:10:12.300Z",
    model_id: null,
    prompt_id: null,
    temperature: null,
    seed: null,
    raw_output_uri: null,
    structured_output_json: null,
    status: "failed",
    created_at: "2024-01-15T09:10:05.000Z",
  },
  {
    agent_run_id: "ar_20240115_006",
    decision_context_id: "dc_2024011508552000",
    agent_type: "final_decision_composer",
    started_at: "2024-01-15T08:55:20.000Z",
    completed_at: "2024-01-15T08:56:02.100Z",
    model_id: "gpt-4",
    prompt_id: "prompt_fdc_v1",
    temperature: 0.3,
    seed: 456,
    raw_output_uri: "s3://outputs/ar_20240115_006.json",
    structured_output_json: {
      summary: "Maintain current positions - market conditions stable",
      decision_type: "hold",
      reason_codes: ["STABLE_MARKET", "NO_SIGNALS"],
    },
    status: "completed",
    created_at: "2024-01-15T08:55:20.000Z",
  },
]

export function AgentRuns() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [agentTypeFilter, setAgentTypeFilter] = useState<string>("all")
  const [statusFilter, setStatusFilter] = useState<string>("all")

  const filteredRuns = useMemo(() => {
    return mockAgentRuns.filter((run) => {
      const matchesSearch =
        run.agent_run_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        run.decision_context_id.toLowerCase().includes(searchQuery.toLowerCase())

      const matchesAgentType =
        agentTypeFilter === "all" || run.agent_type.includes(agentTypeFilter)

      const matchesStatus =
        statusFilter === "all" || run.status.toLowerCase() === statusFilter.toLowerCase()

      return matchesSearch && matchesAgentType && matchesStatus
    })
  }, [searchQuery, agentTypeFilter, statusFilter])

  const selectedRun = selectedRunId
    ? filteredRuns.find((r) => r.agent_run_id === selectedRunId) || null
    : null

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
              value={agentTypeFilter}
              onChange={(e) => setAgentTypeFilter(e.target.value)}
              className="px-3 py-2 border border-[#e2e8f0] rounded-lg text-sm text-[#0f172a] focus:outline-none focus:ring-2 focus:ring-[#3b82f6] focus:border-transparent cursor-pointer"
            >
              <option value="all">All</option>
              <option value="event_interpretation">Event Interpretation (EI)</option>
              <option value="ai_risk">AI Risk (AR)</option>
              <option value="final_decision_composer">
                Final Decision Composer (FDC)
              </option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[#64748b] uppercase tracking-wider">
              Status
            </label>
            <select
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
            selectedId={selectedRunId}
            onRowClick={(run) => setSelectedRunId(run.agent_run_id)}
          />
        </div>

        {/* Right: Detail Panel */}
        <div className="lg:col-span-1">
          <AgentRunDetailPanel run={selectedRun} />
        </div>
      </div>
    </div>
  )
}
