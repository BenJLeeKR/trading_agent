import { useState } from "react"
import { FilterBar } from "@/components/FilterBar"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { X } from "lucide-react"

// Mock data
const decisionsData = [
  { id: "DEC-001", symbol: "AAPL", side: "BUY", decisionType: "ENTRY", confidence: 0.85, agentLabel: "momentum-v2", contextId: "CTX-001", createdAt: "2024-01-15 09:30:00" },
  { id: "DEC-002", symbol: "GOOGL", side: "SELL", decisionType: "EXIT", confidence: 0.72, agentLabel: "mean-reversion", contextId: "CTX-002", createdAt: "2024-01-15 09:28:00" },
  { id: "DEC-003", symbol: "MSFT", side: "BUY", decisionType: "SCALE_IN", confidence: 0.91, agentLabel: "trend-follow", contextId: "CTX-003", createdAt: "2024-01-15 09:25:00" },
  { id: "DEC-004", symbol: "TSLA", side: "SELL", decisionType: "STOP_LOSS", confidence: 0.95, agentLabel: "risk-manager", contextId: "CTX-004", createdAt: "2024-01-15 09:20:00" },
  { id: "DEC-005", symbol: "NVDA", side: "BUY", decisionType: "ENTRY", confidence: 0.68, agentLabel: "momentum-v2", contextId: "CTX-005", createdAt: "2024-01-15 09:15:00" },
]

const decisionContext = {
  id: "CTX-001",
  marketCondition: "BULLISH",
  technicalSignals: {
    rsi: 45.2,
    macdSignal: "BUY",
    movingAverage: "ABOVE_200MA",
  },
  fundamentalScore: 7.8,
  riskAssessment: "LOW",
  reasoning: "Strong momentum detected with RSI in healthy range. Price above 200-day MA indicates bullish trend. MACD crossover confirms entry signal.",
}

export function Decisions() {
  const [search, setSearch] = useState("")
  const [sideFilter, setSideFilter] = useState("")
  const [typeFilter, setTypeFilter] = useState("")
  const [selectedDecision, setSelectedDecision] = useState<typeof decisionsData[0] | null>(null)

  const filteredDecisions = decisionsData.filter((decision) => {
    const matchesSearch = decision.symbol.toLowerCase().includes(search.toLowerCase()) ||
      decision.id.toLowerCase().includes(search.toLowerCase())
    const matchesSide = !sideFilter || decision.side === sideFilter
    const matchesType = !typeFilter || decision.decisionType === typeFilter
    return matchesSearch && matchesSide && matchesType
  })

  const decisionColumns = [
    { key: "id", header: "Decision ID", width: "100px" },
    { key: "symbol", header: "Symbol" },
    { key: "side", header: "Side", render: (value: string) => (
      <StatusBadge variant={value === "BUY" ? "success" : "error"}>{value}</StatusBadge>
    )},
    { key: "decisionType", header: "Type" },
    { key: "confidence", header: "Confidence", render: (value: number) => {
      const variant = value >= 0.8 ? "success" : value >= 0.6 ? "warning" : "error"
      return <StatusBadge variant={variant}>{(value * 100).toFixed(0)}%</StatusBadge>
    }},
    { key: "agentLabel", header: "Agent" },
    { key: "createdAt", header: "Created" },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Decisions</h1>
        <p className="text-sm text-[#64748b] mt-1">View AI trade decisions and related context</p>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Decisions List */}
        <div className={selectedDecision ? "col-span-7" : "col-span-12"}>
          <FilterBar
            searchPlaceholder="Search symbol or decision ID..."
            searchValue={search}
            onSearchChange={setSearch}
            filters={[
              {
                key: "side",
                label: "Side",
                options: [
                  { label: "Buy", value: "BUY" },
                  { label: "Sell", value: "SELL" },
                ],
                value: sideFilter,
                onChange: setSideFilter,
              },
              {
                key: "type",
                label: "Decision Type",
                options: [
                  { label: "Entry", value: "ENTRY" },
                  { label: "Exit", value: "EXIT" },
                  { label: "Scale In", value: "SCALE_IN" },
                  { label: "Stop Loss", value: "STOP_LOSS" },
                ],
                value: typeFilter,
                onChange: setTypeFilter,
              },
            ]}
            onClearAll={() => {
              setSearch("")
              setSideFilter("")
              setTypeFilter("")
            }}
          />
          <DataTable
            columns={decisionColumns}
            data={filteredDecisions}
            onRowClick={setSelectedDecision}
            selectedId={selectedDecision?.id}
            idKey="id"
          />
        </div>

        {/* Decision Detail Panel */}
        {selectedDecision && (
          <div className="col-span-5 space-y-4">
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-[#0f172a]">Decision Detail</h3>
                <button
                  onClick={() => setSelectedDecision(null)}
                  className="p-1 text-[#94a3b8] hover:text-[#64748b] transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Decision ID</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedDecision.id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Symbol</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedDecision.symbol}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Side</dt>
                  <dd><StatusBadge variant={selectedDecision.side === "BUY" ? "success" : "error"}>{selectedDecision.side}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Decision Type</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{selectedDecision.decisionType}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Confidence</dt>
                  <dd><StatusBadge variant={selectedDecision.confidence >= 0.8 ? "success" : "warning"}>{(selectedDecision.confidence * 100).toFixed(0)}%</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Agent</dt>
                  <dd className="text-sm font-mono text-[#0f172a]">{selectedDecision.agentLabel}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Context ID</dt>
                  <dd className="text-sm font-mono text-[#3b82f6]">{selectedDecision.contextId}</dd>
                </div>
              </dl>
            </div>

            {/* Decision Context */}
            <div className="bg-white rounded-xl border border-[#e2e8f0] p-5">
              <h4 className="text-sm font-medium text-[#0f172a] mb-4">Decision Context</h4>
              <dl className="space-y-3">
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Market Condition</dt>
                  <dd><StatusBadge variant="success">{decisionContext.marketCondition}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">RSI</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{decisionContext.technicalSignals.rsi}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">MACD Signal</dt>
                  <dd><StatusBadge variant="success">{decisionContext.technicalSignals.macdSignal}</StatusBadge></dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Moving Average</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{decisionContext.technicalSignals.movingAverage}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Fundamental Score</dt>
                  <dd className="text-sm font-medium text-[#0f172a]">{decisionContext.fundamentalScore}/10</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-sm text-[#64748b]">Risk Assessment</dt>
                  <dd><StatusBadge variant="success">{decisionContext.riskAssessment}</StatusBadge></dd>
                </div>
              </dl>
              <div className="mt-4 pt-4 border-t border-[#e2e8f0]">
                <dt className="text-sm text-[#64748b] mb-2">Reasoning</dt>
                <dd className="text-sm text-[#0f172a] leading-relaxed">{decisionContext.reasoning}</dd>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
