'use client'
import { useEffect, useState, useMemo } from 'react'

interface Market {
  symbol: string; rsi_14: number; rsi_7: number; macd_hist: number; bb_position: number
  adx: number; stoch_k: number; volume_ratio: number; ob_imbalance_1: number
  drift_status: string; direction: string; confidence: number; regime: string
}

type SortKey = 'rsi_14' | 'confidence' | 'volume_ratio' | 'adx'

const DRIFT_COLOR: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-400' }
const DIR_STYLE: Record<string, string> = { long: 'text-green-400 bg-green-900/30', short: 'text-red-400 bg-red-900/30', flat: 'text-gray-400 bg-gray-800' }
const REGIME_COLOR: Record<string, string> = { trending_up: 'text-green-400', trending_down: 'text-red-400', ranging: 'text-blue-400', volatile: 'text-yellow-400' }

function rsiStyle(rsi: number): string {
  if (rsi < 30) return 'text-blue-400'
  if (rsi < 45) return 'text-green-400'
  if (rsi < 55) return 'text-gray-400'
  if (rsi < 70) return 'text-orange-400'
  return 'text-red-400'
}

function RSIBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value))
  const bg = value < 30 ? 'bg-blue-500' : value < 45 ? 'bg-green-500' : value < 55 ? 'bg-gray-500' : value < 70 ? 'bg-orange-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-14 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${bg}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-mono ${rsiStyle(value)}`}>{value?.toFixed(1)}</span>
    </div>
  )
}

function SortBtn({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={`px-2 py-1 text-xs rounded ${active ? 'bg-orange-500/20 text-orange-400 border border-orange-500/40' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
      {label}
    </button>
  )
}

export default function MarketsPage() {
  const [markets, setMarkets] = useState<Market[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('confidence')
  const [sortDesc, setSortDesc] = useState(true)

  const fetchData = async () => {
    try {
      const data = await fetch('/api/markets').then(r => r.json())
      setMarkets(Array.isArray(data) ? data : [])
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

  if (loading) return <div className="text-gray-400 text-center mt-20 text-sm">Loading markets...</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-white font-bold text-lg">Markets <span className="text-gray-500 text-sm font-normal">({filtered.length} symbols)</span></h1>
        <div className="text-xs text-gray-500">Auto-refresh 10s</div>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <input
          value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search symbol..."
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-orange-500 w-44"
        />
        <span className="text-gray-500 text-xs">Sort:</span>
        {(['rsi_14', 'confidence', 'volume_ratio', 'adx'] as SortKey[]).map(k => (
          <SortBtn key={k} label={k === 'rsi_14' ? 'RSI' : k === 'volume_ratio' ? 'Volume' : k.toUpperCase()} active={sortKey === k} onClick={() => toggleSort(k)} />
        ))}
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800 bg-gray-900/80">
              {['Symbol', 'RSI-14', 'MACD', 'BB Pos', 'ADX', 'Stoch', 'Vol Ratio', 'OB Imbal', 'Direction', 'Confidence', 'Drift', 'Regime'].map(h => (
                <th key={h} className="text-left px-3 py-2 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(m => (
              <tr key={m.symbol} className="border-b border-gray-800/40 hover:bg-gray-800/30">
                <td className="px-3 py-2 font-semibold text-white whitespace-nowrap">{m.symbol}</td>
                <td className="px-3 py-2"><RSIBar value={m.rsi_14} /></td>
                <td className={`px-3 py-2 font-mono ${(m.macd_hist ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>{m.macd_hist?.toFixed(4)}</td>
                <td className="px-3 py-2 text-gray-300">{(m.bb_position * 100)?.toFixed(0)}%</td>
                <td className={`px-3 py-2 ${(m.adx ?? 0) > 25 ? 'text-orange-400' : 'text-gray-400'}`}>{m.adx?.toFixed(1)}</td>
                <td className={`px-3 py-2 ${(m.stoch_k ?? 50) < 20 ? 'text-blue-400' : (m.stoch_k ?? 50) > 80 ? 'text-red-400' : 'text-gray-300'}`}>{m.stoch_k?.toFixed(1)}</td>
                <td className={`px-3 py-2 ${(m.volume_ratio ?? 1) > 1.5 ? 'text-orange-400' : 'text-gray-300'}`}>{m.volume_ratio?.toFixed(2)}x</td>
                <td className={`px-3 py-2 ${(m.ob_imbalance_1 ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>{((m.ob_imbalance_1 ?? 0) * 100).toFixed(1)}%</td>
                <td className="px-3 py-2"><span className={`px-1.5 py-0.5 rounded text-xs font-bold ${DIR_STYLE[m.direction]}`}>{m.direction?.toUpperCase()}</span></td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <div className="w-12 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full bg-orange-500 rounded-full" style={{ width: `${Math.round((m.confidence ?? 0) * 100)}%` }} />
                    </div>
                    <span className="text-gray-300">{Math.round((m.confidence ?? 0) * 100)}%</span>
                  </div>
                </td>
                <td className={`px-3 py-2 ${DRIFT_COLOR[m.drift_status] || 'text-gray-400'}`}>{m.drift_status}</td>
                <td className={`px-3 py-2 ${REGIME_COLOR[m.regime] || 'text-gray-400'}`}>{m.regime}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
