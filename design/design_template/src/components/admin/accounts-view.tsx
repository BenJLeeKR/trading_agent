'use client'

import { useState } from 'react'
import { Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Panel, DetailField } from './panel'
import { DataTable } from './data-table'
import { mockAccounts } from '@/lib/mock-data'
import type { Account } from '@/lib/mock-data'

function formatCurrency(val: number, currency = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val)
}

export function AccountsView() {
  const [selectedAccount, setSelectedAccount] = useState<Account | null>(mockAccounts[0])
  const [search, setSearch] = useState('')

  const filtered = mockAccounts.filter((a) => {
    const q = search.toLowerCase()
    return (
      !q ||
      a.account_id.toLowerCase().includes(q) ||
      a.account_code.toLowerCase().includes(q) ||
      a.client_code.toLowerCase().includes(q)
    )
  })

  return (
    <div className="flex flex-1 min-h-0 h-full">
      {/* Left: Accounts List */}
      <div className="w-72 shrink-0 flex flex-col border-r border-border">
        <div className="p-3 border-b border-border shrink-0">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface-2 border border-border text-muted-foreground text-[12px]">
            <Search size={12} />
            <input
              className="bg-transparent outline-none text-foreground placeholder:text-muted-foreground text-[12px] w-full"
              placeholder="Search accounts..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {filtered.map((account) => {
            const isSelected = selectedAccount?.account_id === account.account_id
            const totalPnl = account.positions.reduce((s, p) => s + p.unrealized_pnl, 0)
            return (
              <button
                key={account.account_id}
                onClick={() => setSelectedAccount(account)}
                className={cn(
                  'w-full text-left px-4 py-3 border-b border-border/50 transition-colors group',
                  isSelected ? 'bg-primary/8 border-l-2 border-l-primary' : 'hover:bg-surface-2/60'
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[12px] font-semibold text-foreground truncate">
                      {account.account_code}
                    </p>
                    <p className="text-[10px] text-muted-foreground tabular-nums">
                      {account.account_id}
                    </p>
                  </div>
                  <span className="text-[10px] text-muted-foreground/70 bg-surface-3/60 border border-border px-1.5 py-0.5 rounded shrink-0">
                    {account.account_type}
                  </span>
                </div>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {formatCurrency(account.cash_balance)}
                  </span>
                  <span
                    className={cn(
                      'text-[11px] font-semibold tabular-nums',
                      totalPnl >= 0 ? 'text-status-success-fg' : 'text-status-error-fg'
                    )}
                  >
                    {totalPnl >= 0 ? '+' : ''}{formatCurrency(totalPnl)}
                  </span>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Right: Account Detail */}
      {selectedAccount ? (
        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-[16px] font-semibold text-foreground">
                {selectedAccount.account_code}
              </h2>
              <p className="text-[12px] text-muted-foreground mt-0.5 font-mono">
                {selectedAccount.account_id}
              </p>
            </div>
            <div className="text-right">
              <p className="text-[11px] text-muted-foreground/70">Cash Balance</p>
              <p className="text-[18px] font-semibold text-foreground tabular-nums">
                {formatCurrency(selectedAccount.cash_balance, selectedAccount.currency)}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-4 gap-4 p-4 rounded-lg bg-surface-1 border border-border">
            <DetailField label="Account ID" value={selectedAccount.account_id} mono />
            <DetailField label="Account Code" value={selectedAccount.account_code} mono />
            <DetailField label="Client Code" value={selectedAccount.client_code} mono />
            <DetailField label="Type" value={selectedAccount.account_type} />
            <DetailField label="Currency" value={selectedAccount.currency} />
            <DetailField label="Last Updated" value={selectedAccount.last_updated} mono />
          </div>

          <Panel
            title="Positions"
            subtitle={`${selectedAccount.positions.length} open position${selectedAccount.positions.length !== 1 ? 's' : ''}`}
            noPadding
            bodyClassName="p-0 overflow-auto"
          >
            {selectedAccount.positions.length === 0 ? (
              <div className="px-4 py-6 text-center text-[12px] text-muted-foreground">
                No open positions
              </div>
            ) : (
              <DataTable
                data={selectedAccount.positions}
                getRowKey={(p) => p.symbol}
                columns={[
                  {
                    key: 'symbol',
                    header: 'Symbol',
                    render: (p) => (
                      <span className="font-semibold text-foreground">{p.symbol}</span>
                    ),
                  },
                  {
                    key: 'qty',
                    header: 'Quantity',
                    className: 'text-right',
                    render: (p) => (
                      <span className="tabular-nums text-foreground/85">
                        {p.quantity.toLocaleString()}
                      </span>
                    ),
                  },
                  {
                    key: 'avg',
                    header: 'Avg Price',
                    className: 'text-right',
                    render: (p) => (
                      <span className="tabular-nums text-foreground/85">
                        {formatCurrency(p.average_price)}
                      </span>
                    ),
                  },
                  {
                    key: 'mkt',
                    header: 'Mkt Price',
                    className: 'text-right',
                    render: (p) => (
                      <span className="tabular-nums text-foreground/85">
                        {formatCurrency(p.market_price)}
                      </span>
                    ),
                  },
                  {
                    key: 'pnl',
                    header: 'Unrealized P&L',
                    className: 'text-right',
                    render: (p) => (
                      <span
                        className={cn(
                          'tabular-nums font-semibold',
                          p.unrealized_pnl >= 0 ? 'text-status-success-fg' : 'text-status-error-fg'
                        )}
                      >
                        {p.unrealized_pnl >= 0 ? '+' : ''}
                        {formatCurrency(p.unrealized_pnl)}
                      </span>
                    ),
                  },
                  {
                    key: 'source',
                    header: 'Source',
                    render: (p) => (
                      <span className="text-muted-foreground text-[11px] capitalize">
                        {p.source_of_truth}
                      </span>
                    ),
                  },
                ]}
              />
            )}
          </Panel>

          <div className="grid grid-cols-3 gap-3">
            <PnlCard
              label="Total Unrealized P&L"
              value={selectedAccount.positions.reduce((s, p) => s + p.unrealized_pnl, 0)}
            />
            <PnlCard label="Open Positions" value={selectedAccount.positions.length} isCount />
            <PnlCard label="Cash Available" value={selectedAccount.cash_balance} />
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-[13px]">
          Select an account to view details
        </div>
      )}
    </div>
  )
}

function PnlCard({
  label,
  value,
  isCount = false,
}: {
  label: string
  value: number
  isCount?: boolean
}) {
  const isNeg = !isCount && value < 0
  return (
    <div className="p-3.5 rounded-lg bg-surface-1 border border-border">
      <p className="text-[10px] font-medium text-muted-foreground/70 uppercase tracking-wide">
        {label}
      </p>
      <p
        className={cn(
          'text-[18px] font-semibold tabular-nums mt-1 leading-tight',
          isCount ? 'text-foreground' : isNeg ? 'text-status-error-fg' : 'text-status-success-fg'
        )}
      >
        {isCount ? value : `${value >= 0 ? '+' : ''}${formatCurrency(value)}`}
      </p>
    </div>
  )
}
