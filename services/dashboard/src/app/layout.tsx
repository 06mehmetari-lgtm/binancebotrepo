import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Prometheus Trading System',
  description: 'Autonomous crypto trading dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-950 text-gray-100 font-mono">
        <nav className="border-b border-gray-800 px-6 py-3 flex items-center gap-6">
          <span className="text-orange-400 font-bold text-lg">⚡ PROMETHEUS</span>
          <span className="text-gray-400 text-sm">Autonomous Trading System</span>
          <div className="ml-auto flex gap-4 text-sm text-gray-400">
            <a href="/" className="hover:text-white">Dashboard</a>
            <a href="/signals" className="hover:text-white">Signals</a>
            <a href="/shadow" className="hover:text-white">Shadow</a>
            <a href="/agents" className="hover:text-white">Agents</a>
          </div>
        </nav>
        <main className="p-6">{children}</main>
      </body>
    </html>
  )
}
