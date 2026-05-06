import { useState } from "react"
import { FilterBar } from "@/components/FilterBar"
import { DataTable } from "@/components/DataTable"
import { StatusBadge } from "@/components/StatusBadge"
import { WarningBanner } from "@/components/WarningBanner"

// Mock data
const reconciliationRuns = [
  { id: "RUN-001", status: "COMPLETED", triggerType: "SCHEDULED", startedAt: "2024-01-15 09:00:00", completedAt: "2024-01-15 09:05:00", itemsProcessed: 150 },
  { id: "RUN-002", status: "RUNNING", triggerType: "MANUAL", startedAt: "2024-01-15 09:30:00", completedAt: null, itemsProcessed: 45 },
  { id: "RUN-003", status: "FAILED", triggerType: "SCHEDULED", startedAt: "2024-01-15 08:00:00", completedAt: "2024-01-15 08:02:00", itemsProcessed: 12 },
  { id: "RUN-004", status: "COMPLETED", triggerType: "SCHEDULED", startedAt: "2024-01-14 21:00:00", completedAt: "2024-01-14 21:08:00", itemsProcessed: 200 },
]

const activeLocks = [
  { id: "LOCK-001", type: "RECONCILIATION", account: "ACC-001", reason: "Position mismatch detected", createdAt: "2024-01-15 09:00:00" },
  { id: "LOCK-002", type: "POSITION_SYNC", account: "ACC-003", reason: "Cash balance discrepancy", createdAt: "2024-01-15 08:45:00" },
]

export function Reconciliation() {
  const [statusFilter, setStatusFilter] = useState("")
  const [triggerFilter, setTriggerFilter] = useState("")

  const filteredRuns = reconciliationRuns.filter((run) => {
    const matchesStatus = !statusFilter || run.status === statusFilter
    const matchesTrigger = !triggerFilter || run.triggerType === triggerFilter
    return matchesStatus && matchesTrigger
  })

  const runColumns = [
    { key: "id", header: "Run ID", width: "100px" },
    { key: "status", header: "Status", render: (value: string) => {
      const variants: Record<string, "success" | "warning" | "error" | "info"> = {
        COMPLETED: "success",
        RUNNING: "info",
        FAILED: "error",
        PENDING: "warning",
      }
      return <StatusBadge variant={variants[value] || "neutral"}>{value}</StatusBadge>
    }},
    { key: "triggerType", header: "Trigger" },
    { key: "startedAt", header: "Started" },
    { key: "completedAt", header: "Completed", render: (value: string | null) => value || "-" },
    { key: "itemsProcessed", header: "Items" },
  ]

  const lockColumns = [
    { key: "id", header: "Lock ID" },
    { key: "type", header: "Type", render: (value: string) => (
      <StatusBadge variant="error">{value}</StatusBadge>
    )},
    { key: "account", header: "Account" },
    { key: "reason", header: "Reason" },
    { key: "createdAt", header: "Created" },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[#0f172a]">Reconciliation</h1>
        <p className="text-sm text-[#64748b] mt-1">Monitor uncertain states, reconciliation runs, and active locks</p>
      </div>

      {/* Active Warning Banner */}
      {activeLocks.length > 0 && (
        <WarningBanner
          variant="error"
          title={`${activeLocks.length} Active Blocking Locks`}
          message="These locks are preventing normal order processing. Review and resolve as soon as possible."
        />
      )}

      {/* Active Locks Section */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-[#0f172a]">Active Locks</h2>
        {activeLocks.length > 0 ? (
          <DataTable columns={lockColumns} data={activeLocks} idKey="id" />
        ) : (
          <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
            <p className="text-sm text-[#94a3b8]">No active locks</p>
          </div>
        )}
      </div>

      {/* Reconciliation Runs Section */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-[#0f172a]">Reconciliation Runs</h2>
        <FilterBar
          filters={[
            {
              key: "status",
              label: "Status",
              options: [
                { label: "Completed", value: "COMPLETED" },
                { label: "Running", value: "RUNNING" },
                { label: "Failed", value: "FAILED" },
              ],
              value: statusFilter,
              onChange: setStatusFilter,
            },
            {
              key: "trigger",
              label: "Trigger Type",
              options: [
                { label: "Scheduled", value: "SCHEDULED" },
                { label: "Manual", value: "MANUAL" },
              ],
              value: triggerFilter,
              onChange: setTriggerFilter,
            },
          ]}
          onClearAll={() => {
            setStatusFilter("")
            setTriggerFilter("")
          }}
        />
        <DataTable columns={runColumns} data={filteredRuns} idKey="id" />
      </div>
    </div>
  )
}
