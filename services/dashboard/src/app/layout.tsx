'use client'
import './globals.css'
import { usePathname } from 'next/navigation'
import { useState, useEffect, useRef, useCallback } from 'react'
import SmartAlerts from './components/SmartAlerts'
import AlertPanel from './components/AlertPanel'
import LlmHealthBanner from './components/LlmHealthBanner'
import { useStreamInvalidate } from '@/hooks/useStream'

const NAV_LINKS = [
  { href: '/', label: 'Dashboard' },
  { href: '/system', label: '🖥 Sistem' },
  { href: '/analiz', label: '🤖 AI Analiz' },
  { href: '/learning', label: '📈 AI Öğrenme' },
  { href: '/llm-keys', label: '🔑 LLM Keys' },
  { href: '/chat', label: '💬 Chat' },
  { href: '/positions', label: '💼 Positions' },
  { href: '/autopsy', label: '🔬 Otopsi' },
  { href: '/compare', label: '⚖ Compare' },
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

interface TickerEntry { price: number | null; direction: string; live: boolean; confidence?: number }
type TickerPayload = Record<string, TickerEntry | { total?: number; active?: number; top_nav?: string[]; deploy?: DeployInfo | null }>

interface DeployInfo {
  version?: string
  commit_short?: string
  deployed_at_iso?: string
  status?: string
  services_ok?: string[]
  services_failed?: string[]
  files_changed?: string[]
}

interface Notification { id: string; type: string; title: string; body: string; level: string; ts: number; symbol?: string }

const LEVEL_ICON: Record<string, string> = { success: '▲', warning: '⚠', critical: '🚨', info: '•' }
const LEVEL_COLOR: Record<string, string> = {
  success: 'text-green-400', warning: 'text-yellow-400', critical: 'text-red-400', info: 'text-gray-400',
}

function fmtTickerPrice(p: number | null, sym: string) {
  if (!p) return '—'
  if (sym === 'BTCUSDT') return p >= 10000 ? `$${Math.round(p / 1000)}K` : `$${p.toFixed(0)}`
  if (sym === 'ETHUSDT') return `$${Math.round(p)}`
  if (p >= 100) return `$${Math.round(p)}`
  if (p >= 1) return `$${p.toFixed(2)}`
  return `$${p.toFixed(4)}`
}

function TickerChip({ sym, entry }: { sym: string; entry: TickerEntry }) {
  const short = sym.replace('USDT', '')
  const arrowColor = entry.direction === 'long' ? 'text-green-400' : entry.direction === 'short' ? 'text-red-400' : 'text-gray-500'
  const arrow = entry.direction === 'long' ? '▲' : entry.direction === 'short' ? '▼' : '—'
  return (
    <a href={`/coin/${sym}`}
      className="flex items-center gap-1 px-2 py-1 rounded bg-gray-800/60 hover:bg-gray-700/60 transition-colors border border-gray-700/40 cursor-pointer">
      <span className="text-gray-400 text-xs font-semibold">{short}</span>
      <span className="text-white text-xs font-mono tabular-nums">{fmtTickerPrice(entry.price, sym)}</span>
      <span className={`text-xs leading-none ${arrowColor}`}>{arrow}</span>
      {!entry.live && <span className="text-gray-700 text-[10px]">○</span>}
    </a>
  )
}

function DeployVersionBadge({ deploy }: { deploy: DeployInfo | null | undefined }) {
  if (!deploy?.version) return null
  const ok = deploy.status === 'ok'
  const partial = deploy.status === 'partial'
  const color = ok
    ? 'text-green-400 border-green-700/50 bg-green-950/40'
    : partial
      ? 'text-yellow-400 border-yellow-700/50 bg-yellow-950/40'
      : 'text-gray-400 border-gray-700/50 bg-gray-900/40'
  const services = (deploy.services_ok ?? []).slice(0, 4).join(', ')
  const failed = (deploy.services_failed ?? []).length
  const title = [
    `v${deploy.version}`,
    deploy.commit_short ? `sha ${deploy.commit_short}` : '',
    deploy.deployed_at_iso ?? '',
    deploy.services_ok?.length ? `OK: ${deploy.services_ok.join(', ')}` : '',
    failed ? `HATA: ${(deploy.services_failed ?? []).join(', ')}` : '',
    deploy.files_changed?.length ? `${deploy.files_changed.length} dosya` : '',
  ].filter(Boolean).join(' | ')
  return (
    <span
      title={title}
      className={`hidden md:inline text-[10px] font-mono px-2 py-0.5 rounded border ${color} max-w-[200px] truncate`}
    >
      v{deploy.version}
      {services ? ` · ${services}` : ''}
      {failed > 0 ? ` · !${failed}` : ''}
    </span>
  )
}

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

function NotificationPanel({ notifications, onClose }: { notifications: Notification[]; onClose: () => void }) {
  return (
    <div className="absolute right-0 top-full mt-2 w-80 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl z-50 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <span className="text-white font-semibold text-sm">Recent Alerts</span>
        <button onClick={onClose} className="text-gray-600 hover:text-white text-sm">✕</button>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {notifications.length === 0 ? (
          <p className="text-gray-500 text-xs p-4 text-center">No recent alerts</p>
        ) : notifications.map(n => (
          <div key={n.id}
            className="px-4 py-3 border-b border-gray-800/50 hover:bg-gray-800/40 transition-colors cursor-pointer"
            onClick={() => { if (n.symbol) { window.location.href = `/coin/${n.symbol}`; onClose() } }}>
            <div className="flex items-start gap-2">
              <span className={`text-sm leading-none mt-0.5 ${LEVEL_COLOR[n.level] ?? 'text-gray-400'}`}>
                {LEVEL_ICON[n.level] ?? '•'}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-white text-xs font-semibold truncate">{n.title}</p>
                <p className="text-gray-500 text-[11px] mt-0.5 leading-snug">{n.body}</p>
                <p className="text-gray-700 text-[10px] mt-1">
                  {new Date(n.ts * 1000).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="px-4 py-2 border-t border-gray-800 text-center">
        <a href="/memory" className="text-xs text-orange-400 hover:text-orange-300 transition-colors">
          View all activity →
        </a>
      </div>
    </div>
  )
}

function Nav() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const [ticker, setTicker] = useState<TickerPayload>({})
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [notifOpen, setNotifOpen] = useState(false)
  const [lastSeenTs, setLastSeenTs] = useState(0)
  const notifRef = useRef<HTMLDivElement>(null)

  const fetchTicker = useCallback(async () => {
    try {
      const data = await fetch('/api/ticker').then(r => r.json())
      setTicker(data ?? {})
    } catch { /* ignore */ }
  }, [])

  const fetchNotifications = useCallback(async () => {
    try {
      const data: Notification[] = await fetch('/api/notifications').then(r => r.json())
      if (Array.isArray(data)) setNotifications(data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    // Load lastSeenTs from localStorage
    const saved = localStorage.getItem('notif_last_seen')
    if (saved) setLastSeenTs(Number(saved))

    fetchTicker()
    fetchNotifications()
    const t1 = setInterval(fetchTicker, 30000)
    const t2 = setInterval(fetchNotifications, 60000)
    return () => { clearInterval(t1); clearInterval(t2) }
  }, [fetchTicker, fetchNotifications])

  useStreamInvalidate({
    hints: ['signal', 'agents'],
    debounceMs: 800,
    onEvent: () => {
      fetchTicker()
      fetchNotifications()
    },
  })

  // Close notification panel on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false)
      }
    }
    if (notifOpen) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [notifOpen])

  const unreadCount = notifications.filter(n => n.ts > lastSeenTs).length

  const handleNotifToggle = () => {
    if (!notifOpen) {
      // Mark all as seen
      const latest = notifications[0]?.ts ?? Date.now() / 1000
      setLastSeenTs(latest)
      localStorage.setItem('notif_last_seen', String(latest))
    }
    setNotifOpen(v => !v)
  }

  const meta = ticker._meta as { total?: number; active?: number; top_nav?: string[]; deploy?: DeployInfo | null } | undefined
  const isEntry = (e: unknown): e is TickerEntry =>
    !!e && typeof e === 'object' && 'live' in e
  const tickerSyms = meta?.top_nav?.length
    ? meta.top_nav
    : Object.entries(ticker)
        .filter((entry): entry is [string, TickerEntry] => {
          const [k, e] = entry
          return k !== '_meta' && isEntry(e) && e.live
        })
        .sort((a, b) => (b[1].confidence ?? 0) - (a[1].confidence ?? 0))
        .slice(0, 12)
        .map(([k]) => k)

  return (
    <>
      <nav className="border-b border-gray-800 bg-gray-950/95 backdrop-blur-sm sticky top-0 z-50">
        <div className="px-4 md:px-6 py-3 flex items-center gap-2">
          <a href="/" className="flex items-center gap-2 mr-2 shrink-0">
            <span className="text-orange-400 font-black text-base tracking-tight">⚡ PROMETHEUS</span>
            <DeployVersionBadge deploy={meta?.deploy} />
          </a>

          {/* Desktop nav */}
          <div className="hidden lg:flex gap-0.5 overflow-x-auto scrollbar-hide">
            {NAV_LINKS.map(link => (
              <NavLink key={link.href} href={link.href} label={link.label} active={
                link.href === '/' ? pathname === '/' : pathname.startsWith(link.href)
              } />
            ))}
          </div>

          <div className="ml-auto flex items-center gap-2 shrink-0">
            {meta?.total != null && (
              <span className="hidden lg:inline text-[10px] text-gray-600 font-mono border border-gray-800 px-1.5 py-0.5 rounded">
                {meta.active ?? 0}/{meta.total} coin
              </span>
            )}
            <div className="hidden md:flex items-center gap-1 max-w-[420px] overflow-x-auto scrollbar-hide">
              {tickerSyms.map(sym => {
                const raw = ticker[sym]
                if (!isEntry(raw)) return null
                return <TickerChip key={sym} sym={sym} entry={raw} />
              })}
            </div>

            {/* Notification bell */}
            <div ref={notifRef} className="relative">
              <button
                onClick={handleNotifToggle}
                className="relative p-2 rounded hover:bg-gray-800 transition-colors text-gray-400 hover:text-white"
                aria-label="Notifications"
              >
                <span className="text-base leading-none">🔔</span>
                {unreadCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center leading-none">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                )}
              </button>
              {notifOpen && (
                <NotificationPanel notifications={notifications} onClose={() => setNotifOpen(false)} />
              )}
            </div>

            <span className="hidden md:block text-xs text-gray-600 font-mono">USDM</span>
            <span className="hidden sm:inline-flex items-center text-xs font-bold px-2 py-0.5 rounded bg-yellow-900/40 text-yellow-400 border border-yellow-700/50">PAPER</span>

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
            {/* Mobile ticker */}
            <div className="px-4 py-3 border-b border-gray-800/60 flex gap-2 overflow-x-auto">
              {tickerSyms.map(sym => {
                const raw = ticker[sym]
                if (!isEntry(raw)) return null
                return <TickerChip key={sym} sym={sym} entry={raw} />
              })}
            </div>
            <div className="p-4 flex flex-col gap-1">
              {NAV_LINKS.map(link => (
                <NavLink
                  key={link.href}
                  href={link.href}
                  label={link.label}
                  active={link.href === '/' ? pathname === '/' : pathname.startsWith(link.href)}
                  onClick={() => setOpen(false)}
                />
              ))}
            </div>
            <div className="absolute bottom-6 left-4 right-4 text-xs text-gray-700 space-y-1 border-t border-gray-800/60 pt-4">
              <p>USDM Perpetual Futures · v2.1</p>
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
        <LlmHealthBanner />
        <main className="p-3 md:p-4 lg:p-6">{children}</main>
        <SmartAlerts />
        <AlertPanel />
      </body>
    </html>
  )
}
