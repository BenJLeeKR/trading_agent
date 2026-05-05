'use client'

import { Package } from 'lucide-react'

const products = [
  { name: 'Crop top pants', category: 'Clothing', stock: 82, price: '$599', sold: 134, platform: 'Shopee' },
  { name: 'T-shirt Rainblow White', category: 'Clothing', stock: 54, price: '$49', sold: 271, platform: 'Tokopedia' },
  { name: 'Huzzle black cap', category: 'Accessories', stock: 22, price: '$109', sold: 147, platform: 'Tokopedia' },
  { name: 'Classic Sneakers', category: 'Footwear', stock: 18, price: '$199', sold: 89, platform: 'Shopee' },
  { name: 'Oversized Hoodie', category: 'Clothing', stock: 67, price: '$89', sold: 201, platform: 'Tiktok' },
  { name: 'Slim Fit Jeans', category: 'Clothing', stock: 44, price: '$129', sold: 163, platform: 'Shopee' },
]

export default function ProductsPage() {
  return (
    <div className="bg-white rounded-xl border shadow-sm overflow-hidden" style={{ borderColor: '#e8eaed' }}>
      <div
        className="flex items-center gap-2 px-5 py-3.5 border-b"
        style={{ borderColor: '#e8eaed' }}
      >
        <Package size={15} className="text-blue-500" />
        <h2 className="text-sm font-semibold text-gray-900">Products</h2>
        <span className="ml-auto text-xs text-gray-400">{products.length} total</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
              {['Name', 'Category', 'Platform', 'Stock', 'Price', 'Sold'].map((h) => (
                <th key={h} className="text-left px-5 py-2.5 text-xs font-medium text-gray-400">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {products.map((p, i) => (
              <tr
                key={i}
                className="cursor-pointer transition-colors"
                style={{ borderBottom: '1px solid #f9fafb' }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLElement).style.backgroundColor = '#f9fafb')
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLElement).style.backgroundColor = '')
                }
              >
                <td className="px-5 py-3 text-xs text-gray-800 font-medium">{p.name}</td>
                <td className="px-5 py-3 text-xs text-gray-500">{p.category}</td>
                <td className="px-5 py-3 text-xs text-gray-500">{p.platform}</td>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-14 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${Math.min((p.stock / 100) * 100, 100)}%`,
                          backgroundColor: p.stock < 30 ? '#ef4444' : '#10b981',
                        }}
                      />
                    </div>
                    <span className="text-xs text-gray-600">{p.stock}</span>
                  </div>
                </td>
                <td className="px-5 py-3 text-xs text-gray-900 font-semibold">{p.price}</td>
                <td className="px-5 py-3 text-xs text-gray-600">{p.sold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
