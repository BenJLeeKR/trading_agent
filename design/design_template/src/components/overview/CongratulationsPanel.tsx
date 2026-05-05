import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const products = [
  {
    name: 'T-shirt Rainblow White',
    sold: 271,
    color: '#1a1a2e',
    textColor: 'white',
    image: 'https://hebbkx1anhila5yf.public.blob.vercel-storage.com/image-lZRFKHpdfhhVJrfpzI5YOoUUK7BIOk.png',
  },
  {
    name: 'Crop Top Pants',
    sold: 198,
    color: '#f0f0f0',
    textColor: '#1a1a1a',
  },
  {
    name: 'Huzzle Black Cap',
    sold: 147,
    color: '#f59e0b',
    textColor: 'white',
  },
]

export default function CongratulationsPanel() {
  const [activeIdx, setActiveIdx] = useState(0)

  const prev = () => setActiveIdx((i) => (i - 1 + products.length) % products.length)
  const next = () => setActiveIdx((i) => (i + 1) % products.length)

  const active = products[activeIdx]

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm w-72 shrink-0 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-5 pb-3">
        <div className="flex items-center gap-1 mb-1">
          <span className="text-sm font-semibold text-gray-900">Congratulations!</span>
          <span className="text-base">🎉</span>
        </div>
        <p className="text-xs text-gray-400 leading-relaxed">
          Some of your products already have the highest buyers
        </p>
      </div>

      {/* Product carousel */}
      <div className="relative flex-1 px-4 pb-4">
        <div className="relative flex items-end justify-center gap-2 h-44 overflow-hidden rounded-xl bg-gray-50">
          {/* Background product cards */}
          {products.map((p, idx) => {
            const offset = idx - activeIdx
            const absOffset = Math.abs(offset)
            if (absOffset > 1) return null
            return (
              <div
                key={idx}
                className="absolute transition-all duration-300 flex flex-col items-center justify-end pb-3"
                style={{
                  transform: `translateX(${offset * 80}px) scale(${offset === 0 ? 1 : 0.82})`,
                  zIndex: offset === 0 ? 10 : 5,
                  opacity: offset === 0 ? 1 : 0.5,
                  bottom: 0,
                  width: 100,
                  height: 140,
                }}
              >
                <div
                  className="w-full h-full rounded-xl flex items-center justify-center"
                  style={{ backgroundColor: p.color }}
                >
                  <span className="text-3xl">👕</span>
                </div>
              </div>
            )
          })}

          {/* Nav buttons */}
          <button
            onClick={prev}
            className="absolute left-2 top-1/2 -translate-y-1/2 z-20 w-6 h-6 bg-white rounded-full shadow-md flex items-center justify-center text-gray-500 hover:text-gray-800 border border-gray-100 transition-colors"
          >
            <ChevronLeft size={12} />
          </button>
          <button
            onClick={next}
            className="absolute right-2 top-1/2 -translate-y-1/2 z-20 w-6 h-6 bg-white rounded-full shadow-md flex items-center justify-center text-gray-500 hover:text-gray-800 border border-gray-100 transition-colors"
          >
            <ChevronRight size={12} />
          </button>
        </div>

        {/* Active product info */}
        <div className="mt-3 text-center">
          <p className="text-sm font-semibold text-gray-900">{active.name}</p>
          <p className="text-xs text-gray-400 mt-0.5">{active.sold} sold</p>

          {/* Dots */}
          <div className="flex items-center justify-center gap-1.5 mt-2">
            {products.map((_, idx) => (
              <button
                key={idx}
                onClick={() => setActiveIdx(idx)}
                className="rounded-full transition-all"
                style={{
                  width: activeIdx === idx ? 20 : 6,
                  height: 6,
                  backgroundColor: activeIdx === idx ? '#3b82f6' : '#d1d5db',
                }}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Top products list */}
      <div className="border-t border-gray-100 px-5 py-3">
        <p className="text-xs font-semibold text-gray-500 mb-2">Top Sellers</p>
        {products.slice(0, 3).map((p, idx) => (
          <div key={idx} className="flex items-center justify-between py-1.5">
            <div className="flex items-center gap-2">
              <div
                className="w-6 h-6 rounded-md flex items-center justify-center text-xs"
                style={{ backgroundColor: p.color }}
              >
                <span>👕</span>
              </div>
              <span className="text-xs text-gray-700 truncate max-w-[120px]">{p.name}</span>
            </div>
            <span className="text-xs font-semibold text-gray-500">{p.sold}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
