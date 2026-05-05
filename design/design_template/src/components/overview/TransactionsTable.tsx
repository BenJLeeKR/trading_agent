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

const platformColors: Record<Transaction['platform'], { bg: string; text: string; dot: string }> = {
  Shopee: { bg: '#fff1ee', text: '#ee4d2d', dot: '#ee4d2d' },
  Tokopedia: { bg: '#edfaf1', text: '#29a35a', dot: '#29a35a' },
  Tiktok: { bg: '#f4f4f4', text: '#111', dot: '#111' },
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
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm flex-1">
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-900">Last transaction</h2>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-200 bg-gray-50 text-xs text-gray-400">
            <Search size={13} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search"
              className="bg-transparent outline-none w-28 text-gray-700 placeholder-gray-400"
            />
          </div>
          <button className="flex items-center justify-center w-8 h-8 rounded-lg border border-gray-200 bg-gray-50 text-gray-500 hover:bg-gray-100 transition-colors">
            <SlidersHorizontal size={13} />
          </button>
        </div>
      </div>

      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="w-8 pl-5 py-2.5">
              <input type="checkbox" className="accent-blue-500 w-3.5 h-3.5" />
            </th>
            <th className="text-left py-2.5 pr-4 text-gray-400 font-medium">Order ID</th>
            <th className="text-left py-2.5 pr-4 text-gray-400 font-medium">Item</th>
            <th className="text-left py-2.5 pr-4 text-gray-400 font-medium">Date</th>
            <th className="text-left py-2.5 pr-4 text-gray-400 font-medium">Price</th>
            <th className="text-left py-2.5 pr-5 text-gray-400 font-medium">Platform</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((t, idx) => {
            const isSelected = selected.includes(idx)
            const platformStyle = platformColors[t.platform]
            return (
              <tr
                key={idx}
                onClick={() => toggleRow(idx)}
                className="border-b border-gray-50 cursor-pointer transition-colors hover:bg-gray-50"
                style={{ backgroundColor: isSelected ? '#f0f4ff' : undefined }}
              >
                <td className="pl-5 py-3">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleRow(idx)}
                    onClick={(e) => e.stopPropagation()}
                    className="accent-blue-500 w-3.5 h-3.5"
                  />
                </td>
                <td className="py-3 pr-4 text-gray-500">{t.id}</td>
                <td className="py-3 pr-4 text-gray-800 font-medium">{t.item}</td>
                <td className="py-3 pr-4 text-gray-500">{t.date}</td>
                <td className="py-3 pr-4 text-gray-800 font-semibold">{t.price}</td>
                <td className="py-3 pr-5">
                  <span
                    className="flex items-center gap-1 px-2 py-1 rounded-full w-fit text-xs font-medium"
                    style={{ backgroundColor: platformStyle.bg, color: platformStyle.text }}
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
  )
}
