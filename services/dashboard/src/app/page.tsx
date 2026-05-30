'use client'
import { useEffect, useState } from 'react'

interface Market { symbol: string; rsi_14: number; direction: string; confidence: number; regime: string; crisis_level: number; kelly_fraction: number; drift_status: string }
interface Signal { symbol: string; direction: string; confidence: number; regime: string; crisis_level: number; drift_status: string; kelly_fraction: number }
interface Shadow { shadow_id: string; sharpe: number; win_rate: number; trades: number; return: number; promotion_ready: boolean; max_drawdown: number }
interface Status { active_symbol_count: number; total_signals: number; avg_confidence: number; best_genome_fitness: number; fear_greed: { value: number; classification: string }; macro_vix: number; 'ws:status': { status: string } }

const DRIFT_COLOR: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-400' }
const DIR_STYLE: Record<string, string> = { long: 'text-green-400 bg-green-900/30', short: 'text-red-400 bg-red-900/30', flat: 'text-gray-400 bg-gray-800' }
const REGIME_COLOR: Record<string, string> = { trending_up: 'text-green-400', trending_down: 'text-red-400', ranging: 'text-blue-400', volatile: 'text-yellow-400' }
const CRISIS_COLOR = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-400 animate-pulse']

function rsiTileColor(rsi: number) {
  if (rsi < 30) return 'bg-blue-900/60 border-blue-700'
  if (rsi < 45) return 'bg-green-900/50 border-green-800'
  if (rsi < 55) return 'bg-gray-800 border-gray-700'
  if (rsi < 70) return 'bg-orange-900/50 border-orange-800'
  return 'bg-red-900/60 border-red-700'
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  )
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'bg-green-500' : pct >= 65 ? 'bg-orange-500' : 'bg-yellow-600'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-300">{pct}%</span>
    </div>
  )
}

