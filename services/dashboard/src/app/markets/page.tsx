'use client'
import { useEffect, useState, useMemo } from 'react'

interface Market {
  symbol: string
  rsi_14?: number; rsi_7?: number; macd_hist?: number; bb_position?: number
  adx?: number; stoch_k?: number; volume_ratio?: number; ob_imbalance_1?: number
  drift_status?: string; regime?: string
  // from signal
  direction?: string; confidence?: number; kelly_fraction?: number; crisis_level?: number
  // crypto-specific (from CryptoFeatureBuilder, stored in features:latest:*)
  funding_rate?: number   // funding * 1000, clipped ±5 → display: /10 → actual %
  oi_change_1h?: number   // oi_change_pct/20 → display: *20 → actual %
  ls_ratio_z?: number     // log(ls_ratio)/2 → >0 long-biased, <0 short-biased
  fear_greed_norm?: number // 0–1 → display: *100
  funding_regime?: number  // 1=longs paying, -1=shorts paying, 0=neutral
  vix_level?: number       // 0–1 normalized
}

type SortKey = 'rsi_14' | 'confidence' | 'volume_ratio' | 'adx' | 'funding_rate'

const DRIFT_COLOR: Record<string, string> = {
  STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500',
}
const DIR_STYLE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-800/50',
  short: 'text-red-400 bg-red-900/30 border border-red-800/50',
  flat: 'text-gray-500 bg-gray-800/60 border border-gray-700/40',
}
const REGIME_COLOR: Record<string, string> = {
  trending_up: 'text-green-400', trending_down: 'text-red-400',
  ranging: 'text-blue-400', volatile: 'text-yellow-400',
}

function rsiColor(rsi: number) {
  if (rsi < 30) return 'text-blue-400'
  if (rsi < 45) return 'text-green-400'
  if (rsi < 55) return 'text-gray-400'
  if (rsi < 70) return 'text-orange-400'
  return 'text-red-400'
}

function rsiBg(rsi: number) {
  if (rsi < 30) return 'bg-blue-500'
  if (rsi < 45) return 'bg-green-500'
  if (rsi < 55) return 'bg-gray-500'
  if (rsi < 70) return 'bg-orange-500'
  return 'bg-red-500'
}

function RSIBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value ?? 50))
  return (
    <div className="flex items-center gap-1.5 min-w-[90px]">
      <div className="w-14 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${rsiBg(value)}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-mono tabular-nums ${rsiColor(value)}`}>{value?.toFixed(1)}</span>
    </div>
  )
}

function SortBtn({ label, active, desc, onClick }: { label: string; active: boolean; desc: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`px-2.5 py-1 text-xs rounded transition-colors flex items-center gap-1 ${active
        ? 'bg-orange-500/15 text-orange-400 border border-orange-500/40'
        : 'bg-gray-800/80 text-gray-400 hover:text-white border border-transparent'}`}>
      {label}{active && <span className="text-[10px]">{desc ? '↓' : '↑'}</span>}
    </button>
  )
}

function FundingBadge({ raw }: { raw: number }) {
  // raw = funding * 1000; actual % = raw / 10
  const pct = raw / 10
  const color = pct > 0.05 ? 'text-red-400' : pct > 0 ? 'text-orange-400' : pct < -0.05 ? 'text-blue-400' : 'text-green-400'
  const sign = pct >= 0 ? '+' : ''
  return <span className={`font-mono tabular-nums text-xs ${color}`}>{sign}{pct.toFixed(4)}%</span>
}

function FearGreedBadge({ norm }: { norm: number }) {
  const val = Math.round(norm * 100)
  const color = val >= 80 ? 'text-red-400' : val >= 60 ? 'text-orange-400' : val >= 40 ? 'text-gray-400' : val >= 20 ? 'text-green-400' : 'text-blue-400'
  const label = val >= 80 ? 'Greed' : val >= 60 ? 'Fomo' : val >= 40 ? 'Neutral' : val >= 20 ? 'Fear' : 'Panic'
  return <span className={`font-mono tabular-nums text-xs ${color}`}>{val} <span className="text-gray-600">{label}</span></span>
}

function LSBadge({ z }: { z: number }) {
  const pct = Math.round(z * 100)
  const color = z > 0.3 ? 'text-green-400' : z < -0.3 ? 'text-red-400' : 'text-gray-400'
  const label = z > 0.2 ? 'Long' : z < -0.2 ? 'Short' : 'Neut'
  return <span className={`font-mono tabular-nums text-xs ${color}`}>{pct > 0 ? '+' : ''}{pct} <span className="text-gray-600 text-[10px]">{label}</span></span>
}

const PAGE_SIZE = 50

