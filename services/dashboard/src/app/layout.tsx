'use client'
import './globals.css'
import { usePathname } from 'next/navigation'
import { useState } from 'react'

const NAV_LINKS = [
  { href: '/', label: 'Dashboard' },
  { href: '/scanner', label: '🔍 Scanner' },
  { href: '/markets', label: 'Markets' },
  { href: '/signals', label: 'Signals' },
  { href: '/agents', label: 'Agents' },
  { href: '/evolution', label: 'Evolution' },
  { href: '/shadow', label: 'Shadow' },
  { href: '/risk', label: 'Risk' },
  { href: '/memory', label: 'AI Memory' },
  { href: '/backtest', label: '📈 Backtest' },
]

function NavLink({ href, label, active, onClick }: {
  href: string; label: string; active: boolean; onClick?: () => void
}) {
  return (
    <a href={href} onClick={onClick}
      className={`text-sm px-3 py-1.5 rounded transition-all duration-150 whitespace-nowrap ${
        active
          ? 'text-orange-400 bg-orange-500/10 font-semibold border border-orange-500/30'
          : 'text-gray-400 hover:text-white hover:bg-gray-800/80'
      }`}>
      {label}
    </a>
  )
}

function Nav() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)

  return (
    <>
      <nav className="border-b border-gray-800 bg-gray-950/95 backdrop-blur-sm sticky top-0 z-50">
        <div className="px-4 md:px-6 py-3 flex items-center gap-2">
          <a href="/" className="flex items-center gap-2 mr-2 shrink-0">
            <span className="text-orange-400 font-black text-base tracking-tight">⚡ PROMETHEUS</span>
          </a>

          {/* Desktop nav */}
          <div className="hidden lg:flex gap-0.5 overflow-x-auto scrollbar-hide">
            {NAV_LINKS.map(link => (
              <NavLink key={link.href} href={link.href} label={link.label} active={pathname === link.href} />
            ))}
          </div>

          <div className="ml-auto flex items-center gap-2 shrink-0">
            <span className="hidden md:block text-xs text-gray-600 font-mono">USDM Futures</span>
            <span className="hidden sm:inline-flex items-center text-xs font-bold px-2 py-0.5 rounded bg-yellow-900/40 text-yellow-400 border border-yellow-700/50">PAPER</span>
            <span className="hidden lg:block text-xs text-gray-700 font-mono">v2.0</span>

            {/* Hamburger — mobile/tablet */}
            <button
              onClick={() => setOpen(o => !o)}
              className="lg:hidden p-2 rounded hover:bg-gray-800 transition-colors"
              aria-label="Navigation menu"
            >
              <div className="w-5 space-y-1.5">
                <span className={`block h-0.5 bg-gray-400 transition-all duration-200 origin-center ${open ? 'rotate-45 translate-y-2' : ''}`} />
                <span className={`block h-0.5 bg-gray-400 transition-all duration-200 ${open ? 'opacity-0 scale-x-0' : ''}`} />
                <span className={`block h-0.5 bg-gray-400 transition-all duration-200 origin-center ${open ? '-rotate-45 -translate-y-2' : ''}`} />
              </div>
            </button>
          </div>
        </div>
      </nav>

      {/* Mobile drawer overlay */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-40" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
          <div
            className="absolute top-0 right-0 h-full w-72 max-w-[85vw] bg-gray-950 border-l border-gray-800 shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="p-5 border-b border-gray-800 flex items-center justify-between">
              <span className="text-orange-400 font-black tracking-tight">⚡ PROMETHEUS</span>
              <button onClick={() => setOpen(false)} className="text-gray-600 hover:text-white text-xl leading-none">✕</button>
            </div>
            <div className="p-4 flex flex-col gap-1">
              {NAV_LINKS.map(link => (
                <NavLink
                  key={link.href}
                  href={link.href}
                  label={link.label}
                  active={pathname === link.href}
                  onClick={() => setOpen(false)}
                />
              ))}
            </div>
            <div className="absolute bottom-6 left-4 right-4 text-xs text-gray-700 space-y-1 border-t border-gray-800/60 pt-4">
              <p>USDM Perpetual Futures · v2.0</p>
              <span className="inline-flex items-center font-bold px-2 py-0.5 rounded bg-yellow-900/40 text-yellow-400 border border-yellow-700/50">PAPER MODE</span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <title>Prometheus Trading System</title>
        <meta name="description" content="Autonomous crypto trading dashboard" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body className="min-h-screen bg-gray-950 text-gray-100 font-mono">
        <Nav />
        <main className="p-3 md:p-4 lg:p-6">{children}</main>
      </body>
    </html>
  )
}
