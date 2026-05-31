'use client'
import { useEffect, useRef, useState } from 'react'

interface ActivityEvent {
  time: number
  type: string
  symbol?: string
  direction?: string
  confidence?: number
  source?: string
  rsi?: number
  label?: string
  regime?: string
  prev_regime?: string
  crisis_level?: number
  total?: number
  long?: number
  short?: number
  flat?: number
}

interface Coin {
  symbol: string
  direction: 'long' | 'short' | 'flat'
  confidence: number
  rsi: number | null
  macd_hist: number | null
  bb_position: number | null
  atr_pct: number | null
  volume_ratio: number | null
  drift: string
  regime: string | null
  timestamp: number | null
}

interface ScannerData {
  coins: Coin[]
  total: number
  long_count: number
  short_count: number
  flat_count: number
  ws_status: { status: string; symbols?: number } | null
  server_time: number
}

const DIR_STYLE: Record<string, string> = {
  long:  'text-green-400 bg-green-900/30 border-green-700/50',
  short: 'text-red-400 bg-red-900/30 border-red-700/50',
  flat:  'text-gray-500 bg-gray-800/20 border-gray-700/30',
}

const DRIFT_STYLE: Record<string, string> = {
  STABLE:   'text-green-400',
  WARNING:  'text-yellow-400',
  DRIFTING: 'text-orange-400',
  SHOCK:    'text-red-400',
}

const REGIME_STYLE: Record<string, string> = {
  trending_up:   'text-green-400',
  trending_down: 'text-red-400',
  volatile:      'text-orange-400',
  ranging:       'text-blue-400',
}

function RsiCell({ v }: { v: number | null }) {
  if (v == null) return <span className="text-gray-600">—</span>
  const color = v < 30 ? 'text-green-400 font-bold' : v > 70 ? 'text-red-400 font-bold' : 'text-gray-300'
  return <span className={`font-mono ${color}`}>{v.toFixed(1)}</span>
}

function MacdCell({ v }: { v: number | null }) {
  if (v == null) return <span className="text-gray-600">—</span>
  const color = v > 0 ? 'text-green-400' : 'text-red-400'
  const arrow = v > 0 ? '▲' : '▼'
  return <span className={`font-mono text-xs ${color}`}>{arrow} {Math.abs(v).toFixed(3)}</span>
}

function ConfBar({ v, dir }: { v: number; dir: string }) {
  const color = dir === 'long' ? 'bg-green-500' : dir === 'short' ? 'bg-red-500' : 'bg-gray-600'
  const pct = v >= 0.6 ? Math.min(100, v * 100) : Math.min(100, v * 100)
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} ${v >= 0.6 ? '' : 'opacity-40'}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`font-mono text-xs tabular-nums ${v >= 0.6 ? 'text-white' : 'text-gray-500'}`}>
        {(v * 100).toFixed(0)}%
      </span>
    </div>
  )
}

function VolBadge({ v }: { v: number | null }) {
  if (v == null) return <span className="text-gray-600">—</span>
  const color = v > 2 ? 'text-orange-400 font-bold' : v > 1.3 ? 'text-yellow-400' : 'text-gray-500'
  return <span className={`font-mono text-xs ${color}`}>{v.toFixed(2)}×</span>
}

function timeAgo(ts: number | null): string {
  if (!ts) return '—'
  const sec = Math.floor(Date.now() / 1000 - ts)
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  return `${Math.floor(sec / 3600)}h ago`
}

const PAGE_SIZE = 50

