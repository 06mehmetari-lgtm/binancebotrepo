'use client'
import { useState, useEffect, useCallback, useRef } from 'react'

// ── Types ────────────────────────────────────────────────────────────────────

interface Lesson {
  lesson: string
  symbol: string
  side: string
  pnl_pct: number
  outcome: 'WIN' | 'LOSS'
  close_reason: string
  confidence: number
  regime?: string
  ts: number
}

interface ObserverEvent {
  ts: number
  type: string
  level: 'success' | 'error' | 'warning' | 'info'
  title: string
  detail: string
  symbol: string
  pnl_pct: number | null
  icon: string
}

interface CellStats { wins: number; losses: number }

interface StrategyStats {
  lessons_count: number
  wins: number
  losses: number
  win_rate: number
  avg_pnl: number
  avg_hold_hours: number
  regimes: string[]
  sides: string[]
  grid: Record<string, Record<string, CellStats>>
  by_reason: Record<string, CellStats>
  conf_buckets: Record<string, CellStats>
  symbols: { symbol: string; wins: number; losses: number; win_rate: number }[]
  strategy_doc: string | null
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtPnl(p: number) {
  return `${p >= 0 ? '+' : ''}${(p * 100).toFixed(2)}%`
}

function fmtTs(ts: number) {
  return new Date(ts * 1000).toLocaleString('tr-TR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function fmtHold(h: number) {
  if (h < 1) return `${Math.round(h * 60)}dk`
  return `${h.toFixed(1)}sa`
}

function winRatePct(s: CellStats) {
  const total = s.wins + s.losses
  if (!total) return null
  return Math.round((s.wins / total) * 100)
}

function cellColor(pct: number | null) {
  if (pct === null) return 'bg-gray-900/30 text-gray-700'
  if (pct >= 60) return 'bg-green-900/40 text-green-400'
  if (pct >= 50) return 'bg-yellow-900/30 text-yellow-400'
  return 'bg-red-900/30 text-red-400'
}

function levelColor(level: string) {
  switch (level) {
    case 'success': return 'border-green-700/40 bg-green-900/10'
    case 'error':   return 'border-red-700/40 bg-red-900/10'
    case 'warning': return 'border-yellow-700/40 bg-yellow-900/10'
    default:        return 'border-gray-700/40 bg-gray-900/10'
  }
}

function levelDot(level: string) {
  switch (level) {
    case 'success': return 'text-green-400'
    case 'error':   return 'text-red-400'
    case 'warning': return 'text-yellow-400'
    default:        return 'text-blue-400'
  }
}

// ── Tab 1: AI Dersleri ───────────────────────────────────────────────────────

function LessonCard({ lesson }: { lesson: Lesson }) {
  const isWin = lesson.outcome === 'WIN'
  return (
    <div className={`border rounded-xl p-4 space-y-2 ${
      isWin ? 'border-green-700/40 bg-green-900/10' : 'border-red-700/40 bg-red-900/10'
    }`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-xs font-bold px-2 py-0.5 rounded ${
          isWin ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
        }`}>
          {isWin ? '▲ WIN' : '▼ LOSS'}
        </span>
        <span className="text-white font-semibold text-sm">{lesson.symbol}</span>
        <span className={`text-sm font-mono font-bold ${isWin ? 'text-green-400' : 'text-red-400'}`}>
          {fmtPnl(lesson.pnl_pct)}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded border ${
          lesson.side === 'long'
            ? 'border-blue-700/40 bg-blue-900/20 text-blue-400'
            : 'border-purple-700/40 bg-purple-900/20 text-purple-400'
        }`}>
          {(lesson.side || 'unknown').toUpperCase()}
        </span>
        {lesson.regime && (
          <span className="text-xs px-2 py-0.5 rounded border border-gray-700/40 bg-gray-900/20 text-gray-400">
            {lesson.regime}
          </span>
        )}
        <span className="text-xs text-gray-600 ml-auto">{fmtTs(lesson.ts)}</span>
      </div>
      <div className="flex items-center gap-3 text-xs text-gray-500">
        <span>Güven: <span className="text-gray-300">{(lesson.confidence * 100).toFixed(0)}%</span></span>
        <span>Kapanış: <span className="text-gray-300">{lesson.close_reason}</span></span>
      </div>
      <p className="text-gray-300 text-sm leading-relaxed border-t border-gray-700/40 pt-2">
        {lesson.lesson}
      </p>
    </div>
  )
}

function LessonsTab() {
  const [lessons, setLessons] = useState<Lesson[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'WIN' | 'LOSS'>('all')
  const [symbolFilter, setSymbolFilter] = useState('')

  const fetch_ = useCallback(async () => {
    try {
      const data = await fetch('/api/learning').then(r => r.json())
      if (Array.isArray(data)) setLessons(data)
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetch_(); const t = setInterval(fetch_, 30000); return () => clearInterval(t) }, [fetch_])

  const symbols = Array.from(new Set(lessons.map(l => l.symbol))).sort()
  const filtered = lessons.filter(l => {
    if (filter !== 'all' && l.outcome !== filter) return false
    if (symbolFilter && l.symbol !== symbolFilter) return false
    return true
  })
  const wins = lessons.filter(l => l.outcome === 'WIN').length
  const avgPnl = lessons.length > 0
    ? (lessons.reduce((s, l) => s + l.pnl_pct, 0) / lessons.length * 100).toFixed(2)
    : '—'
  const winRate = lessons.length > 0 ? Math.round(wins / lessons.length * 100) : 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Toplam Ders', value: lessons.length.toString(), color: 'text-white' },
          { label: 'Kazanan', value: wins.toString(), color: 'text-green-400' },
          { label: 'Kaybeden', value: (lessons.length - wins).toString(), color: 'text-red-400' },
          { label: 'Ort. P&L', value: avgPnl !== '—' ? `${Number(avgPnl) >= 0 ? '+' : ''}${avgPnl}%` : '—', color: Number(avgPnl) >= 0 ? 'text-green-400' : 'text-red-400' },
        ].map(s => (
          <div key={s.label} className="border border-gray-800 rounded-xl p-3 bg-gray-900/40 text-center">
            <p className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</p>
            <p className="text-gray-500 text-xs mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {lessons.length > 0 && (
        <div className="border border-gray-800 rounded-xl p-3 bg-gray-900/40">
          <div className="flex items-center justify-between mb-1.5 text-xs text-gray-500">
            <span>Kazanma Oranı</span>
            <span className="font-bold text-white">{winRate}%</span>
          </div>
          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-green-600 to-green-400 rounded-full transition-all" style={{ width: `${winRate}%` }} />
          </div>
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        {(['all', 'WIN', 'LOSS'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              filter === f
                ? f === 'WIN' ? 'bg-green-900/40 border-green-600/50 text-green-400'
                  : f === 'LOSS' ? 'bg-red-900/40 border-red-600/50 text-red-400'
                  : 'bg-orange-900/40 border-orange-600/50 text-orange-400'
                : 'border-gray-700 text-gray-500 hover:text-gray-300'
            }`}>
            {f === 'all' ? 'Tümü' : f === 'WIN' ? '▲ Kazanan' : '▼ Kaybeden'}
          </button>
        ))}
        {symbols.length > 0 && (
          <select value={symbolFilter} onChange={e => setSymbolFilter(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-900 text-gray-400 focus:outline-none focus:border-orange-500">
            <option value="">Tüm Semboller</option>
            {symbols.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </div>

      {loading ? (
        <div className="text-center py-16 text-gray-600">Dersler yükleniyor...</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-gray-600 text-sm">
            {lessons.length === 0 ? 'Henüz ders yok — sistem trade kapattıkça burada görünür' : 'Bu filtreye uyan ders bulunamadı'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((l, i) => <LessonCard key={i} lesson={l} />)}
        </div>
      )}
    </div>
  )
}

// ── Tab 2: Canlı Akış ────────────────────────────────────────────────────────

const TYPE_LABELS: Record<string, string> = {
  TRADE_CLOSE: 'Trade Kapandı',
  TRADE_OPEN:  'Trade Açıldı',
  BLOCK:       'Engellendi',
  REGIME:      'Rejim',
  SIGNAL:      'Sinyal',
  PDF:         'PDF',
  STRATEGY:    'Strateji',
  SYSTEM:      'Sistem',
}

function EventRow({ ev }: { ev: ObserverEvent }) {
  return (
    <div className={`border rounded-lg p-3 space-y-1 ${levelColor(ev.level)}`}>
      <div className="flex items-center gap-2">
        <span className="text-base leading-none">{ev.icon}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono uppercase tracking-wide ${levelDot(ev.level)} border border-current/30 bg-current/5`}>
          {TYPE_LABELS[ev.type] || ev.type}
        </span>
        {ev.symbol && ev.symbol !== 'SYSTEM' && ev.symbol !== 'MARKET' && (
          <span className="text-xs font-bold text-white">{ev.symbol}</span>
        )}
        {ev.pnl_pct !== null && ev.pnl_pct !== undefined && (
          <span className={`text-xs font-mono font-bold ml-auto ${ev.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {fmtPnl(ev.pnl_pct)}
          </span>
        )}
        {(ev.pnl_pct === null || ev.pnl_pct === undefined) && (
          <span className="text-[10px] text-gray-600 ml-auto">{fmtTs(ev.ts)}</span>
        )}
      </div>
      <p className="text-white text-xs font-medium leading-snug">{ev.title}</p>
      {ev.detail && <p className="text-gray-500 text-[11px] leading-snug">{ev.detail}</p>}
      {(ev.pnl_pct !== null && ev.pnl_pct !== undefined) && (
        <p className="text-[10px] text-gray-600 text-right">{fmtTs(ev.ts)}</p>
      )}
    </div>
  )
}

function FeedTab() {
  const [events, setEvents] = useState<ObserverEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<string>('ALL')
  const [paused, setPaused] = useState(false)
  const prevCount = useRef(0)
  const [newCount, setNewCount] = useState(0)

  const fetch_ = useCallback(async () => {
    if (paused) return
    try {
      const data: ObserverEvent[] = await fetch('/api/observer?limit=200').then(r => r.json())
      if (Array.isArray(data)) {
        setEvents(data)
        if (data.length > prevCount.current) {
          setNewCount(data.length - prevCount.current)
          setTimeout(() => setNewCount(0), 3000)
        }
        prevCount.current = data.length
      }
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [paused])

  useEffect(() => { fetch_(); const t = setInterval(fetch_, 5000); return () => clearInterval(t) }, [fetch_])

  const typeOptions = ['ALL', ...Array.from(new Set(events.map(e => e.type))).sort()]
  const filtered = filter === 'ALL' ? events : events.filter(e => e.type === filter)

  const counts = {
    TRADE_CLOSE: events.filter(e => e.type === 'TRADE_CLOSE').length,
    BLOCK:       events.filter(e => e.type === 'BLOCK').length,
    REGIME:      events.filter(e => e.type === 'REGIME').length,
    SIGNAL:      events.filter(e => e.type === 'SIGNAL').length,
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Trade Kapandı', value: counts.TRADE_CLOSE, color: 'text-white' },
          { label: 'Engellendi', value: counts.BLOCK, color: 'text-yellow-400' },
          { label: 'Rejim Değişimi', value: counts.REGIME, color: 'text-blue-400' },
          { label: 'Güçlü Sinyal', value: counts.SIGNAL, color: 'text-orange-400' },
        ].map(s => (
          <div key={s.label} className="border border-gray-800 rounded-xl p-3 bg-gray-900/40 text-center">
            <p className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</p>
            <p className="text-gray-500 text-xs mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="flex gap-2 flex-wrap items-center">
        <div className="flex gap-1 flex-wrap">
          {typeOptions.map(t => (
            <button key={t} onClick={() => setFilter(t)}
              className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                filter === t
                  ? 'bg-orange-900/40 border-orange-600/50 text-orange-400'
                  : 'border-gray-700 text-gray-500 hover:text-gray-300'
              }`}>
              {t === 'ALL' ? 'Tümü' : (TYPE_LABELS[t] || t)}
            </button>
          ))}
        </div>
        <button onClick={() => setPaused(p => !p)}
          className={`ml-auto text-xs px-3 py-1.5 rounded-lg border transition-colors ${
            paused ? 'bg-yellow-900/40 border-yellow-600/50 text-yellow-400' : 'border-gray-700 text-gray-500 hover:text-gray-300'
          }`}>
          {paused ? '▶ Devam' : '⏸ Duraklat'}
        </button>
        {newCount > 0 && (
          <span className="text-xs text-green-400 font-bold animate-pulse">+{newCount} yeni</span>
        )}
      </div>

      {loading ? (
        <div className="text-center py-16 text-gray-600">Olaylar yükleniyor...</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-gray-600 text-sm">
          Henüz olay yok — sistem aktif hale gelince burada görünür
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((ev, i) => <EventRow key={i} ev={ev} />)}
        </div>
      )}
    </div>
  )
}

// ── Tab 3: Strateji Analizi ──────────────────────────────────────────────────

function WinRateCell({ stats }: { stats: CellStats }) {
  const pct = winRatePct(stats)
  const total = stats.wins + stats.losses
  return (
    <div className={`rounded p-2 text-center ${cellColor(pct)}`}>
      {pct !== null ? (
        <>
          <p className="text-sm font-bold font-mono">{pct}%</p>
          <p className="text-[10px] opacity-60">{total} trade</p>
        </>
      ) : (
        <p className="text-xs opacity-30">—</p>
      )}
    </div>
  )
}

function StatsTab() {
  const [stats, setStats] = useState<StrategyStats | null>(null)
  const [loading, setLoading] = useState(true)

  const fetch_ = useCallback(async () => {
    try {
      const data = await fetch('/api/strategy-stats').then(r => r.json())
      if (data.lessons_count !== undefined) setStats(data)
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetch_(); const t = setInterval(fetch_, 60000); return () => clearInterval(t) }, [fetch_])

  if (loading) return <div className="text-center py-16 text-gray-600">İstatistikler yükleniyor...</div>
  if (!stats || stats.lessons_count === 0) return (
    <div className="text-center py-16 text-gray-600 text-sm">
      Henüz yeterli ders yok — trade kapandıkça istatistikler burada görünür
    </div>
  )

  const overallWinRate = Math.round(stats.win_rate * 100)

  return (
    <div className="space-y-5">
      {/* Overview strip */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
        {[
          { label: 'Toplam Trade', value: stats.lessons_count.toString(), color: 'text-white' },
          { label: 'Kazanma Oranı', value: `${overallWinRate}%`, color: overallWinRate >= 52 ? 'text-green-400' : 'text-red-400' },
          { label: 'Kazanan', value: stats.wins.toString(), color: 'text-green-400' },
          { label: 'Kaybeden', value: stats.losses.toString(), color: 'text-red-400' },
          { label: 'Ort. P&L', value: `${stats.avg_pnl >= 0 ? '+' : ''}${(stats.avg_pnl * 100).toFixed(2)}%`, color: stats.avg_pnl >= 0 ? 'text-green-400' : 'text-red-400' },
          { label: 'Ort. Süre', value: fmtHold(stats.avg_hold_hours), color: 'text-blue-400' },
        ].map(s => (
          <div key={s.label} className="border border-gray-800 rounded-xl p-3 bg-gray-900/40 text-center">
            <p className={`text-lg font-bold font-mono ${s.color}`}>{s.value}</p>
            <p className="text-gray-500 text-[11px] mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Heat map: regime × side */}
      {stats.regimes.length > 0 && (
        <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/40 space-y-3">
          <h3 className="text-white text-sm font-semibold">Rejim × Yön Kazanma Oranı</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th className="text-left text-gray-500 font-normal pb-2 pr-4">Rejim</th>
                  {stats.sides.map(s => (
                    <th key={s} className="text-center text-gray-400 font-semibold pb-2 px-2 uppercase">{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="space-y-1">
                {stats.regimes.map(regime => (
                  <tr key={regime}>
                    <td className="text-gray-400 pr-4 py-1 text-[11px] font-mono">{regime}</td>
                    {stats.sides.map(side => (
                      <td key={side} className="px-2 py-1">
                        <WinRateCell stats={stats.grid[regime]?.[side] || { wins: 0, losses: 0 }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-gray-600">Yeşil ≥ 60% | Sarı 50–60% | Kırmızı &lt; 50%</p>
        </div>
      )}

      {/* Confidence buckets */}
      {stats.conf_buckets && (
        <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/40 space-y-3">
          <h3 className="text-white text-sm font-semibold">Güven Seviyesi vs Başarı</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {Object.entries(stats.conf_buckets).map(([bucket, s]) => {
              const pct = winRatePct(s)
              return (
                <div key={bucket} className={`rounded-lg p-3 text-center ${cellColor(pct)}`}>
                  <p className="text-xs font-mono font-bold mb-1">{bucket}</p>
                  <p className="text-lg font-bold font-mono">{pct !== null ? `${pct}%` : '—'}</p>
                  <p className="text-[10px] opacity-60">{s.wins + s.losses} trade</p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Close reason breakdown */}
      {stats.by_reason && Object.keys(stats.by_reason).length > 0 && (
        <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/40 space-y-3">
          <h3 className="text-white text-sm font-semibold">Kapanış Sebebi Analizi</h3>
          <div className="space-y-2">
            {Object.entries(stats.by_reason)
              .sort((a, b) => (b[1].wins + b[1].losses) - (a[1].wins + a[1].losses))
              .slice(0, 8)
              .map(([reason, s]) => {
                const total = s.wins + s.losses
                const pct = total > 0 ? Math.round((s.wins / total) * 100) : 0
                return (
                  <div key={reason} className="flex items-center gap-3">
                    <span className="text-gray-400 text-xs w-32 truncate font-mono">{reason}</span>
                    <div className="flex-1 h-4 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${pct >= 60 ? 'bg-green-500/60' : pct >= 50 ? 'bg-yellow-500/60' : 'bg-red-500/60'}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className={`text-xs font-mono font-bold w-10 text-right ${pct >= 60 ? 'text-green-400' : pct >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                      {pct}%
                    </span>
                    <span className="text-[10px] text-gray-600 w-12 text-right">{total}t</span>
                  </div>
                )
              })}
          </div>
        </div>
      )}

      {/* Symbol leaderboard */}
      {stats.symbols.length > 0 && (
        <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/40 space-y-3">
          <h3 className="text-white text-sm font-semibold">Sembol Sıralaması</h3>
          <div className="space-y-2">
            {stats.symbols.map((sym) => {
              const pct = Math.round(sym.win_rate * 100)
              return (
                <div key={sym.symbol} className="flex items-center gap-3">
                  <span className="text-white text-xs font-bold w-20">{sym.symbol}</span>
                  <div className="flex-1 h-4 bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${pct >= 60 ? 'bg-green-500/60' : pct >= 50 ? 'bg-yellow-500/60' : 'bg-red-500/60'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className={`text-xs font-mono font-bold w-10 text-right ${pct >= 60 ? 'text-green-400' : pct >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {pct}%
                  </span>
                  <span className="text-[10px] text-gray-600 w-16 text-right">{sym.wins}W/{sym.losses}L</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Tab 4: AI Strateji Belgesi ───────────────────────────────────────────────

function StrategyDocTab() {
  const [doc, setDoc] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)

  const fetch_ = useCallback(async () => {
    try {
      const data = await fetch('/api/strategy-stats').then(r => r.json())
      if (data.strategy_doc) {
        setDoc(data.strategy_doc)
        setUpdatedAt(new Date().toLocaleString('tr-TR'))
      } else {
        setDoc(null)
      }
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetch_(); const t = setInterval(fetch_, 60000); return () => clearInterval(t) }, [fetch_])

  if (loading) return <div className="text-center py-16 text-gray-600">Strateji belgesi yükleniyor...</div>

  if (!doc) return (
    <div className="text-center py-16 space-y-3">
      <p className="text-4xl">🧠</p>
      <p className="text-gray-500 text-sm">Strateji belgesi henüz oluşturulmadı</p>
      <p className="text-gray-600 text-xs max-w-sm mx-auto">
        En az 10 trade kapandıktan sonra AI saatlik analiz yapar ve kurallar belgesi oluşturur.
        Belge her saat güncellenir.
      </p>
    </div>
  )

  // Render markdown-like sections with basic formatting
  const lines = doc.split('\n')
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>AI tarafından trade geçmişinden üretildi</span>
        {updatedAt && <span>Son güncelleme: {updatedAt}</span>}
      </div>

      <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/40 space-y-2">
        {lines.map((line, i) => {
          if (line.startsWith('## ')) {
            return (
              <h2 key={i} className="text-orange-400 font-bold text-sm pt-4 first:pt-0 border-t border-gray-700/40 mt-4 first:border-0 first:mt-0">
                {line.replace('## ', '')}
              </h2>
            )
          }
          if (line.startsWith('### ')) {
            return <h3 key={i} className="text-white font-semibold text-xs pt-2">{line.replace('### ', '')}</h3>
          }
          if (line.startsWith('- ') || line.startsWith('• ')) {
            return (
              <div key={i} className="flex gap-2 text-gray-300 text-xs leading-relaxed">
                <span className="text-orange-400 mt-0.5 shrink-0">•</span>
                <span>{line.replace(/^[-•] /, '')}</span>
              </div>
            )
          }
          if (line.trim() === '') return <div key={i} className="h-1" />
          return <p key={i} className="text-gray-300 text-xs leading-relaxed">{line}</p>
        })}
      </div>
    </div>
  )
}

// ── Tab 5: LLM Durum ─────────────────────────────────────────────────────────

interface LLMProvider {
  name: string
  status: 'working' | 'rate_limited' | 'no_key' | 'error' | 'local' | 'unknown'
  keysConfigured: number
  keysReady: number
  calls: number
  rateLimits: number
  errors: number
  successes: number
  lastSuccessTs: number
  lastError: string
  cooldownUntil: number
  cooldownSecsLeft: number
  dailyLimit: number | null
  estimatedRemaining: number | null
  note: string
}

function statusBadge(status: LLMProvider['status']) {
  switch (status) {
    case 'working':      return <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-green-900/40 text-green-400 border border-green-700/40">✓ Çalışıyor</span>
    case 'rate_limited': return <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-yellow-900/40 text-yellow-400 border border-yellow-700/40">⏳ Limit Doldu</span>
    case 'no_key':       return <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-gray-800 text-gray-500 border border-gray-700">— Key Yok</span>
    case 'error':        return <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-red-900/40 text-red-400 border border-red-700/40">✕ Hata</span>
    case 'local':        return <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-900/40 text-blue-400 border border-blue-700/40">🖥 Yerel</span>
    default:             return <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-gray-800 text-gray-600 border border-gray-700">? Bilinmiyor</span>
  }
}

function timeAgo(ts: number) {
  if (!ts) return '—'
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s önce`
  if (diff < 3600) return `${Math.floor(diff / 60)}dk önce`
  return `${Math.floor(diff / 3600)}sa önce`
}

function LLMStatusTab() {
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetch_ = useCallback(async () => {
    try {
      const data = await fetch('/api/llm-status').then(r => r.json())
      if (Array.isArray(data)) {
        setProviders(data)
        setLastUpdate(new Date().toLocaleTimeString('tr-TR'))
      }
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetch_(); const t = setInterval(fetch_, 30000); return () => clearInterval(t) }, [fetch_])

  const working    = providers.filter(p => p.status === 'working' || p.status === 'local').length
  const limited    = providers.filter(p => p.status === 'rate_limited').length
  const noKey      = providers.filter(p => p.status === 'no_key').length
  const totalCalls = providers.reduce((s, p) => s + p.calls, 0)

  if (loading) return <div className="text-center py-16 text-gray-600">LLM durumu yükleniyor...</div>

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Çalışan', value: working.toString(), color: 'text-green-400' },
          { label: 'Limitli', value: limited.toString(), color: limited > 0 ? 'text-yellow-400' : 'text-gray-500' },
          { label: 'Key Yok', value: noKey.toString(), color: noKey > 0 ? 'text-red-400' : 'text-gray-500' },
          { label: 'Toplam İstek', value: totalCalls.toString(), color: 'text-white' },
        ].map(s => (
          <div key={s.label} className="border border-gray-800 rounded-xl p-3 bg-gray-900/40 text-center">
            <p className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</p>
            <p className="text-gray-500 text-xs mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Provider table */}
      <div className="border border-gray-800 rounded-xl bg-gray-900/40 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h3 className="text-white text-sm font-semibold">Provider Durumu</h3>
          {lastUpdate && <span className="text-[10px] text-gray-600">Son güncelleme: {lastUpdate}</span>}
        </div>
        <div className="divide-y divide-gray-800/50">
          {providers.map(p => (
            <div key={p.name} className="px-4 py-3 space-y-2">
              {/* Row 1: name + status + keys */}
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-white font-bold text-sm w-24">{p.name}</span>
                {statusBadge(p.status)}
                <span className="text-xs text-gray-500 ml-auto">
                  {p.name !== 'Ollama'
                    ? `${p.keysReady}/${p.keysConfigured} key hazır`
                    : 'Yerel model'
                  }
                </span>
              </div>

              {/* Row 2: stats */}
              <div className="flex gap-4 flex-wrap text-[11px]">
                <span className="text-gray-500">
                  İstek: <span className="text-gray-300 font-mono">{p.calls}</span>
                </span>
                <span className={p.rateLimits > 0 ? 'text-yellow-500' : 'text-gray-500'}>
                  Rate limit: <span className="font-mono">{p.rateLimits}</span>
                </span>
                <span className={p.errors > 0 ? 'text-red-400' : 'text-gray-500'}>
                  Hata: <span className="font-mono">{p.errors}</span>
                </span>
                <span className="text-gray-500">
                  Son başarı: <span className="text-gray-300">{timeAgo(p.lastSuccessTs)}</span>
                </span>
              </div>

              {/* Row 3: daily limit bar or cooldown */}
              {p.status === 'rate_limited' && p.cooldownSecsLeft > 0 && (
                <div className="text-[11px] text-yellow-400">
                  Soğuma: {p.cooldownSecsLeft}s kaldı
                </div>
              )}
              {p.dailyLimit !== null && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-gray-500">
                    <span>{p.note}</span>
                    <span className="font-mono">
                      {p.estimatedRemaining !== null
                        ? `~${p.estimatedRemaining} istek kaldı`
                        : '—'
                      }
                    </span>
                  </div>
                  {p.estimatedRemaining !== null && (
                    <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          p.estimatedRemaining / p.dailyLimit > 0.3
                            ? 'bg-green-500/60'
                            : p.estimatedRemaining / p.dailyLimit > 0.1
                              ? 'bg-yellow-500/60'
                              : 'bg-red-500/60'
                        }`}
                        style={{ width: `${Math.min(100, (p.estimatedRemaining / p.dailyLimit) * 100)}%` }}
                      />
                    </div>
                  )}
                </div>
              )}
              {p.dailyLimit === null && p.status !== 'no_key' && (
                <p className="text-[10px] text-gray-600">{p.note}</p>
              )}
              {p.lastError && p.status === 'error' && (
                <p className="text-[10px] text-red-400/80 font-mono truncate">{p.lastError}</p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Key recommendation */}
      {noKey > 0 && (
        <div className="border border-yellow-700/40 rounded-xl p-4 bg-yellow-900/10 space-y-2">
          <h4 className="text-yellow-400 text-sm font-semibold">Eksik Key&apos;ler</h4>
          <div className="space-y-1">
            {providers.filter(p => p.status === 'no_key').map(p => (
              <div key={p.name} className="flex items-center gap-2 text-xs">
                <span className="text-red-400">✕</span>
                <span className="text-white font-bold w-24">{p.name}</span>
                <span className="text-gray-400">{p.note}</span>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-gray-500 pt-1">
            Eksik key&apos;leri .env dosyasına ekle. Çoklu key için GROQ_API_KEY_1, GROQ_API_KEY_2 formatını kullan.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

type TabId = 'readiness' | 'lessons' | 'feed' | 'stats' | 'strategy' | 'llm'

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'readiness', label: 'Canlıya Geçiş', icon: '🎯' },
  { id: 'lessons',  label: 'AI Dersleri',       icon: '📖' },
  { id: 'feed',     label: 'Canlı Akış',         icon: '📡' },
  { id: 'stats',    label: 'Strateji Analizi',   icon: '📊' },
  { id: 'strategy', label: 'Strateji Belgesi',   icon: '🧠' },
  { id: 'llm',      label: 'LLM Durum',          icon: '🔌' },
]

// ── Readiness Tab ─────────────────────────────────────────────────────────────

interface Criterion { value: number; target: number; progress: number; label: string; unit: string; invert?: boolean }
interface ReadinessData {
  overall: number
  criteria: { trades: Criterion; winRate: Criterion; sharpe: Criterion; maxDrawdown: Criterion }
  bestStrategy: string
  recentTrades: { symbol: string; direction: string; pnl_pct: number; outcome: string; reason: string; confidence: number; regime: string; lesson: string | null; ts: number }[]
  byReason: Record<string, { wins: number; losses: number }>
  totalTrades: number; totalWins: number; totalLosses: number; totalPnl: number
}

function CriterionBar({ c, met }: { c: Criterion; met: boolean }) {
  const color = met ? 'bg-green-500' : c.progress > 60 ? 'bg-yellow-500' : 'bg-orange-500'
  const display = c.invert
    ? `${c.value}${c.unit} (hedef <${c.target}${c.unit})`
    : `${c.value}${c.unit} / ${c.target}${c.unit}`
  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-gray-400 text-xs">{c.label}</span>
        <span className={`text-xs font-semibold ${met ? 'text-green-400' : 'text-gray-300'}`}>
          {met ? '✓ ' : ''}{display}
        </span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${c.progress}%` }} />
      </div>
    </div>
  )
}

function ReadinessTab() {
  const [data, setData] = useState<ReadinessData | null>(null)
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/live-readiness')
      const d = await res.json()
      setData(d)
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t) }, [load])

  if (loading) return <div className="text-center py-16 text-gray-600">Yükleniyor...</div>
  if (!data) return <div className="text-center py-16 text-gray-600">Veri yok</div>

  const overall = data.overall
  const c = data.criteria
  const metTrades  = c.trades.value >= c.trades.target
  const metWin     = c.winRate.value >= c.winRate.target
  const metSharpe  = c.sharpe.value >= c.sharpe.target
  const metDD      = c.maxDrawdown.value <= c.maxDrawdown.target
  const allMet     = metTrades && metWin && metSharpe && metDD
  const metCount   = [metTrades, metWin, metSharpe, metDD].filter(Boolean).length

  const ringColor = overall >= 100 ? '#22c55e' : overall >= 70 ? '#f59e0b' : overall >= 40 ? '#f97316' : '#ef4444'

  return (
    <div className="space-y-4">

      {/* Hero — overall progress */}
      <div className="border border-gray-800 rounded-xl p-6 bg-gray-900/60 flex flex-col sm:flex-row items-center gap-6">
        {/* Ring */}
        <div className="relative w-32 h-32 shrink-0">
          <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
            <circle cx="60" cy="60" r="52" fill="none" stroke="#1f2937" strokeWidth="12" />
            <circle cx="60" cy="60" r="52" fill="none" stroke={ringColor} strokeWidth="12"
              strokeDasharray={`${2 * Math.PI * 52}`}
              strokeDashoffset={`${2 * Math.PI * 52 * (1 - overall / 100)}`}
              strokeLinecap="round" className="transition-all duration-700" />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-black text-white">{overall}%</span>
            <span className="text-[10px] text-gray-500">HAZIR</span>
          </div>
        </div>

        {/* Text */}
        <div className="flex-1 text-center sm:text-left">
          <h2 className="text-white font-bold text-lg mb-1">
            {allMet ? '🟢 CANLI TRADİNGE GEÇİŞ HAZIR!' : '🎯 Canlıya Geçiş Hedefi'}
          </h2>
          <p className="text-gray-400 text-sm mb-3">
            {allMet
              ? 'Tüm kriterler karşılandı. Sistem canlı trading için onaya hazır.'
              : `${metCount}/4 kriter karşılandı. %100 olduğunda canlıya geçebilirsin.`}
          </p>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-gray-800/60 rounded-lg p-2.5 text-center">
              <div className="text-gray-500 mb-0.5">Toplam Trade</div>
              <div className="text-white font-bold text-base">{data.totalTrades}</div>
            </div>
            <div className="bg-gray-800/60 rounded-lg p-2.5 text-center">
              <div className="text-gray-500 mb-0.5">Toplam P&L</div>
              <div className={`font-bold text-base ${data.totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {data.totalPnl >= 0 ? '+' : ''}{data.totalPnl.toFixed(2)}%
              </div>
            </div>
            <div className="bg-gray-800/60 rounded-lg p-2.5 text-center">
              <div className="text-gray-500 mb-0.5">Kazanan</div>
              <div className="text-green-400 font-bold text-base">{data.totalWins} ✓</div>
            </div>
            <div className="bg-gray-800/60 rounded-lg p-2.5 text-center">
              <div className="text-gray-500 mb-0.5">Kaybeden</div>
              <div className="text-red-400 font-bold text-base">{data.totalLosses} ✗</div>
            </div>
          </div>
        </div>
      </div>

      {/* Criteria bars */}
      <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/60 space-y-4">
        <h3 className="text-white font-semibold text-sm">Canlıya Geçiş Kriterleri</h3>
        <CriterionBar c={c.trades}      met={metTrades} />
        <CriterionBar c={c.winRate}     met={metWin} />
        <CriterionBar c={c.sharpe}      met={metSharpe} />
        <CriterionBar c={c.maxDrawdown} met={metDD} />
        <p className="text-gray-600 text-xs pt-1">
          Tüm kriterler karşılandığında shadow sistem otomatik olarak canlıya geçiş onayı verir.
        </p>
      </div>

      {/* Trade history */}
      {data.recentTrades.length > 0 && (
        <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/60">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Son Trade Geçmişi</h3>
            <button onClick={() => setShowAll(v => !v)} className="text-xs text-gray-500 hover:text-gray-300">
              {showAll ? 'Az göster' : 'Tümünü göster'}
            </button>
          </div>
          <div className="space-y-2">
            {(showAll ? data.recentTrades : data.recentTrades.slice(0, 10)).map((t, i) => {
              const win = t.pnl_pct > 0 || t.outcome === 'WIN'
              return (
                <div key={i} className={`rounded-lg p-3 border text-xs ${win ? 'border-green-800/40 bg-green-900/10' : 'border-red-800/40 bg-red-900/10'}`}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className={`font-bold ${win ? 'text-green-400' : 'text-red-400'}`}>{win ? '▲ WIN' : '▼ LOSS'}</span>
                      <span className="text-gray-300 font-semibold">{t.symbol}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${t.direction === 'long' ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
                        {t.direction?.toUpperCase()}
                      </span>
                    </div>
                    <span className={`font-bold ${win ? 'text-green-400' : 'text-red-400'}`}>
                      {t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct.toFixed(2)}%
                    </span>
                  </div>
                  <div className="flex gap-3 text-gray-500">
                    <span>Rejim: {t.regime}</span>
                    <span>Güven: {(t.confidence * 100).toFixed(0)}%</span>
                    {t.reason !== '—' && <span>Kapanış: {t.reason}</span>}
                  </div>
                  {t.lesson && (
                    <div className="mt-1.5 text-gray-400 border-t border-gray-700/40 pt-1.5">
                      💡 {t.lesson}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Breakdown by reason */}
      {Object.keys(data.byReason).length > 0 && (
        <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/60">
          <h3 className="text-white font-semibold text-sm mb-3">Kapanış Nedenine Göre Sonuçlar</h3>
          <div className="space-y-2">
            {Object.entries(data.byReason).sort((a, b) => (b[1].wins + b[1].losses) - (a[1].wins + a[1].losses)).map(([reason, stats]) => {
              const total = stats.wins + stats.losses
              const wr = total > 0 ? stats.wins / total : 0
              return (
                <div key={reason} className="flex items-center gap-3">
                  <span className="text-gray-400 text-xs w-28 truncate shrink-0">{reason}</span>
                  <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                    <div className="h-full bg-green-600 rounded-full" style={{ width: `${wr * 100}%` }} />
                  </div>
                  <span className="text-xs text-gray-500 w-20 text-right shrink-0">
                    {stats.wins}W / {stats.losses}L ({(wr * 100).toFixed(0)}%)
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {data.totalTrades === 0 && (
        <div className="text-center py-8 text-gray-600 text-sm">
          Henüz trade yok. Shadow system işlem yaptıkça burada görünecek.
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

export default function LearningPage() {
  const [tab, setTab] = useState<TabId>('readiness')

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* Header */}
      <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/60">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🤖</span>
          <div>
            <h1 className="text-white font-bold text-base">AI Öğrenme Merkezi</h1>
            <p className="text-gray-500 text-xs">
              PDF dersleri • Trade geçmişi • Canlı sistem olayları • Otomatik strateji üretimi
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800 pb-0 overflow-x-auto">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium rounded-t-lg transition-colors border-b-2 -mb-px shrink-0 ${
              tab === t.id
                ? 'border-orange-500 text-orange-400 bg-orange-900/10'
                : 'border-transparent text-gray-500 hover:text-gray-300 hover:bg-gray-800/40'
            }`}
          >
            <span>{t.icon}</span>
            <span className="hidden sm:inline">{t.label}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {tab === 'readiness' && <ReadinessTab />}
        {tab === 'lessons'  && <LessonsTab />}
        {tab === 'feed'     && <FeedTab />}
        {tab === 'stats'    && <StatsTab />}
        {tab === 'strategy' && <StrategyDocTab />}
        {tab === 'llm'      && <LLMStatusTab />}
      </div>
    </div>
  )
}
