import { ShoppingCart } from 'lucide-react'

const orders = [
  { id: 'ORD-1024', customer: 'Alice Johnson', date: '05/05/2026', amount: '$240.00', status: 'Completed' },
  { id: 'ORD-1025', customer: 'Bob Smith', date: '05/04/2026', amount: '$89.99', status: 'Processing' },
  { id: 'ORD-1026', customer: 'Carol White', date: '05/04/2026', amount: '$430.50', status: 'Completed' },
  { id: 'ORD-1027', customer: 'David Lee', date: '05/03/2026', amount: '$15.00', status: 'Canceled' },
  { id: 'ORD-1028', customer: 'Eva Green', date: '05/03/2026', amount: '$199.00', status: 'Processing' },
  { id: 'ORD-1029', customer: 'Frank Kim', date: '05/02/2026', amount: '$59.99', status: 'Completed' },
]

const statusStyle: Record<string, { bg: string; text: string }> = {
  Completed: { bg: '#ecfdf5', text: '#10b981' },
  Processing: { bg: '#eff6ff', text: '#3b82f6' },
  Canceled: { bg: '#fef2f2', text: '#ef4444' },
}

export default function OrdersPage() {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
        <ShoppingCart size={16} className="text-blue-500" />
        <h2 className="text-sm font-semibold text-gray-900">Orders</h2>
        <span className="ml-auto flex items-center justify-center px-2.5 py-0.5 rounded-full bg-red-500 text-white text-xs font-semibold">
          10
        </span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left px-5 py-3 text-gray-400 font-medium">Order ID</th>
            <th className="text-left px-4 py-3 text-gray-400 font-medium">Customer</th>
            <th className="text-left px-4 py-3 text-gray-400 font-medium">Date</th>
            <th className="text-left px-4 py-3 text-gray-400 font-medium">Amount</th>
            <th className="text-left px-5 py-3 text-gray-400 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o, idx) => {
            const s = statusStyle[o.status]
            return (
              <tr key={idx} className="border-b border-gray-50 hover:bg-gray-50 transition-colors cursor-pointer">
                <td className="px-5 py-3 text-gray-500">{o.id}</td>
                <td className="px-4 py-3 text-gray-800 font-medium">{o.customer}</td>
                <td className="px-4 py-3 text-gray-500">{o.date}</td>
                <td className="px-4 py-3 text-gray-800 font-semibold">{o.amount}</td>
                <td className="px-5 py-3">
                  <span
                    className="px-2 py-1 rounded-full text-xs font-medium"
                    style={{ backgroundColor: s.bg, color: s.text }}
                  >
                    {o.status}
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
