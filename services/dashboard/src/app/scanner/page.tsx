'use client'
import { useEffect, useRef, useState } from 'react'

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

export default function ScannerPage() {
  const [data, setData] = useState<Partial<ScannerData>>({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterDir, setFilterDir] = useState<'all' | 'long' | 'short' | 'active'>('all')
  const [tick, setTick] = useState(0)          // forces timeAgo re-render
  const [lastUpdate, setLastUpdate] = useState('')
  const [scanCount, setScanCount] = useState(0) // how many refreshes done
  const intervalRef = useRef<ReturnType<typeof setInterval>>()

  const fetchData = async () => {
    try {
      const res = await fetch('/api/scanner')
      const json = await res.json()
      setData(json)
      setLastUpdate(new Date().toLocaleTimeString())
      setScanCount(n => n + 1)
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 5000)
    // Re-render timeAgo every 10s without re-fetching
    const tickTimer = setInterval(() => setTick(t => t + 1), 10000)
    return () => {
      clearInterval(intervalRef.current)
      clearInterval(tickTimer)
    }
  }, [])

  const coins = (data.coins ?? []).filter(c => {
    if (search && !c.symbol.toLowerCase().includes(search.toLowerCase())) return false
    if (filterDir === 'long') return c.direction === 'long'
    if (filterDir === 'short') return c.direction === 'short'
    if (filterDir === 'active') return c.direction !== 'flat'
    return true
  })

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
          { label: 'Tarama Sayısı', value: String(scanCount), color: 'text-purple-400', sub: 'bu oturum' },
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
        <span className="ml-auto text-xs text-gray-600">{coins.length} sonuç</span>
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
              {coins.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-gray-500">
                    {data.total === 0
                      ? 'Henüz tarama verisi yok — feature_engine başlatılıyor...'
                      : 'Filtreyle eşleşen coin bulunamadı'}
                  </td>
                </tr>
              ) : coins.map(c => (
                <tr key={c.symbol}
                  className={`border-b border-gray-800/40 hover:bg-gray-800/25 transition-colors ${
                    c.direction === 'long' ? 'bg-green-950/10' :
                    c.direction === 'short' ? 'bg-red-950/10' : ''
                  }`}>
                  <td className="px-4 py-2.5">
                    <span className="font-bold text-white text-sm">{c.symbol.replace('USDT','')}</span>
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

      {/* Footer note */}
      <div className="text-center text-xs text-gray-700 pb-2 space-y-0.5">
        <p>⚡ Prometheus · {data.total ?? 0} coin izleniyor · Her 5 saniyede otomatik güncelleme</p>
        <p>Sinyal eşiği: %60 güven gerekli · Kelly pozisyon boyutlandırması aktif</p>
      </div>
    </div>
  )
}