export default function MarketsPage() {
  const [markets, setMarkets] = useState<Market[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('confidence')
  const [sortDesc, setSortDesc] = useState(true)
  const [showCrypto, setShowCrypto] = useState(false)
  const [lastUpdate, setLastUpdate] = useState('')
  const [page, setPage] = useState(0)

  const fetchData = async () => {
    try {
      const data = await fetch('/api/markets').then(r => r.json())
      setMarkets(Array.isArray(data) ? data : [])
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 10000); return () => clearInterval(t) }, [])

  const filtered = useMemo(() => {
    const q = search.toUpperCase()
    return markets
      .filter(m => m.symbol?.includes(q))
      .sort((a, b) => {
        const av = typeof a[sortKey] === 'number' ? (a[sortKey] as number) : 0
        const bv = typeof b[sortKey] === 'number' ? (b[sortKey] as number) : 0
        return sortDesc ? bv - av : av - bv
      })
  }, [markets, search, sortKey, sortDesc])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paged = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDesc(d => !d)
    else { setSortKey(key); setSortDesc(true) }
    setPage(0)
  }

  // Reset page when search changes
  const handleSearch = (v: string) => { setSearch(v); setPage(0) }

  const longCount = markets.filter(m => m.direction === 'long').length
  const shortCount = markets.filter(m => m.direction === 'short').length
  const hasCrypto = markets.some(m => m.funding_rate != null)

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-blue-400">◌</span>
      <span className="text-sm">Loading markets...</span>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">
            Markets <span className="text-gray-500 text-sm font-normal">({filtered.length} / {markets.length})</span>
          </h1>
          <p className="text-gray-500 text-xs mt-0.5">Live feature data for all tracked symbols · 10s refresh</p>
        </div>
        <div className="flex items-center gap-4 text-xs shrink-0">
          <span className="text-green-400 font-semibold">▲ {longCount} long</span>
          <span className="text-red-400 font-semibold">▼ {shortCount} short</span>
          <span className="text-gray-600">{lastUpdate ? `${lastUpdate}` : ''}</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <input
          value={search} onChange={e => handleSearch(e.target.value)}
          placeholder="Filter symbol..."
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-orange-500 w-44 transition-colors"
        />
        <div className="flex items-center gap-1.5">
          <span className="text-gray-600 text-xs">Sort:</span>
          {([
            { key: 'confidence', label: 'Confidence' },
            { key: 'rsi_14', label: 'RSI' },
            { key: 'volume_ratio', label: 'Volume' },
            { key: 'adx', label: 'ADX' },
            ...(showCrypto ? [{ key: 'funding_rate' as SortKey, label: 'Funding' }] : []),
          ] as { key: SortKey; label: string }[]).map(({ key, label }) => (
            <SortBtn key={key} label={label} active={sortKey === key} desc={sortDesc} onClick={() => toggleSort(key)} />
          ))}
        </div>
        {hasCrypto && (
          <button
            onClick={() => setShowCrypto(v => !v)}
            className={`ml-auto px-2.5 py-1 text-xs rounded border transition-colors ${showCrypto
              ? 'bg-purple-500/15 text-purple-400 border-purple-500/40'
              : 'bg-gray-800/80 text-gray-400 border-transparent hover:text-white'}`}>
            {showCrypto ? '⊗ Hide Crypto' : '⊕ Crypto Cols'}
          </button>
        )}
      </div>

      {showCrypto && (
        <div className="bg-gray-900/60 border border-gray-800/60 rounded-lg px-4 py-2.5 flex flex-wrap gap-4 text-xs text-gray-500">
          <span><span className="text-purple-400 font-semibold">Funding</span> — 8h perpetual funding rate (+ = longs pay shorts)</span>
          <span><span className="text-blue-400 font-semibold">OI 1h</span> — open interest change % in last hour</span>
          <span><span className="text-orange-400 font-semibold">L/S</span> — long/short position ratio (z-score; +ve = long-biased)</span>
          <span><span className="text-yellow-400 font-semibold">Fear/Greed</span> — 0 (panic) → 100 (extreme greed)</span>
        </div>
      )}

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-xs" style={{ minWidth: showCrypto ? '1180px' : '900px' }}>
          <thead>
            <tr className="text-gray-500 border-b border-gray-800 bg-gray-900/80">
              <th className="text-left px-3 py-2.5 sticky left-0 bg-gray-900/90 font-medium">Symbol</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">Direction</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">Confidence</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">RSI-14</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">RSI-7</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">MACD Hist</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">BB Pos</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">ADX</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">Vol Ratio</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">OB Imbal</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">Drift</th>
              <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium">Regime</th>
              {showCrypto && <>
                <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium text-purple-400">Funding</th>
                <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium text-blue-400">OI 1h</th>
                <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium text-orange-400">L/S</th>
                <th className="text-left px-3 py-2.5 whitespace-nowrap font-medium text-yellow-400">F&G</th>
              </>}
            </tr>
          </thead>
          <tbody>
            {paged.length === 0 && (
              <tr><td colSpan={showCrypto ? 16 : 12} className="text-center text-gray-500 py-8">No markets match your filter</td></tr>
            )}
            {paged.map(m => {
              const dir = m.direction ?? 'flat'
              const conf = (m.confidence ?? 0) * 100
              return (
                <tr key={m.symbol} className="border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors">
                  <td className="px-3 py-2 font-bold text-white whitespace-nowrap sticky left-0 bg-gray-950/90">
                    <a href={`/coin/${m.symbol}`} className="hover:text-orange-400 transition-colors">{m.symbol}</a>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`px-1.5 py-0.5 rounded font-bold text-xs ${DIR_STYLE[dir]}`}>
                      {dir === 'long' ? '▲ LONG' : dir === 'short' ? '▼ SHORT' : '— FLAT'}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5 min-w-[80px]">
                      <div className="w-12 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${conf >= 70 ? 'bg-green-500' : conf >= 60 ? 'bg-orange-500' : 'bg-gray-600'}`}
                          style={{ width: `${conf}%` }} />
                      </div>
                      <span className={`tabular-nums font-mono ${conf >= 70 ? 'text-green-400' : conf >= 60 ? 'text-orange-400' : 'text-gray-500'}`}>{Math.round(conf)}%</span>
                    </div>
                  </td>
                  <td className="px-3 py-2"><RSIBar value={m.rsi_14 ?? 50} /></td>
                  <td className={`px-3 py-2 font-mono tabular-nums ${rsiColor(m.rsi_7 ?? 50)}`}>{m.rsi_7?.toFixed(1) ?? '—'}</td>
                  <td className={`px-3 py-2 font-mono tabular-nums ${(m.macd_hist ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {m.macd_hist != null ? m.macd_hist.toFixed(4) : '—'}
                  </td>
                  <td className="px-3 py-2 text-gray-300 tabular-nums">
                    {m.bb_position != null ? `${((m.bb_position) * 100).toFixed(0)}%` : '—'}
                  </td>
                  <td className={`px-3 py-2 tabular-nums ${(m.adx ?? 0) > 25 ? 'text-orange-400 font-semibold' : 'text-gray-400'}`}>
                    {m.adx?.toFixed(1) ?? '—'}
                  </td>
                  <td className={`px-3 py-2 tabular-nums ${(m.volume_ratio ?? 1) > 1.5 ? 'text-orange-400 font-semibold' : 'text-gray-400'}`}>
                    {m.volume_ratio != null ? `${m.volume_ratio.toFixed(2)}×` : '—'}
                  </td>
                  <td className={`px-3 py-2 tabular-nums ${(m.ob_imbalance_1 ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {m.ob_imbalance_1 != null ? `${((m.ob_imbalance_1) * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className={`px-3 py-2 font-semibold ${DRIFT_COLOR[m.drift_status ?? ''] ?? 'text-gray-500'}`}>
                    {m.drift_status ?? '—'}
                  </td>
                  <td className={`px-3 py-2 ${REGIME_COLOR[m.regime ?? ''] ?? 'text-gray-400'}`}>
                    {m.regime ?? '—'}
                  </td>
                  {showCrypto && <>
                    <td className="px-3 py-2">
                      {m.funding_rate != null ? <FundingBadge raw={m.funding_rate} /> : <span className="text-gray-700">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      {m.oi_change_1h != null
                        ? <span className={`font-mono tabular-nums text-xs ${(m.oi_change_1h * 20) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {(m.oi_change_1h * 20) > 0 ? '+' : ''}{(m.oi_change_1h * 20).toFixed(1)}%
                          </span>
                        : <span className="text-gray-700">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      {m.ls_ratio_z != null ? <LSBadge z={m.ls_ratio_z} /> : <span className="text-gray-700">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      {m.fear_greed_norm != null ? <FearGreedBadge norm={m.fear_greed_norm} /> : <span className="text-gray-700">—</span>}
                    </td>
                  </>}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">{filtered.length} coin · sayfa {page + 1}/{totalPages}</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(0)} disabled={page === 0}
              className="px-2 py-1 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">«</button>
            <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
              className="px-2 py-1 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">‹</button>
            {Array.from({ length: Math.min(7, totalPages) }, (_, i) => {
              const p = Math.max(0, Math.min(totalPages - 7, page - 3)) + i
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={`px-2 py-1 rounded text-xs ${p === page ? 'bg-orange-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
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

      <div className="flex flex-wrap gap-4 text-xs text-gray-600">
        <span>RSI: <span className="text-blue-400">◼</span> &lt;30 oversold · <span className="text-green-400">◼</span> 30–45 · <span className="text-gray-400">◼</span> 45–55 · <span className="text-orange-400">◼</span> 55–70 · <span className="text-red-400">◼</span> &gt;70 overbought</span>
        <span>ADX &gt;25 = trending (orange). Vol Ratio &gt;1.5× = unusual volume spike.</span>
      </div>
    </div>
  )
}
