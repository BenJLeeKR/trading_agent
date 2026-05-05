'use client'

import { useState, useMemo } from 'react'
import { Search, SlidersHorizontal, CheckCircle2, Circle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Panel, DetailField, SectionDivider } from './panel'
import { DataTable } from './data-table'
import { OrderStatusBadge } from './status-badge'
import { mockOrders } from '@/lib/mock-data'
import type { Order, OrderStatus, Side } from '@/lib/mock-data'

const ALL_STATUSES: OrderStatus[] = [
  'filled', 'pending_submit', 'submitted', 'rejected', 'error',
  'cancelled', 'reconcile_required', 'partially_filled', 'acknowledged',
]
const ALL_SIDES: Side[] = ['Buy', 'Sell']
const ALL_SYMBOLS = [...new Set(mockOrders.map((o) => o.symbol))].sort()

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium border transition-colors',
        active
          ? 'bg-primary/15 border-primary/40 text-primary'
          : 'bg-surface-2/50 border-border text-muted-foreground hover:text-foreground hover:border-border/80'
      )}
    >
      {active ? <CheckCircle2 size={11} /> : <Circle size={11} />}
      {label}
    </button>
  )
}

export function OrdersView() {
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(mockOrders[0])
  const [search, setSearch] = useState('')
  const [filterSymbols, setFilterSymbols] = useState<Set<string>>(new Set())
  const [filterSides, setFilterSides] = useState<Set<Side>>(new Set())
  const [filterStatuses, setFilterStatuses] = useState<Set<OrderStatus>>(new Set())

  function toggleSet<T>(set: Set<T>, val: T): Set<T> {
    const next = new Set(set)
    next.has(val) ? next.delete(val) : next.add(val)
    return next
  }

  const filtered = useMemo(() => {
    return mockOrders.filter((o) => {
      if (
        search &&
        !o.symbol.toLowerCase().includes(search.toLowerCase()) &&
        !o.order_request_id.toLowerCase().includes(search.toLowerCase())
      )
        return false
      if (filterSymbols.size > 0 && !filterSymbols.has(o.symbol)) return false
      if (filterSides.size > 0 && !filterSides.has(o.side)) return false
      if (filterStatuses.size > 0 && !filterStatuses.has(o.status)) return false
      return true
    })
  }, [search, filterSymbols, filterSides, filterStatuses])

  return (
    <div className="flex flex-col gap-0 h-full">
      {/* Filter Bar */}
      <div className="shrink-0 flex flex-wrap items-center gap-3 px-5 py-3 border-b border-border bg-card/20">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface-2 border border-border text-muted-foreground text-[12px] w-44">
          <Search size={12} />
          <input
            className="bg-transparent outline-none text-foreground placeholder:text-muted-foreground text-[12px] w-full"
            placeholder="Symbol or ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-1.5">
          <SlidersHorizontal size={11} className="text-muted-foreground/60" />
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60 font-medium">Symbol</span>
          {ALL_SYMBOLS.map((s) => (
            <FilterChip
              key={s}
              label={s}
              active={filterSymbols.has(s)}
              onClick={() => setFilterSymbols(toggleSet(filterSymbols, s))}
            />
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60 font-medium">Side</span>
          {ALL_SIDES.map((s) => (
            <FilterChip
              key={s}
              label={s}
              active={filterSides.has(s)}
              onClick={() => setFilterSides(toggleSet(filterSides, s))}
            />
          ))}
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60 font-medium">Status</span>
          {ALL_STATUSES.map((s) => (
            <FilterChip
              key={s}
              label={s.replace(/_/g, ' ')}
              active={filterStatuses.has(s)}
              onClick={() => setFilterStatuses(toggleSet(filterStatuses, s))}
            />
          ))}
        </div>

        <div className="ml-auto text-[11px] text-muted-foreground tabular-nums">
          {filtered.length} / {mockOrders.length} orders
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 min-h-0 gap-0">
        {/* Orders List */}
        <div className="flex-1 overflow-hidden flex flex-col">
          <Panel
            className="flex-1 rounded-none border-0 border-r border-border"
            bodyClassName="p-0 overflow-auto"
            noPadding
          >
            <DataTable
              data={filtered}
              getRowKey={(o) => o.order_request_id}
              selectedKey={selectedOrder?.order_request_id}
              onRowClick={(o) =>
                setSelectedOrder(
                  o.order_request_id === selectedOrder?.order_request_id ? null : o
                )
              }
              columns={[
                {
                  key: 'id',
                  header: 'Order ID',
                  render: (o) => (
                    <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                      {o.order_request_id}
                    </span>
                  ),
                },
                {
                  key: 'symbol',
                  header: 'Symbol',
                  render: (o) => <span className="font-semibold text-foreground">{o.symbol}</span>,
                },
                {
                  key: 'side',
                  header: 'Side',
                  render: (o) => (
                    <span
                      className={cn(
                        'font-semibold text-[11px]',
                        o.side === 'Buy' ? 'text-status-success-fg' : 'text-status-error-fg'
                      )}
                    >
                      {o.side}
                    </span>
                  ),
                },
                {
                  key: 'qty',
                  header: 'Qty',
                  className: 'text-right',
                  render: (o) => (
                    <span className="tabular-nums text-foreground/80 text-[12px]">
                      {o.quantity.toLocaleString()}
                    </span>
                  ),
                },
                {
                  key: 'status',
                  header: 'Status',
                  render: (o) => <OrderStatusBadge status={o.status} />,
                },
                {
                  key: 'agent',
                  header: 'Agent',
                  render: (o) => (
                    <span className="text-muted-foreground text-[11px]">{o.agent_label}</span>
                  ),
                },
                {
                  key: 'time',
                  header: 'Created',
                  render: (o) => (
                    <span className="text-muted-foreground tabular-nums font-mono text-[10px]">
                      {o.created_at}
                    </span>
                  ),
                },
              ]}
            />
          </Panel>
        </div>

        {/* Detail Panel */}
        {selectedOrder && (
          <div className="w-80 shrink-0 overflow-y-auto border-l border-border bg-surface-1/50">
            <OrderDetailPanel order={selectedOrder} />
          </div>
        )}
      </div>
    </div>
  )
}

function OrderDetailPanel({ order }: { order: Order }) {
  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[14px] font-semibold text-foreground">{order.symbol}</p>
          <p className="text-[11px] text-muted-foreground mt-0.5 font-mono">{order.order_request_id}</p>
        </div>
        <OrderStatusBadge status={order.status} />
      </div>

      <SectionDivider label="Order Details" />
      <div className="grid grid-cols-2 gap-3">
        <DetailField
          label="Side"
          value={
            <span
              className={cn(
                'font-semibold',
                order.side === 'Buy' ? 'text-status-success-fg' : 'text-status-error-fg'
              )}
            >
              {order.side}
            </span>
          }
        />
        <DetailField label="Quantity" value={order.quantity.toLocaleString()} mono />
        <DetailField label="Agent" value={order.agent_label} />
        <DetailField label="Account" value={order.account_id} mono />
        {order.filled_quantity !== undefined && (
          <DetailField label="Filled Qty" value={order.filled_quantity.toLocaleString()} mono />
        )}
        {order.avg_price !== undefined && (
          <DetailField label="Avg Price" value={`$${order.avg_price.toFixed(2)}`} mono />
        )}
      </div>

      <SectionDivider label="Identifiers" />
      <div className="flex flex-col gap-2.5">
        <DetailField label="Correlation ID" value={order.correlation_id} mono />
        <DetailField label="Created At" value={order.created_at} mono />
        {order.broker && <DetailField label="Broker" value={order.broker} />}
      </div>

      {order.state_events && order.state_events.length > 0 && (
        <>
          <SectionDivider label="State Events" />
          <div className="flex flex-col gap-0">
            {order.state_events.map((ev, i) => (
              <div key={i} className="relative flex gap-3 pb-3 last:pb-0">
                {i < order.state_events!.length - 1 && (
                  <div className="absolute left-[5px] top-4 bottom-0 w-px bg-border/50" />
                )}
                <div className="w-3 h-3 rounded-full border-2 border-primary/50 bg-surface-2 shrink-0 mt-0.5 z-10" />
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-semibold text-foreground capitalize">
                    {ev.event.replace(/_/g, ' ')}
                  </p>
                  <p className="text-[10px] text-muted-foreground tabular-nums font-mono">
                    {ev.timestamp}
                  </p>
                  {ev.detail && (
                    <p className="text-[10px] text-muted-foreground/70 mt-0.5">{ev.detail}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
