'use client'

import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const products = [
  { name: 'T-shirt Rainblow White', sold: 271, bg: '#1a1a2e', emoji: '👕' },
  { name: 'Crop Top Pants', sold: 198, bg: '#f0f0f0', emoji: '👖' },
  { name: 'Huzzle Black Cap', sold: 147, bg: '#f59e0b', emoji: '🧢' },
]

export default function CongratulationsPanel() {
  const [idx, setIdx] = useState(0)

  const prev = () => setIdx((i) => (i - 1 + products.length) % products.length)
  const next = () => setIdx((i) => (i + 1) % products.length)
  const active = products[idx]

  return (
    <div
      className="bg-white rounded-xl border shadow-sm flex flex-col shrink-0 overflow-hidden"
      style={{ width: 268, borderColor: '#e8eaed' }}
    >
      {/* Header */}
      <div className="px-5 pt-4 pb-2">
        <div className="flex items-center gap-1 mb-0.5">
          <span className="text-sm font-semibold text-gray-900">Congratulations!</span>
          <span className="text-sm">🎉</span>
        </div>
        <p className="text-xs text-gray-400 leading-relaxed">
          Some of your products already have the highest buyers
        </p>
      </div>

      {/* Carousel */}
      <div className="relative mx-4 rounded-xl overflow-hidden" style={{ height: 168, backgroundColor: '#f9fafb' }}>
        {/* Cards */}
        <div className="relative w-full h-full flex items-end justify-center pb-4">
          {products.map((p, i) => {
            const offset = i - idx
            const absOff = Math.abs(offset)
            if (absOff > 1) return null
            return (
              <div
                key={i}
                className="absolute flex flex-col items-center justify-end transition-all duration-300"
                style={{
                  width: 80,
                  height: 110,
                  bottom: 16,
                  transform: `translateX(${offset * 72}px) scale(${offset === 0 ? 1 : 0.78})`,
                  zIndex: offset === 0 ? 10 : 4,
                  opacity: offset === 0 ? 1 : 0.45,
                }}
              >
                <div
                  className="w-full h-full rounded-xl flex items-center justify-center text-3xl shadow-sm"
                  style={{ backgroundColor: p.bg }}
                >
                  {p.emoji}
                </div>
              </div>
            )
          })}
        </div>

        {/* Nav buttons */}
        <button
          onClick={prev}
          className="absolute left-2 top-1/2 -translate-y-1/2 z-20 w-6 h-6 bg-white rounded-full shadow flex items-center justify-center text-gray-500 hover:text-gray-800 border transition-colors"
          style={{ borderColor: '#e8eaed' }}
        >
          <ChevronLeft size={11} />
        </button>
        <button
          onClick={next}
          className="absolute right-2 top-1/2 -translate-y-1/2 z-20 w-6 h-6 bg-white rounded-full shadow flex items-center justify-center text-gray-500 hover:text-gray-800 border transition-colors"
          style={{ borderColor: '#e8eaed' }}
        >
          <ChevronRight size={11} />
        </button>
      </div>

      {/* Product info */}
      <div className="px-4 py-3 text-center">
        <p className="text-sm font-semibold text-gray-900">{active.name}</p>
        <p className="text-xs text-gray-400 mt-0.5">{active.sold} sold</p>
        {/* Dots */}
        <div className="flex items-center justify-center gap-1.5 mt-2">
          {products.map((_, i) => (
            <button
              key={i}
              onClick={() => setIdx(i)}
              className="rounded-full transition-all duration-200"
              style={{
                width: idx === i ? 18 : 6,
                height: 6,
                backgroundColor: idx === i ? '#3b82f6' : '#d1d5db',
              }}
            />
          ))}
        </div>
      </div>

      {/* Top sellers list */}
      <div className="border-t px-4 py-3" style={{ borderColor: '#f3f4f6' }}>
        {products.map((p, i) => (
          <div key={i} className="flex items-center justify-between py-1.5">
            <div className="flex items-center gap-2">
              <div
                className="w-6 h-6 rounded-md flex items-center justify-center text-sm shrink-0"
                style={{ backgroundColor: p.bg }}
              >
                {p.emoji}
              </div>
              <span className="text-xs text-gray-700 truncate" style={{ maxWidth: 130 }}>
                {p.name}
              </span>
            </div>
            <span className="text-xs font-semibold text-gray-500">{p.sold}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
