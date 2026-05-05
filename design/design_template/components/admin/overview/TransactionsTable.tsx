'use client'

import { useState } from 'react'
import { Search, SlidersHorizontal } from 'lucide-react'

interface Transaction {
  id: string
  item: string
  date: string
  price: string
  platform: 'Shopee' | 'Tokopedia' | 'Tiktok'
}

const transactions: Transaction[] = [
  { id: 'CTG0291', item: 'Crop top pants', date: '12/02/2022', price: '$599', platform: 'Shopee' },
  { id: 'CTG0291', item: 'T-shirt rainbow...', date: '12/02/2022', price: '$49', platform: 'Tokopedia' },
  { id: 'CTG0291', item: 'Huzzle black cap', date: '12/02/2022', price: '$109', platform: 'Tokopedia' },
  { id: 'CTG0291', item: 'Crop top pants', date: '12/02/2022', price: '$666', platform: 'Shopee' },
  { id: 'CTG0291', item: 'Crop top pants', date: '12/02/2022', price: '$239', platform: 'Tiktok' },
]

const platformStyle: Record<Transaction['platform'], { bg: string; text: string }> = {
  Shopee: { bg: '#fff1ee', text: '#ee4d2d' },
  Tokopedia: { bg: '#edfaf1', text: '#29a35a' },
  Tiktok: { bg: '#f4f4f4', text: '#111827' },
}

const platformEmoji: Record<Transaction['platform'], string> = {
  Shopee: '🛍️',
  Tokopedia: '🟢',
  Tiktok: '🎵',
}

export default function TransactionsTable() {
  const [selected, setSelected] = useState<number[]>([1])
  const [search, setSearch] = useState('')

  const toggleRow = (idx: number) => {
    setSelected((prev) =>
      prev.includes(idx) ? prev.filter((i) => i !== idx) : [...prev, idx]
    )
  }

  const filtered = transactions.filter(
    (t) =>
      t.item.toLowerCase().includes(search.toLowerCase()) ||
      t.id.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div
      className="bg-white rounded-xl border shadow-sm overflow-hidden"
      style={{ borderColor: '#e8eaed' }}
    >
      {/* Table header */}
      <div
        className="flex items-center justify-between px-5 py-3.5 border-b"
        style={{ borderColor: '#e8eaed' }}
      >
        <h2 className="text-sm font-semibold text-gray-900">Last transaction</h2>
        <div className="flex items-center gap-2">
          <div
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs text-gray-400"
            style={{ backgroundColor: '#f9fafb', borderColor: '#e8eaed' }}
          >
            <Search size={12} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search"
              className="bg-transparent outline-none w-24 text-gray-700 placeholder-gray-400 text-xs"
            />
          </div>
          <button
            className="flex items-center justify-center w-8 h-8 rounded-lg border text-gray-500 hover:bg-gray-100 transition-colors"
            style={{ backgroundColor: '#f9fafb', borderColor: '#e8eaed' }}
          >
            <SlidersHorizontal size={13} />
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
              <th className="w-10 pl-5 py-2.5 text-left">
                <input type="checkbox" className="w-3.5 h-3.5 accent-blue-500" />
              </th>
              <th className="py-2.5 pr-4 text-left text-xs font-medium text-gray-400">Order ID</th>
              <th className="py-2.5 pr-4 text-left text-xs font-medium text-gray-400">Item</th>
              <th className="py-2.5 pr-4 text-left text-xs font-medium text-gray-400">Date</th>
              <th className="py-2.5 pr-4 text-left text-xs font-medium text-gray-400">Price</th>
              <th className="py-2.5 pr-5 text-left text-xs font-medium text-gray-400">Platform</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t, idx) => {
              const isSelected = selected.includes(idx)
              const ps = platformStyle[t.platform]
              return (
                <tr
                  key={idx}
                  onClick={() => toggleRow(idx)}
                  className="cursor-pointer transition-colors"
                  style={{
                    backgroundColor: isSelected ? '#f0f4ff' : undefined,
                    borderBottom: '1px solid #f9fafb',
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected)
                      (e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb'
                  }}
                  onMouseLeave={(e) => {
                    ;(e.currentTarget as HTMLElement).style.backgroundColor = isSelected
                      ? '#f0f4ff'
                      : ''
                  }}
                >
                  <td className="pl-5 py-3">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleRow(idx)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-3.5 h-3.5 accent-blue-500"
                    />
                  </td>
                  <td className="py-3 pr-4 text-xs text-gray-500">{t.id}</td>
                  <td className="py-3 pr-4 text-xs text-gray-800 font-medium">{t.item}</td>
                  <td className="py-3 pr-4 text-xs text-gray-500">{t.date}</td>
                  <td className="py-3 pr-4 text-xs text-gray-900 font-semibold">{t.price}</td>
                  <td className="py-3 pr-5">
                    <span
                      className="flex items-center gap-1 px-2 py-1 rounded-full w-fit text-xs font-medium"
                      style={{ backgroundColor: ps.bg, color: ps.text }}
                    >
                      <span>{platformEmoji[t.platform]}</span>
                      {t.platform}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