export default function Home() {
  const [markets, setMarkets] = useState<Market[]>([])
  const [signals, setSignals] = useState<Signal[]>([])
  const [shadow, setShadow] = useState<Shadow[]>([])
  const [status, setStatus] = useState<Partial<Status>>({})
  const [loading, setLoading] = useState(true)

  const fetchAll = async () => {
    try {
      const [m, s, sh, st] = await Promise.all([
        fetch('/api/markets').then(r => r.json()),
        fetch('/api/signals').then(r => r.json()),
        fetch('/api/shadow').then(r => r.json()),
        fetch('/api/status').then(r => r.json()),
      ])
      setMarkets(Array.isArray(m) ? m : [])
      setSignals(Array.isArray(s) ? s : [])
      setShadow(Array.isArray(sh) ? sh : [])
      setStatus(st || {})
    } catch { /* retry */ } finally { setLoading(false) }
  }

  useEffect(() => { fetchAll(); const t = setInterval(fetchAll, 5000); return () => clearInterval(t) }, [])

  if (loading) return <div className="text-gray-400 text-center mt-20 text-sm">Connecting to Prometheus...</div>

  const wsStatus = status['ws:status']?.status || 'UNKNOWN'
  const wsColor = wsStatus === 'CONNECTED' ? 'text-green-400' : 'text-red-400'
  const activeSignals = signals.filter(s => s.direction !== 'flat')
  const topOpps = [...activeSignals].sort((a, b) => b.confidence - a.confidence).slice(0, 10)
  const heatmapSymbols = markets.slice(0, 30)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <StatCard label="WebSocket" value={wsStatus} color={wsColor} />
        <StatCard label="Active Symbols" value={String(status.active_symbol_count ?? markets.length)} color="text-blue-400" />
        <StatCard label="Active Signals" value={String(activeSignals.length)} color="text-orange-400" />
        <StatCard label="Best Genome" value={status.best_genome_fitness?.toFixed(4) ?? '—'} color="text-purple-400" />
        <StatCard label="Fear & Greed" value={String(status.fear_greed?.value ?? '—')} sub={status.fear_greed?.classification} color="text-yellow-400" />
        <StatCard label="VIX" value={status.macro_vix?.toFixed(1) ?? '—'} color={status.macro_vix && status.macro_vix > 40 ? 'text-red-400' : 'text-green-400'} />
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <h2 className="text-orange-400 font-semibold mb-3 text-sm uppercase tracking-wider">Top Opportunities</h2>
        {topOpps.length === 0 ? <p className="text-gray-500 text-sm">No active signals</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-gray-500 border-b border-gray-800 text-xs">
                <th className="text-left py-2 pr-4">Symbol</th>
                <th className="text-left py-2 pr-4">Direction</th>
                <th className="text-left py-2 pr-4">Confidence</th>
                <th className="text-left py-2 pr-4">RSI</th>
                <th className="text-left py-2 pr-4">Regime</th>
                <th className="text-left py-2 pr-4">Kelly%</th>
                <th className="text-left py-2">Drift</th>
              </tr></thead>
              <tbody>
                {topOpps.map(sig => {
                  const mkt = markets.find(m => m.symbol === sig.symbol)
                  return (
                    <tr key={sig.symbol} className="border-b border-gray-800/40 hover:bg-gray-800/30">
                      <td className="py-2 pr-4 font-semibold text-white">{sig.symbol}</td>
                      <td className="py-2 pr-4"><span className={`px-2 py-0.5 rounded text-xs font-bold ${DIR_STYLE[sig.direction]}`}>{sig.direction.toUpperCase()}</span></td>
                      <td className="py-2 pr-4"><ConfidenceBar value={sig.confidence} /></td>
                      <td className="py-2 pr-4 text-gray-300">{mkt?.rsi_14?.toFixed(1) ?? '—'}</td>
                      <td className={`py-2 pr-4 text-xs ${REGIME_COLOR[sig.regime] || 'text-gray-400'}`}>{sig.regime}</td>
                      <td className="py-2 pr-4 text-gray-300">{((sig.kelly_fraction ?? 0) * 100).toFixed(1)}%</td>
                      <td className={`py-2 text-xs ${DRIFT_COLOR[sig.drift_status] || 'text-gray-400'}`}>{sig.drift_status}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <h2 className="text-blue-400 font-semibold mb-3 text-sm uppercase tracking-wider">Market Heatmap — RSI</h2>
        <div className="grid grid-cols-5 sm:grid-cols-8 md:grid-cols-10 gap-1.5">
          {heatmapSymbols.map(m => (
            <div key={m.symbol} className={`border rounded p-1.5 text-center cursor-default ${rsiTileColor(m.rsi_14)}`}>
              <p className="text-xs font-semibold text-white truncate">{m.symbol.replace('USDT', '')}</p>
              <p className="text-xs text-gray-300">{m.rsi_14?.toFixed(0)}</p>
              <p className="text-xs">{m.direction === 'long' ? '▲' : m.direction === 'short' ? '▼' : '—'}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <h2 className="text-purple-400 font-semibold mb-3 text-sm uppercase tracking-wider">Shadow Leaderboard</h2>
        {shadow.length === 0 ? <p className="text-gray-500 text-sm">Shadow system warming up...</p> : (
          <table className="w-full text-sm">
            <thead><tr className="text-gray-500 border-b border-gray-800 text-xs">
              <th className="text-left py-2 pr-4">Universe</th>
              <th className="text-left py-2 pr-4">Sharpe</th>
              <th className="text-left py-2 pr-4">Win Rate</th>
              <th className="text-left py-2 pr-4">Trades</th>
              <th className="text-left py-2 pr-4">Return</th>
              <th className="text-left py-2">Status</th>
            </tr></thead>
            <tbody>
              {shadow.map(s => (
                <tr key={s.shadow_id} className="border-b border-gray-800/40">
                  <td className="py-2 pr-4 font-semibold">{s.shadow_id}</td>
                  <td className={`py-2 pr-4 ${s.sharpe >= 1.5 ? 'text-green-400' : 'text-gray-300'}`}>{s.sharpe?.toFixed(2)}</td>
                  <td className={`py-2 pr-4 ${s.win_rate >= 0.52 ? 'text-green-400' : 'text-gray-300'}`}>{((s.win_rate ?? 0) * 100).toFixed(1)}%</td>
                  <td className="py-2 pr-4 text-gray-300">{s.trades}</td>
                  <td className={`py-2 pr-4 ${(s.return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>{((s.return ?? 0) * 100).toFixed(2)}%</td>
                  <td className="py-2">{s.promotion_ready
                    ? <span className="bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded text-xs font-bold">READY</span>
                    : <span className="text-gray-500 text-xs">Training</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
