import { Package } from 'lucide-react'

const products = [
  { name: 'Crop top pants', category: 'Clothing', stock: 82, price: '$599', sold: 134 },
  { name: 'T-shirt Rainblow White', category: 'Clothing', stock: 54, price: '$49', sold: 271 },
  { name: 'Huzzle black cap', category: 'Accessories', stock: 30, price: '$109', sold: 147 },
  { name: 'Classic Sneakers', category: 'Footwear', stock: 18, price: '$199', sold: 89 },
  { name: 'Oversized Hoodie', category: 'Clothing', stock: 67, price: '$89', sold: 201 },
]

export default function ProductsPage() {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
        <Package size={16} className="text-blue-500" />
        <h2 className="text-sm font-semibold text-gray-900">Products</h2>
        <span className="ml-auto text-xs text-gray-400">{products.length} total</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left px-5 py-3 text-gray-400 font-medium">Name</th>
            <th className="text-left px-4 py-3 text-gray-400 font-medium">Category</th>
            <th className="text-left px-4 py-3 text-gray-400 font-medium">Stock</th>
            <th className="text-left px-4 py-3 text-gray-400 font-medium">Price</th>
            <th className="text-left px-5 py-3 text-gray-400 font-medium">Sold</th>
          </tr>
        </thead>
        <tbody>
          {products.map((p, idx) => (
            <tr key={idx} className="border-b border-gray-50 hover:bg-gray-50 transition-colors cursor-pointer">
              <td className="px-5 py-3 text-gray-800 font-medium">{p.name}</td>
              <td className="px-4 py-3 text-gray-500">{p.category}</td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min((p.stock / 100) * 100, 100)}%`,
                        backgroundColor: p.stock < 30 ? '#ef4444' : '#10b981',
                      }}
                    />
                  </div>
                  <span className="text-gray-600">{p.stock}</span>
                </div>
              </td>
              <td className="px-4 py-3 text-gray-800 font-semibold">{p.price}</td>
              <td className="px-5 py-3 text-gray-600">{p.sold}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
