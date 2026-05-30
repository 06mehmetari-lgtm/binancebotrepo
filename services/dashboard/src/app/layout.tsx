'use client'
import './globals.css'
import { usePathname } from 'next/navigation'

const NAV_LINKS = [
  { href: '/', label: 'Dashboard' },
  { href: '/markets', label: 'Markets' },
  { href: '/signals', label: 'Signals' },
  { href: '/agents', label: 'Agents' },
  { href: '/evolution', label: 'Evolution' },
  { href: '/shadow', label: 'Shadow' },
]

function NavLink({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <a
      href={href}
      className={`text-sm px-3 py-1.5 rounded transition-all duration-150 ${
        active
          ? 'text-orange-400 bg-orange-500/10 font-semibold border border-orange-500/30'
          : 'text-gray-400 hover:text-white hover:bg-gray-800/80'
      }`}
    >
      {label}
    </a>
  )
}

function Nav() {
  const pathname = usePathname()
  return (
    <nav className="border-b border-gray-800 bg-gray-950/95 backdrop-blur-sm sticky top-0 z-50">
      <div className="px-4 md:px-6 py-3 flex items-center gap-3">
        <a href="/" className="flex items-center gap-2 mr-3 shrink-0">
          <span className="text-orange-400 font-black text-base tracking-tight">⚡ PROMETHEUS</span>
        </a>
        <div className="flex gap-0.5 flex-wrap">
          {NAV_LINKS.map(link => (
            <NavLink key={link.href} href={link.href} label={link.label} active={pathname === link.href} />
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3 shrink-0">
          <span className="hidden sm:block text-xs text-gray-600 font-mono">USDM Futures</span>
          <span className="text-xs text-gray-700 font-mono">v2.0</span>
        </div>
      </div>
    </nav>
  )
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <title>Prometheus Trading System</title>
        <meta name="description" content="Autonomous crypto trading dashboard" />
      </head>
      <body className="min-h-screen bg-gray-950 text-gray-100 font-mono">
        <Nav />
        <main className="p-4 md:p-6">{children}</main>
      </body>
    </html>
  )
}
