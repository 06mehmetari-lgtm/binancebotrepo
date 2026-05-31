'use client'
import { useEffect, useState } from 'react'

interface Position {
  symbol: string; direction: string; size_usd: number
  entry_price: number; current_price: number | null
  entry_time: number; unrealized_pct: number; unrealized_usdt: number
  age_hours: number; entry_signal?: { confidence: number; regime: string; drift_status: string }
}

interface Trade {
  symbol: string; direction: string; entry_price: number; exit_price: number
  pnl_pct: number; pnl_usdt: number; size_usd: number; closed_at: number
}

interface PositionData {
  positions: Position[]
  daily_pnl: number
  trade_history: Trade[]
  position_count: number
}

const DIR_STYLE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-800/50',
  short: 'text-red-400 bg-red-900/30 border border-red-800/50',
}

function fmtPrice(p: number | null) {
  if (!p) return '—'
  if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (p >= 1) return p.toFixed(4)
  return p.toFixed(6)
}

function timeAgo(ts: number) {
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function PnLBar({ pct }: { pct: number }) {
  const abs = Math.min(Math.abs(pct), 10)
  const width = (abs / 10) * 100
  const color = pct >= 0 ? 'bg-green-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${width}%` }} />
      </div>
      <span className={`text-xs font-mono tabular-nums font-bold ${pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
        {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
      </span>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center space-y-3">
      <div className="text-4xl">📭</div>
      <p className="text-white font-semibold">No Open Positions</p>
      <p className="text-gray-500 text-sm max-w-sm mx-auto">
        The OMS is in Paper/DRY_RUN mode. Positions open when the signal engine generates valid signals
        with confidence ≥ 60% that pass immunity system checks.
      </p>
      <div className="flex flex-wrap justify-center gap-2 mt-4 text-xs text-gray-600">
        <span className="bg-gray-800 px-2 py-1 rounded">Min confidence: 60%</span>
        <span className="bg-gray-800 px-2 py-1 rounded">Max 3 concurrent positions</span>
        <span className="bg-gray-800 px-2 py-1 rounded">Max size: 5% portfolio</span>
      </div>
    </div>
  )
}

export default function PositionsPage() {
  const [data, setData] = useState<PositionData | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = async () => {
    try {
      const res = await fetch('/api/positions')
      if (res.ok) {
        setData(await res.json())
        setLastUpdate(new Date().toLocaleTimeString())
      }
    } catch { /* retry */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 5000)
    return () => clearInterval(t)
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400">⚡</span>
      <span>Loading positions...</span>
    </div>
  )

  const { positions = [], daily_pnl = 0, trade_history = [] } = data ?? {}
  const totalUnrealized = positions.reduce((s, p) => s + p.unrealized_usdt, 0)
  const totalExposed = positions.reduce((s, p) => s + p.size_usd, 0)
  const winTrades = trade_history.filter(t => t.pnl_pct > 0).length
  const winRate = trade_history.length > 0 ? (winTrades / trade_history.length * 100) : 0

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-white font-bold text-base">Portfolio — Paper Trading</h1>
          <p className="text-gray-500 text-xs mt-0.5">OMS positions · DRY_RUN mode · 5s refresh</p>
        </div>
        <span className="text-xs text-gray-600">{lastUpdate}</span>
      </div>

      {/* ── Summary stats ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Open Positions</p>
          <p className={`text-2xl font-black ${positions.length > 0 ? 'text-white' : 'text-gray-600'}`}>
            {positions.length} <span className="text-sm font-normal text-gray-500">/ 3 max</span>
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Unrealized P&L</p>
          <p className={`text-2xl font-black ${totalUnrealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {totalUnrealized >= 0 ? '+' : ''}${totalUnrealized.toFixed(2)}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Daily Realized P&L</p>
          <p className={`text-2xl font-black ${daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {daily_pnl >= 0 ? '+' : ''}${daily_pnl.toFixed(2)}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Today's Win Rate</p>
          <p className={`text-2xl font-black ${winRate >= 52 ? 'text-green-400' : winRate > 0 ? 'text-yellow-400' : 'text-gray-600'}`}>
            {trade_history.length > 0 ? `${winRate.toFixed(0)}%` : '—'}
          </p>
          <p className="text-xs text-gray-600">{winTrades}/{trade_history.length} trades</p>
        </div>
      </div>

      {/* ── Exposure bar ── */}
      {totalExposed > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex justify-between text-xs text-gray-400">
            <span>Capital Exposed</span>
            <span>${totalExposed.toFixed(0)} / $10,000 portfolio (max $500)</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-orange-500 rounded-full transition-all"
              style={{ width: `${Math.min(totalExposed / 500 * 100, 100)}%` }}
            />
          </div>
          <p className="text-xs text-gray-600">{(totalExposed / 10000 * 100).toFixed(2)}% of portfolio · Max 5% per position</p>
        </div>
      )}

      {/* ── Open Positions ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">⚡ Open Positions</h2>
          <span className="text-xs text-gray-600">{positions.length} active</span>
        </div>

        {positions.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5">Direction</th>
                  <th className="text-left px-4 py-2.5">Entry</th>
                  <th className="text-left px-4 py-2.5">Current</th>
                  <th className="text-left px-4 py-2.5">Size</th>
                  <th className="text-left px-4 py-2.5">Unrealized P&L</th>
                  <th className="text-left px-4 py-2.5">Unrealized $</th>
                  <th className="text-left px-4 py-2.5">Age</th>
                  <th className="text-left px-4 py-2.5">Confidence</th>
                  <th className="text-left px-4 py-2.5">Regime</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => (
                  <tr key={pos.symbol}
                    className={`border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors cursor-pointer ${
                      pos.unrealized_pct > 0.5 ? 'bg-green-950/10' :
                      pos.unrealized_pct < -0.5 ? 'bg-red-950/10' : ''
                    }`}
                    onClick={() => window.location.href = `/coin/${pos.symbol}`}>
                    <td className="px-4 py-3 font-bold text-white hover:text-orange-400 transition-colors">
                      {pos.symbol}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-bold border ${DIR_STYLE[pos.direction] ?? ''}`}>
                        {pos.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-300">{fmtPrice(pos.entry_price)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-white">{fmtPrice(pos.current_price)}</td>
                    <td className="px-4 py-3 text-xs text-gray-300">${pos.size_usd.toFixed(0)}</td>
                    <td className="px-4 py-3"><PnLBar pct={pos.unrealized_pct} /></td>
                    <td className={`px-4 py-3 font-mono text-xs font-bold ${pos.unrealized_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pos.unrealized_usdt >= 0 ? '+' : ''}${pos.unrealized_usdt.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {pos.age_hours < 1 ? `${Math.round(pos.age_hours * 60)}m` : `${pos.age_hours.toFixed(1)}h`}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {pos.entry_signal ? `${Math.round(pos.entry_signal.confidence * 100)}%` : '—'}
                    </td>
                    <td className={`px-4 py-3 text-xs ${
                      pos.entry_signal?.regime === 'trending_up' ? 'text-green-400' :
                      pos.entry_signal?.regime === 'trending_down' ? 'text-red-400' :
                      pos.entry_signal?.regime === 'volatile' ? 'text-yellow-400' : 'text-blue-400'
                    }`}>
                      {pos.entry_signal?.regime ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Recent Trade History ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">📋 Recent Trades</h2>
          <span className="text-xs text-gray-600">Last {trade_history.length} closed trades</span>
        </div>

        {trade_history.length === 0 ? (
          <p className="text-gray-500 text-sm p-6 text-center">No closed trades yet — waiting for positions to close</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5">Direction</th>
                  <th className="text-left px-4 py-2.5">Entry</th>
                  <th className="text-left px-4 py-2.5">Exit</th>
                  <th className="text-left px-4 py-2.5">Size</th>
                  <th className="text-left px-4 py-2.5">P&L %</th>
                  <th className="text-left px-4 py-2.5">P&L $</th>
                  <th className="text-left px-4 py-2.5">Closed</th>
                </tr>
              </thead>
              <tbody>
                {trade_history.map((trade, i) => (
                  <tr key={i}
                    className="border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors cursor-pointer"
                    onClick={() => window.location.href = `/coin/${trade.symbol}`}>
                    <td className="px-4 py-2.5 font-bold text-white hover:text-orange-400 transition-colors">
                      {trade.symbol}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs px-1.5 py-0.5 rounded font-bold border ${DIR_STYLE[trade.direction] ?? 'text-gray-400'}`}>
                        {trade.direction === 'long' ? '▲' : '▼'} {trade.direction?.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-400">{fmtPrice(trade.entry_price)}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-300">{fmtPrice(trade.exit_price)}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-400">${trade.size_usd?.toFixed(0) ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`font-mono text-xs font-bold ${trade.pnl_pct > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {trade.pnl_pct > 0 ? '+' : ''}{(trade.pnl_pct * 100).toFixed(2)}%
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 font-mono text-xs font-bold ${trade.pnl_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {trade.pnl_usdt >= 0 ? '+' : ''}${trade.pnl_usdt?.toFixed(2) ?? '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">
                      {trade.closed_at ? timeAgo(trade.closed_at) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