export default function ScannerPage() {
  const [data, setData] = useState<Partial<ScannerData>>({})
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterDir, setFilterDir] = useState<'all' | 'long' | 'short' | 'active'>('all')
  const [lastUpdate, setLastUpdate] = useState('')
  const [page, setPage] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()

  const fetchData = async () => {
    try {
      const [scanRes, actRes] = await Promise.all([
        fetch('/api/scanner'),
        fetch('/api/activity'),
      ])
      const scanJson = await scanRes.json()
      const actJson = await actRes.json()
      setData(scanJson)
      setActivity(Array.isArray(actJson) ? actJson : [])
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 5000)
    return () => clearInterval(intervalRef.current)
  }, [])

  const coins = (data.coins ?? []).filter(c => {
    if (search && !c.symbol.toLowerCase().includes(search.toLowerCase())) return false
    if (filterDir === 'long') return c.direction === 'long'
    if (filterDir === 'short') return c.direction === 'short'
    if (filterDir === 'active') return c.direction !== 'flat'
    return true
  })
  const totalPages = Math.ceil(coins.length / PAGE_SIZE)
  const pagedCoins = coins.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  const wsOk = data.ws_status?.status === 'CONNECTED'

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-green-400 text-lg">◌</span>
      <span className="text-sm">Connecting to live scanner...</span>
    </div>
  )

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">Live Market Scanner</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            Sistem 7/24 çalışıyor — siz burada olmasanız da tarama devam eder
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs shrink-0">
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-semibold ${
            wsOk ? 'text-green-400 bg-green-900/20 border-green-700/40' : 'text-gray-500 bg-gray-800/30 border-gray-700/40'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${wsOk ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            {wsOk ? `LIVE · ${data.ws_status?.symbols ?? 0} coins` : 'OFFLINE'}
          </span>
          <span className="text-gray-600">{lastUpdate ? `${lastUpdate} · 5s` : '5s refresh'}</span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          { label: 'Taranan Coin', value: String(data.total ?? 0), color: 'text-blue-400', sub: 'toplam' },
          { label: 'LONG Sinyal', value: String(data.long_count ?? 0), color: 'text-green-400', sub: 'alış' },
          { label: 'SHORT Sinyal', value: String(data.short_count ?? 0), color: 'text-red-400', sub: 'satış' },
          {
          label: 'Ort. Güven',
          value: (() => {
            const active = (data.coins ?? []).filter(c => c.direction !== 'flat')
            if (!active.length) return '—'
            const avg = active.reduce((s, c) => s + c.confidence, 0) / active.length
            return `${(avg * 100).toFixed(0)}%`
          })(),
          color: 'text-purple-400',
          sub: 'aktif sinyaller',
        },
        ].map(s => (
          <div key={s.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
            <p className="text-gray-500 text-xs uppercase tracking-wider">{s.label}</p>
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-gray-600 text-xs">{s.sub}</p>
          </div>
        ))}
      </div>

      {/* System running notice */}
      <div className="bg-blue-950/30 border border-blue-800/40 rounded-lg px-4 py-2.5 flex items-center gap-3">
        <span className="text-blue-400 text-lg shrink-0">ℹ</span>
        <div className="text-xs text-blue-300">
          <span className="font-semibold">Sistem sunucuda 7/24 çalışıyor.</span>
          {' '}Bu sayfayı kapatseniz bile bot coinleri taramaya, sinyal üretmeye ve öğrenmeye devam eder.
          Her 5 saniyede bir bu sayfa otomatik güncellenir.
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          placeholder="Coin ara... (BTC, ETH...)"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-gray-500 w-48"
        />
        {(['all', 'active', 'long', 'short'] as const).map(f => (
          <button key={f}
            onClick={() => setFilterDir(f)}
            className={`px-3 py-1.5 rounded text-xs font-semibold transition-colors ${
              filterDir === f
                ? f === 'long' ? 'bg-green-900/50 text-green-400 border border-green-700/60'
                : f === 'short' ? 'bg-red-900/50 text-red-400 border border-red-700/60'
                : f === 'active' ? 'bg-orange-900/50 text-orange-400 border border-orange-700/60'
                : 'bg-gray-700 text-white border border-gray-600'
                : 'bg-gray-900 text-gray-500 border border-gray-800 hover:border-gray-600'
            }`}>
            {f === 'all' ? `Tümü (${data.total ?? 0})` :
             f === 'active' ? `Aktif (${(data.long_count ?? 0) + (data.short_count ?? 0)})` :
             f === 'long' ? `LONG (${data.long_count ?? 0})` :
             `SHORT (${data.short_count ?? 0})`}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-600">{coins.length} sonuç {totalPages > 1 ? `· s.${page+1}/${totalPages}` : ''}</span>
      </div>

      {/* Main table */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[700px]">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800 bg-gray-900/80">
                <th className="text-left px-4 py-2.5">Coin</th>
                <th className="text-left px-4 py-2.5">Sinyal</th>
                <th className="text-left px-4 py-2.5 w-36">Güven</th>
                <th className="text-left px-4 py-2.5">RSI-14</th>
                <th className="text-left px-4 py-2.5">MACD</th>
                <th className="hidden md:table-cell text-left px-4 py-2.5">Hacim</th>
                <th className="hidden md:table-cell text-left px-4 py-2.5">Drift</th>
                <th className="hidden lg:table-cell text-left px-4 py-2.5">Rejim</th>
                <th className="text-left px-4 py-2.5">Güncelleme</th>
              </tr>
            </thead>
            <tbody>
              {pagedCoins.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-gray-500">
                    {!data.total
                      ? 'Henüz tarama verisi yok — feature_engine başlatılıyor...'
                      : 'Filtreyle eşleşen coin bulunamadı'}
                  </td>
                </tr>
              ) : pagedCoins.map(c => (
                <tr key={c.symbol}
                  className={`border-b border-gray-800/40 hover:bg-gray-800/25 transition-colors ${
                    c.direction === 'long' ? 'bg-green-950/10' :
                    c.direction === 'short' ? 'bg-red-950/10' : ''
                  }`}>
                  <td className="px-4 py-2.5">
                    <a href={`/coin/${c.symbol}`} className="font-bold text-white text-sm hover:text-orange-400 transition-colors">{c.symbol.replace('USDT','')}</a>
                    <span className="text-gray-600 text-xs ml-1">USDT</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`px-1.5 py-0.5 rounded border text-xs font-bold uppercase ${DIR_STYLE[c.direction]}`}>
                      {c.direction}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <ConfBar v={c.confidence} dir={c.direction} />
                  </td>
                  <td className="px-4 py-2.5">
                    <RsiCell v={c.rsi} />
                  </td>
                  <td className="px-4 py-2.5">
                    <MacdCell v={c.macd_hist} />
                  </td>
                  <td className="hidden md:table-cell px-4 py-2.5">
                    <VolBadge v={c.volume_ratio} />
                  </td>
                  <td className="hidden md:table-cell px-4 py-2.5">
                    <span className={`text-xs font-semibold ${DRIFT_STYLE[c.drift] ?? 'text-gray-500'}`}>
                      {c.drift}
                    </span>
                  </td>
                  <td className="hidden lg:table-cell px-4 py-2.5">
                    {c.regime ? (
                      <span className={`text-xs ${REGIME_STYLE[c.regime] ?? 'text-gray-400'}`}>
                        {c.regime.replace('_', ' ')}
                      </span>
                    ) : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 font-mono">
                    {timeAgo(c.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">{coins.length} coin · sayfa {page + 1} / {totalPages}</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(0)} disabled={page === 0}
              className="px-2 py-1 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">«</button>
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
              className="px-2 py-1 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">‹</button>
            {Array.from({ length: Math.min(7, totalPages) }, (_, i) => {
              const p = Math.max(0, Math.min(totalPages - 7, page - 3)) + i
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={`px-2 py-1 rounded text-xs ${p === page ? 'bg-green-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                  {p + 1}
                </button>
              )
            })}
            <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
              className="px-2 py-1 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">›</button>
            <button onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1}
              className="px-2 py-1 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">»</button>
          </div>
        </div>
      )}

      {/* Activity Feed */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <div>
            <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">Canlı Aktivite Akışı</h2>
            <p className="text-gray-500 text-xs mt-0.5">Arka planda gerçekleşen sinyal olayları — siz burada olmasanız da devam eder</p>
          </div>
          <span className="text-xs text-gray-600">{activity.length} olay</span>
        </div>
        <div className="divide-y divide-gray-800/50 max-h-72 overflow-y-auto">
          {activity.length === 0 ? (
            <div className="px-4 py-6 text-center">
              <p className="text-gray-500 text-sm">Sistem çalışıyor — ilk tarama özeti ~60 saniye içinde gelecek</p>
              <p className="text-gray-600 text-xs mt-1">Aktif sinyal veya RSI uyarısı oluşunca burada anlık görünür</p>
            </div>
          ) : activity.map((ev, i) => {
            if (ev.type === 'scan_summary') {
              return (
                <div key={i} className="flex items-center gap-3 px-4 py-2 text-xs bg-gray-800/20">
                  <span className="text-blue-400 shrink-0">⟳</span>
                  <div className="flex-1 text-gray-400">
                    <span className="font-semibold text-blue-300">Tarama Tamamlandı</span>
                    <span className="ml-2">{ev.total} coin</span>
                    {(ev.long ?? 0) > 0 && <span className="ml-2 text-green-400">▲ {ev.long} LONG</span>}
                    {(ev.short ?? 0) > 0 && <span className="ml-2 text-red-400">▼ {ev.short} SHORT</span>}
                    {(ev.long ?? 0) === 0 && (ev.short ?? 0) === 0 && <span className="ml-2 text-gray-600">sinyal yok</span>}
                  </div>
                  <span className="text-gray-600 shrink-0 font-mono">{timeAgo(ev.time)}</span>
                </div>
              )
            }
            if (ev.type === 'regime_change') {
              const regimeColor: Record<string, string> = {
                trending_up: 'text-green-400', trending_down: 'text-red-400',
                volatile: 'text-orange-400', ranging: 'text-blue-400',
              }
              return (
                <div key={i} className="flex items-center gap-3 px-4 py-2 text-xs bg-purple-950/10">
                  <span className="shrink-0">🔄</span>
                  <div className="flex-1 min-w-0">
                    <span className="font-bold text-white">{(ev.symbol ?? '').replace('USDT', '')}</span>
                    <span className="ml-1.5 text-gray-500">rejim değişti:</span>
                    <span className="ml-1.5 text-gray-600 line-through">{ev.prev_regime?.replace('_', ' ')}</span>
                    <span className="mx-1 text-gray-600">→</span>
                    <span className={`font-semibold ${regimeColor[ev.regime ?? ''] ?? 'text-gray-400'}`}>
                      {ev.regime?.replace('_', ' ')}
                    </span>
                  </div>
                  <span className="text-gray-600 shrink-0 font-mono">{timeAgo(ev.time)}</span>
                </div>
              )
            }
            if (ev.type === 'rsi_alert') {
              const oversold = (ev.rsi ?? 50) < 50
              return (
                <div key={i} className={`flex items-center gap-3 px-4 py-2.5 text-xs ${oversold ? 'bg-green-950/10' : 'bg-red-950/10'}`}>
                  <span className="text-base shrink-0">{oversold ? '📉' : '📈'}</span>
                  <div className="flex-1 min-w-0">
                    <span className="font-bold text-white">{(ev.symbol ?? '').replace('USDT', '')}</span>
                    <span className={`ml-1.5 font-semibold ${oversold ? 'text-green-400' : 'text-red-400'}`}>
                      RSI {ev.rsi?.toFixed(1)}
                    </span>
                    <span className="ml-1.5 text-gray-500">{ev.label}</span>
                  </div>
                  <span className="text-gray-600 shrink-0 font-mono">{timeAgo(ev.time)}</span>
                </div>
              )
            }
            // signal event
            const isLong = ev.direction === 'long'
            const isShort = ev.direction === 'short'
            return (
              <div key={i} className={`flex items-center gap-3 px-4 py-2.5 text-xs ${
                isLong ? 'bg-green-950/15' : isShort ? 'bg-red-950/15' : ''
              }`}>
                <span className="text-base shrink-0">{isLong ? '🟢' : isShort ? '🔴' : '⬜'}</span>
                <div className="flex-1 min-w-0">
                  <span className="font-bold text-white">{(ev.symbol ?? '').replace('USDT', '')}</span>
                  <span className={`ml-1.5 font-bold uppercase ${isLong ? 'text-green-400' : isShort ? 'text-red-400' : 'text-gray-500'}`}>
                    {ev.direction}
                  </span>
                  <span className="ml-1.5 text-gray-500">
                    {((ev.confidence ?? 0) * 100).toFixed(0)}% · {ev.source}
                    {ev.rsi != null && <span className="ml-1">· RSI {ev.rsi}</span>}
                  </span>
                </div>
                <span className="text-gray-600 shrink-0 font-mono">{timeAgo(ev.time)}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Footer note */}
      <div className="text-center text-xs text-gray-700 pb-2 space-y-0.5">
        <p>⚡ Prometheus · {data.total ?? 0} coin izleniyor · Her 5 saniyede otomatik güncelleme</p>
        <p>Sinyal eşiği: %60 güven gerekli · Kelly pozisyon boyutlandırması aktif</p>
      </div>
    </div>
  )
}
