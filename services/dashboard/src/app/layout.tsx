'use client'
import './globals.css'
import { usePathname } from 'next/navigation'
import { useState, useEffect, useRef, useCallback } from 'react'
import SmartAlerts from './components/SmartAlerts'

// ── Navigation structure ────────────────────────────────────────────────────
const NAV_GROUPS = [
  {
    title: 'TİCARET',
    links: [
      { href: '/',          label: 'Dashboard',    icon: '🏠' },
      { href: '/positions', label: 'Pozisyonlar',  icon: '💼' },
      { href: '/scanner',   label: 'Tarayıcı',     icon: '🔍' },
      { href: '/markets',   label: 'Piyasalar',    icon: '📊' },
      { href: '/signals',   label: 'Sinyaller',    icon: '⚡' },
    ],
  },
  {
    title: 'YAPAY ZEKA',
    links: [
      { href: '/ai',       label: 'AI Analiz',    icon: '🤖' },
      { href: '/agents',   label: 'Ajan Ekibi',   icon: '🤝' },
      { href: '/learning', label: 'AI Öğrenme',   icon: '📈' },
      { href: '/memory',   label: 'AI Hafıza',    icon: '🧠' },
    ],
  },
  {
    title: 'EĞİTİM',
    links: [
      { href: '/training',  label: 'AI Eğitim',    icon: '📚' },
      { href: '/chat',      label: 'Doküman Chat', icon: '💬' },
      { href: '/backtest',  label: 'Backtest',     icon: '📉' },
      { href: '/evolution', label: 'Evrim',        icon: '🧬' },
    ],
  },
  {
    title: 'SİSTEM',
    links: [
      { href: '/system', label: 'Sistem',   icon: '🖥' },
      { href: '/shadow', label: 'Shadow',   icon: '👥' },
      { href: '/risk',   label: 'Risk',     icon: '⚠️' },
    ],
  },
]

// Flat list for mobile / breadcrumb lookups
const ALL_LINKS = NAV_GROUPS.flatMap(g => g.links)

// ── Types ───────────────────────────────────────────────────────────────────
interface TickerEntry  { price: number | null; direction: string; live: boolean }
type    TickerData     = Record<string, TickerEntry>
interface Notification { id: string; type: string; title: string; body: string; level: string; ts: number; symbol?: string }
interface SystemState  {
  open_positions: number
  daily_pnl: number
  daily_pnl_pct: number
  active_signals: number
  regime: string
  system_halted: boolean
  immunity_daily_loss: number
  win_rate_today: number
  trades_today: number
}

// ── Helpers ─────────────────────────────────────────────────────────────────
const LEVEL_ICON:  Record<string, string> = { success: '▲', warning: '⚠', critical: '🚨', info: '•' }
const LEVEL_COLOR: Record<string, string> = {
  success: 'text-green-400', warning: 'text-yellow-400', critical: 'text-red-400', info: 'text-gray-400',
}

function fmtPrice(p: number | null, sym: string) {
  if (!p) return '—'
  if (sym === 'BTCUSDT') return p >= 10000 ? `$${Math.round(p / 1000)}K` : `$${p.toFixed(0)}`
  if (sym === 'ETHUSDT') return `$${Math.round(p)}`
  if (p >= 100) return `$${Math.round(p)}`
  if (p >= 1)   return `$${p.toFixed(2)}`
  return `$${p.toFixed(4)}`
}

function fmtPnl(v: number) {
  const sign = v >= 0 ? '+' : ''
  return `${sign}$${Math.abs(v).toFixed(2)}`
}

