import type { Metadata } from 'next'
import '../src/index.css'

export const metadata: Metadata = {
  title: 'AITrading Co. — System Operations Center',
  description: 'Internal read-only operator console for AI multi-agent trading system monitoring.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="bg-background">
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  )
}
