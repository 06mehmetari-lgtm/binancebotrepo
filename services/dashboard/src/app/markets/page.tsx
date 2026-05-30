'use client'
import { useEffect, useState, useMemo } from 'react'

interface Market {
  symbol: string; rsi_14: number; rsi_7: number; macd_hist: number; bb_position: number
  adx: number; stoch_k: number; volume_ratio: number; ob_imbalance_1: number
  drift_status: string; direction: string; confidence: number; regime: string
}

type SortKey = 'rsi_14' | 'confidence' | 'volume_ratio' | 'adx'

const DRIFT_COLOR: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500' }
const DIR_STYLE: Record<string, string> = { long: 'text-green-400 bg-green-900/30 border border-green-800/50', short: 'text-red-400 bg-red-900/30 border border-red-800/50', flat: 'text-gray-500 bg-gray-800/60 border border-gray-700/40' }
const REGIME_COLOR: Record<string, string> = { trending_up: 'text-green-400', trending_down: 'text-red-400', ranging: 'text-blue-400', volatile: 'text-yellow-400' }

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
    <button onClick={onClick} className={`px-2.5 py-1 text-xs rounded transition-colors flex items-center gap-1 ${active ? 'bg-orange-500/15 text-orange-400 border border-orange-500/40' : 'bg-gray-800/80 text-gray-400 hover:text-white border border-transparent'}`}>
      {label}
      {active && <span className="text-[10px]">{desc ? '↓' : '↑'}</span>}
    </button>
  )
}

export default function MarketsPage() {
  const [markets, setMarkets] = useState<Market[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('confidence')
  const [sortDesc, setSortDesc] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = async () => {
    try {
      const data = await fetch('/api/markets').then(r => r.json())
      setMarkets(Array.isArray(data) ? data : [])
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { /* retry */ } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 10000); return () => clearInterval(t) }, [])

  const filtered = useMemo(() => {
    const q = search.toUpperCase()
    return markets
      .filter(m => m.symbol.includes(q))
      .sort((a, b) => {
        const diff = (a[sortKey] ?? 0) - (b[sortKey] ?? 0)
        return sortDesc ? -diff : diff
      })
  }, [markets, search, sortKey, sortDesc])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDesc(d => !d)
    else { setSortKey(key); setSortDesc(true) }
  }

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-blue-400">◌</span>
      <span className="text-sm">Loading markets...</span>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-white font-bold text-base">
          Markets <span className="text-gray-500 text-sm font-normal">({filtered.length} / {markets.length})</span>
        </h1>
        <span className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate}` : ''} · 10s refresh</span>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <input
          value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Filter symbol..."
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-orange-500 w-44 transition-colors"
        />
        <div className="flex items-center gap-1.5">
          <span className="text-gray-600 text-xs">Sort by:</span>
          {(['rsi_14', 'confidence', 'volume_ratio', 'adx'] as SortKey[]).map(k => (
            <SortBtn key={k} label={k === 'rsi_14' ? 'RSI' : k === 'volume_ratio' ? 'Volume' : k.toUpperCase()} active={sortKey === k} desc={sortDesc} onClick={() => toggleSort(k)} />
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-gray-600">
          <span className="text-blue-400">◼ &lt;30</span>
          <span className="text-green-400">◼ 30-45</span>
          <span className="text-gray-400">◼ 45-55</span>
          <span className="text-orange-400">◼ 55-70</span>
          <span className="text-red-400">◼ &gt;70</span>
        </div>
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-xs min-w-[900px]">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800 bg-gray-900/80 sticky top-0">
              {['Symbol', 'RSI-14', 'RSI-7', 'MACD Hist', 'BB Pos', 'ADX', 'Stoch K', 'Vol Ratio', 'OB Imbal', 'Direction', 'Confidence', 'Drift', 'Regime'].map(h => (
                <th key={h} className="text-left px-3 py-2.5 whitespace-nowrap font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={13} className="text-center text-gray-500 py-8">No markets match your filter</td></tr>
            )}
            {filtered.map(m => (
              <tr key={m.symbol} className="border-b border-gray-800/40 hover:bg-gray-800/25 transition-colors">
                <td className="px-3 py-2 font-bold text-white whitespace-nowrap">{m.symbol}</td>
                <td className="px-3 py-2"><RSIBar value={m.rsi_14} /></td>
                <td className={`px-3 py-2 font-mono tabular-nums ${rsiColor(m.rsi_7)}`}>{m.rsi_7?.toFixed(1)}</td>
                <td className={`px-3 py-2 font-mono tabular-nums ${(m.macd_hist ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>{m.macd_hist?.toFixed(4)}</td>
                <td className="px-3 py-2 text-gray-300 tabular-nums">{((m.bb_position ?? 0) * 100).toFixed(0)}%</td>
                <td className={`px-3 py-2 tabular-nums ${(m.adx ?? 0) > 25 ? 'text-orange-400 font-semibold' : 'text-gray-400'}`}>{m.adx?.toFixed(1)}</td>
                <td className={`px-3 py-2 tabular-nums ${(m.stoch_k ?? 50) < 20 ? 'text-blue-400' : (m.stoch_k ?? 50) > 80 ? 'text-red-400' : 'text-gray-300'}`}>{m.stoch_k?.toFixed(1)}</td>
                <td className={`px-3 py-2 tabular-nums ${(m.volume_ratio ?? 1) > 1.5 ? 'text-orange-400 font-semibold' : 'text-gray-400'}`}>{m.volume_ratio?.toFixed(2)}x</td>
                <td className={`px-3 py-2 tabular-nums ${(m.ob_imbalance_1 ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>{((m.ob_imbalance_1 ?? 0) * 100).toFixed(1)}%</td>
                <td className="px-3 py-2"><span className={`px-1.5 py-0.5 rounded font-bold ${DIR_STYLE[m.direction]}`}>{m.direction?.toUpperCase()}</span></td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <div className="w-12 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full bg-orange-500 rounded-full" style={{ width: `${Math.round((m.confidence ?? 0) * 100)}%` }} />
                    </div>
                    <span className="text-gray-300 tabular-nums">{Math.round((m.confidence ?? 0) * 100)}%</span>
                  </div>
                </td>
                <td className={`px-3 py-2 font-semibold ${DRIFT_COLOR[m.drift_status] ?? 'text-gray-400'}`}>{m.drift_status}</td>
                <td className={`px-3 py-2 ${REGIME_COLOR[m.regime] ?? 'text-gray-400'}`}>{m.regime}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