// ── Sub-components ──────────────────────────────────────────────────────────
function NotificationPanel({ notifications, onClose }: { notifications: Notification[]; onClose: () => void }) {
  return (
    <div className="absolute left-full ml-2 top-0 w-80 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl z-50 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <span className="text-white font-semibold text-sm">Son Uyarılar</span>
        <button onClick={onClose} className="text-gray-600 hover:text-white text-sm">✕</button>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {notifications.length === 0 ? (
          <p className="text-gray-500 text-xs p-4 text-center">Uyarı yok</p>
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
          Tüm aktivite →
        </a>
      </div>
    </div>
  )
}

// ── Global Decision Bar (top of every page) ─────────────────────────────────
function DecisionBar({ state, ticker }: { state: SystemState | null; ticker: TickerData }) {
  if (!state) return null
  const halted = state.system_halted
  const pnlColor = state.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'
  const regimeColor: Record<string, string> = {
    trending_up: 'text-green-400', trending_down: 'text-red-400',
    ranging: 'text-yellow-400', volatile: 'text-orange-400',
  }
  const regime = state.regime ?? 'unknown'
  const winPct = Math.round((state.win_rate_today ?? 0) * 100)

  return (
    <div className={`flex items-center gap-3 px-4 py-1.5 text-[11px] font-mono border-b ${
      halted ? 'bg-red-950/60 border-red-800' : 'bg-gray-900/80 border-gray-800'
    } overflow-x-auto scrollbar-hide`}>
      {halted && (
        <span className="flex items-center gap-1 text-red-400 font-bold shrink-0 animate-pulse">
          🚨 SİSTEM DURDU
        </span>
      )}
      <span className="text-gray-600 shrink-0">|</span>
      <span className="text-gray-400 shrink-0">Pozisyon:</span>
      <span className="text-white font-bold shrink-0">{state.open_positions}/5</span>
      <span className="text-gray-600 shrink-0">|</span>
      <span className="text-gray-400 shrink-0">Bugün:</span>
      <span className={`font-bold shrink-0 ${pnlColor}`}>{fmtPnl(state.daily_pnl)}</span>
      <span className="text-gray-600 shrink-0">|</span>
      <span className="text-gray-400 shrink-0">Win:</span>
      <span className={`font-bold shrink-0 ${winPct >= 50 ? 'text-green-400' : winPct >= 37 ? 'text-yellow-400' : 'text-red-400'}`}>
        %{winPct} ({state.trades_today}tk)
      </span>
      <span className="text-gray-600 shrink-0">|</span>
      <span className="text-gray-400 shrink-0">Rejim:</span>
      <span className={`font-bold shrink-0 ${regimeColor[regime] ?? 'text-gray-400'}`}>
        {regime}
      </span>
      <span className="text-gray-600 shrink-0">|</span>
      <span className="text-gray-400 shrink-0">Aktif sinyal:</span>
      <span className="text-orange-400 font-bold shrink-0">{state.active_signals}</span>
      {/* BTC/ETH fiyat */}
      {['BTCUSDT', 'ETHUSDT'].map(sym => {
        const e = ticker[sym]
        if (!e) return null
        const c = e.direction === 'long' ? 'text-green-400' : e.direction === 'short' ? 'text-red-400' : 'text-gray-400'
        const a = e.direction === 'long' ? '▲' : e.direction === 'short' ? '▼' : '—'
        return (
          <span key={sym} className="shrink-0 flex items-center gap-0.5">
            <span className="text-gray-600">|</span>
            <span className="text-gray-500 ml-1">{sym.replace('USDT', '')}:</span>
            <span className="text-white ml-0.5">{fmtPrice(e.price, sym)}</span>
            <span className={c}>{a}</span>
          </span>
        )
      })}
    </div>
  )
}

// ── Sidebar ─────────────────────────────────────────────────────────────────
function Sidebar({
  pathname, notifications, unreadCount,
  onNotifToggle, notifOpen, notifRef,
  ticker, sysState, mobileOpen, onMobileClose,
}: {
  pathname: string
  notifications: Notification[]
  unreadCount: number
  onNotifToggle: () => void
  notifOpen: boolean
  notifRef: React.RefObject<HTMLDivElement | null>
  ticker: TickerData
  sysState: SystemState | null
  mobileOpen: boolean
  onMobileClose: () => void
}) {
  const isActive = (href: string) => href === '/' ? pathname === '/' : pathname.startsWith(href)

  const SidebarContent = () => (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800 shrink-0">
        <a href="/" className="flex items-center gap-2" onClick={onMobileClose}>
          <span className="text-orange-400 font-black text-base tracking-tight">⚡ PROMETHEUS</span>
        </a>
        <div className="flex items-center gap-2 mt-2">
          <span className="text-[10px] text-gray-600 font-mono">USDM</span>
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-yellow-900/40 text-yellow-400 border border-yellow-700/50">
            PAPER
          </span>
        </div>
      </div>

      {/* Live mini status */}
      {sysState && (
        <div className="px-4 py-3 border-b border-gray-800/60 shrink-0 space-y-1.5">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-gray-500">Pozisyon</span>
            <span className={`font-bold ${sysState.open_positions > 0 ? 'text-blue-400' : 'text-gray-500'}`}>
              {sysState.open_positions}/5
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-gray-500">Bugünkü K/Z</span>
            <span className={`font-bold ${sysState.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {fmtPnl(sysState.daily_pnl)}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-gray-500">Win Rate</span>
            <span className={`font-bold ${
              (sysState.win_rate_today ?? 0) >= 0.50 ? 'text-green-400' :
              (sysState.win_rate_today ?? 0) >= 0.37 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              %{Math.round((sysState.win_rate_today ?? 0) * 100)}
            </span>
          </div>
          {sysState.system_halted && (
            <div className="text-[10px] text-red-400 font-bold animate-pulse">🚨 SİSTEM DURDU</div>
          )}
        </div>
      )}

      {/* Navigation groups */}
      <nav className="flex-1 overflow-y-auto py-3 scrollbar-hide">
        {NAV_GROUPS.map(group => (
          <div key={group.title} className="mb-3">
            <p className="px-4 py-1 text-[10px] text-gray-600 font-bold tracking-widest uppercase">
              {group.title}
            </p>
            {group.links.map(link => {
              const active = isActive(link.href)
              return (
                <a
                  key={link.href}
                  href={link.href}
                  onClick={onMobileClose}
                  className={`flex items-center gap-2.5 px-4 py-2 text-sm transition-all duration-150 ${
                    active
                      ? 'text-orange-400 bg-orange-500/10 border-r-2 border-orange-500 font-semibold'
                      : 'text-gray-400 hover:text-white hover:bg-gray-800/60'
                  }`}
                >
                  <span className="text-base leading-none w-5 text-center shrink-0">{link.icon}</span>
                  <span>{link.label}</span>
                </a>
              )
            })}
          </div>
        ))}
      </nav>

      {/* Bottom: ticker + notifications */}
      <div className="px-4 py-3 border-t border-gray-800 shrink-0 space-y-2">
        {/* BTC/ETH */}
        <div className="flex items-center gap-2 flex-wrap">
          {['BTCUSDT', 'ETHUSDT'].map(sym => {
            const e = ticker[sym]
            if (!e) return null
            const c = e.direction === 'long' ? 'text-green-400' : e.direction === 'short' ? 'text-red-400' : 'text-gray-500'
            const a = e.direction === 'long' ? '▲' : e.direction === 'short' ? '▼' : '—'
            return (
              <a key={sym} href={`/coin/${sym}`}
                className="flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-gray-800/60 hover:bg-gray-700/60 border border-gray-700/40">
                <span className="text-gray-400">{sym.replace('USDT', '')}</span>
                <span className="text-white font-mono">{fmtPrice(e.price, sym)}</span>
                <span className={c}>{a}</span>
              </a>
            )
          })}
        </div>

        {/* Notification bell */}
        <div ref={notifRef} className="relative">
          <button
            onClick={onNotifToggle}
            className="flex items-center gap-2 w-full px-3 py-2 rounded text-sm text-gray-400 hover:text-white hover:bg-gray-800/60 transition-colors"
          >
            <span className="relative">
              🔔
              {unreadCount > 0 && (
                <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center leading-none">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </span>
            <span className="text-[12px]">Uyarılar</span>
            {unreadCount > 0 && (
              <span className="ml-auto bg-red-500/20 text-red-400 text-[10px] px-1.5 py-0.5 rounded-full">{unreadCount}</span>
            )}
          </button>
          {notifOpen && (
            <NotificationPanel notifications={notifications} onClose={() => {}} />
          )}
        </div>
      </div>
    </div>
  )

  return (
    <>
      {/* ── Desktop sidebar ────────────────────────────────────── */}
      <aside className="hidden lg:flex flex-col fixed left-0 top-0 h-screen w-56 bg-gray-950 border-r border-gray-800 z-40">
        <SidebarContent />
      </aside>

      {/* ── Mobile overlay ─────────────────────────────────────── */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50" onClick={onMobileClose}>
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
          <aside
            className="absolute top-0 left-0 h-full w-64 max-w-[85vw] bg-gray-950 border-r border-gray-800 shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <SidebarContent />
          </aside>
        </div>
      )}
    </>
  )
}

// ── Top bar (mobile only) ────────────────────────────────────────────────────
function MobileTopBar({
  onMenuOpen, pathname,
}: {
  onMenuOpen: () => void
  pathname: string
}) {
  const current = ALL_LINKS.find(l => l.href === '/' ? pathname === '/' : pathname.startsWith(l.href))
  return (
    <header className="lg:hidden sticky top-0 z-40 flex items-center gap-3 px-4 py-3 bg-gray-950/95 backdrop-blur-sm border-b border-gray-800">
      <button
        onClick={onMenuOpen}
        className="p-1.5 rounded hover:bg-gray-800 transition-colors"
        aria-label="Menü"
      >
        <div className="w-5 space-y-1.5">
          <span className="block h-0.5 bg-gray-400" />
          <span className="block h-0.5 bg-gray-400" />
          <span className="block h-0.5 bg-gray-400" />
        </div>
      </button>
      <span className="text-orange-400 font-black text-sm tracking-tight">⚡ PROMETHEUS</span>
      {current && (
        <span className="text-gray-500 text-sm">{current.icon} {current.label}</span>
      )}
      <span className="ml-auto text-[10px] font-bold px-1.5 py-0.5 rounded bg-yellow-900/40 text-yellow-400 border border-yellow-700/50">
        PAPER
      </span>
    </header>
  )
}

// ── Root Nav (orchestrates everything) ──────────────────────────────────────
function RootNav() {
  const pathname = usePathname()
  const [mobileOpen,   setMobileOpen]   = useState(false)
  const [ticker,       setTicker]       = useState<TickerData>({})
  const [notifications, setNotifs]      = useState<Notification[]>([])
  const [notifOpen,    setNotifOpen]    = useState(false)
  const [lastSeenTs,   setLastSeenTs]   = useState(0)
  const [sysState,     setSysState]     = useState<SystemState | null>(null)
  const notifRef = useRef<HTMLDivElement>(null)

  const fetchTicker = useCallback(async () => {
    try { setTicker(await fetch('/api/ticker').then(r => r.json()) ?? {}) } catch { /* */ }
  }, [])

  const fetchNotifications = useCallback(async () => {
    try {
      const d = await fetch('/api/notifications').then(r => r.json())
      if (Array.isArray(d)) setNotifs(d)
    } catch { /* */ }
  }, [])

  const fetchSystemState = useCallback(async () => {
    try {
      // Combine positions + immunity status into a single system state
      const [posData, immunityRaw, signalData] = await Promise.allSettled([
        fetch('/api/positions').then(r => r.json()),
        fetch('/api/risk').then(r => r.json()),
        fetch('/api/signals').then(r => r.json()),
      ])

      const pos      = posData.status      === 'fulfilled' ? posData.value      : {}
      const immunity = immunityRaw.status  === 'fulfilled' ? immunityRaw.value  : {}
      const signals  = signalData.status   === 'fulfilled' ? signalData.value   : {}

      const openPositions = Array.isArray(pos.positions) ? pos.positions.length : 0
      const dailyPnl      = typeof pos.daily_pnl === 'number' ? pos.daily_pnl : 0
      const activeSigs    = Array.isArray(signals.signals) ? signals.signals.filter((s: {is_valid?: boolean}) => s.is_valid).length : 0
      const tradeHistory  = Array.isArray(pos.history) ? pos.history : []
      const todayWins     = tradeHistory.filter((t: {pnl_pct?: number}) => (t.pnl_pct ?? 0) > 0).length
      const todayTrades   = tradeHistory.length

      setSysState({
        open_positions:      openPositions,
        daily_pnl:           dailyPnl,
        daily_pnl_pct:       dailyPnl / 10000,
        active_signals:      activeSigs,
        regime:              immunity.regime ?? signals.regime ?? 'unknown',
        system_halted:       immunity.system_halted ?? false,
        immunity_daily_loss: immunity.daily_loss_pct ?? 0,
        win_rate_today:      todayTrades > 0 ? todayWins / todayTrades : 0,
        trades_today:        todayTrades,
      })
    } catch { /* */ }
  }, [])

  useEffect(() => {
    const saved = localStorage.getItem('notif_last_seen')
    if (saved) setLastSeenTs(Number(saved))

    fetchTicker(); fetchNotifications(); fetchSystemState()
    const t1 = setInterval(fetchTicker,        10000)
    const t2 = setInterval(fetchNotifications, 15000)
    const t3 = setInterval(fetchSystemState,   8000)
    return () => { clearInterval(t1); clearInterval(t2); clearInterval(t3) }
  }, [fetchTicker, fetchNotifications, fetchSystemState])

  // Close notif on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false)
    }
    if (notifOpen) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [notifOpen])

  const unreadCount = notifications.filter(n => n.ts > lastSeenTs).length

  const handleNotifToggle = () => {
    if (!notifOpen) {
      const latest = notifications[0]?.ts ?? Date.now() / 1000
      setLastSeenTs(latest)
      localStorage.setItem('notif_last_seen', String(latest))
    }
    setNotifOpen(v => !v)
  }

  return (
    <>
      <Sidebar
        pathname={pathname}
        notifications={notifications}
        unreadCount={unreadCount}
        onNotifToggle={handleNotifToggle}
        notifOpen={notifOpen}
        notifRef={notifRef}
        ticker={ticker}
        sysState={sysState}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
      />
      <MobileTopBar onMenuOpen={() => setMobileOpen(true)} pathname={pathname} />
      <DecisionBar state={sysState} ticker={ticker} />
    </>
  )
}

// ── Root Layout ──────────────────────────────────────────────────────────────
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <head>
        <title>Prometheus Trading System</title>
        <meta name="description" content="Özerk kripto trading dashboard" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body className="min-h-screen bg-gray-950 text-gray-100 font-mono">
        <RootNav />
        {/* Desktop: push content right of sidebar; Mobile: full width */}
        <div className="lg:ml-56">
          <main className="p-3 md:p-4 lg:p-5">{children}</main>
        </div>
        <SmartAlerts />
      </body>
    </html>
  )
}
