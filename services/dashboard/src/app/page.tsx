'use client'
import { useEffect, useState } from 'react'

interface Signal { symbol: string; direction: string; confidence: number; regime: string; crisis_level: number; drift_status: string }
interface ShadowEntry { shadow_id: string; sharpe: number; win_rate: number; trades: number; return: number; promotion_ready: boolean }
interface AgentVote { agent: string; signal: string; confidence: number }

const DIR_COLOR: Record<string, string> = { long: 'text-green-400', short: 'text-red-400', flat: 'text-gray-400' }

export default function Home() {
  const [signals, setSignals] = useState<Signal[]>([])
  const [shadow, setShadow] = useState<ShadowEntry[]>([])
  const [status, setStatus] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(true)

  const fetchAll = async () => {
    try {
      const [s, sh, st] = await Promise.all([
        fetch('/api/signals').then(r => r.json()),
        fetch('/api/shadow').then(r => r.json()),
        fetch('/api/status').then(r => r.json()),
      ])
      setSignals(Array.isArray(s) ? s : [])
      setShadow(Array.isArray(sh) ? sh : [])
      setStatus(st)
    } catch {
      // silently retry
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 5000)
    return () => clearInterval(interval)
  }, [])

  if (loading) return <div className="text-gray-400 text-center mt-20">Connecting to system...</div>

  const wsStatus = (status['ws:status'] as { status?: string })?.status || 'UNKNOWN'
  const wsColor = wsStatus === 'CONNECTED' ? 'text-green-400' : 'text-red-400'

  return (
    <div className="space-y-6">
      {/* Header stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="WebSocket" value={wsStatus} color={wsColor} />
        <StatCard label="Active Signals" value={signals.filter(s => s.direction !== 'flat').length.toString()} color="text-orange-400" />
        <StatCard label="Shadow Universes" value={shadow.length.toString()} color="text-blue-400" />
        <StatCard label="Promotion Ready" value={shadow.filter(s => s.promotion_ready).length.toString()} color="text-yellow-400" />
      </div>

      {/* Signals */}
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-orange-400 font-semibold mb-3">📡 Live Signals</h2>
        {signals.length === 0 ? (
          <p className="text-gray-500 text-sm">Waiting for signal data...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2">Symbol</th>
                  <th className="text-left py-2">Direction</th>
                  <th className="text-left py-2">Confidence</th>
                  <th className="text-left py-2">Regime</th>
                  <th className="text-left py-2">Crisis</th>
                  <th className="text-left py-2">Drift</th>
                </tr>
              </thead>
              <tbody>
                {signals.map(sig => (
                  <tr key={sig.symbol} className="border-b border-gray-800/50">
                    <td className="py-2 font-semibold">{sig.symbol}</td>
                    <td className={`py-2 font-bold ${DIR_COLOR[sig.direction] || 'text-gray-400'}`}>
                      {sig.direction.toUpperCase()}
                    </td>
                    <td className="py-2">{(sig.confidence * 100).toFixed(1)}%</td>
                    <td className="py-2 text-gray-300">{sig.regime}</td>
                    <td className={`py-2 ${sig.crisis_level > 0 ? 'text-red-400' : 'text-gray-400'}`}>
                      Level {sig.crisis_level}
                    </td>
                    <td className={`py-2 ${sig.drift_status !== 'STABLE' ? 'text-yellow-400' : 'text-gray-400'}`}>
                      {sig.drift_status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Shadow leaderboard */}
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-blue-400 font-semibold mb-3">👥 Shadow Leaderboard</h2>
        {shadow.length === 0 ? (
          <p className="text-gray-500 text-sm">Shadow system warming up...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2">Universe</th>
                  <th className="text-left py-2">Sharpe</th>
                  <th className="text-left py-2">Win Rate</th>
                  <th className="text-left py-2">Trades</th>
                  <th className="text-left py-2">Return</th>
                  <th className="text-left py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {shadow.map(s => (
                  <tr key={s.shadow_id} className="border-b border-gray-800/50">
                    <td className="py-2 font-semibold">{s.shadow_id}</td>
                    <td className={`py-2 ${s.sharpe >= 1.2 ? 'text-green-400' : 'text-gray-300'}`}>
                      {s.sharpe.toFixed(2)}
                    </td>
                    <td className={`py-2 ${s.win_rate >= 0.55 ? 'text-green-400' : 'text-gray-300'}`}>
                      {(s.win_rate * 100).toFixed(1)}%
                    </td>
                    <td className="py-2">{s.trades}</td>
                    <td className={`py-2 ${s.return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {(s.return * 100).toFixed(2)}%
                    </td>
                    <td className="py-2">
                      {s.promotion_ready ? (
                        <span className="bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded text-xs">🏆 READY</span>
                      ) : (
                        <span className="text-gray-500 text-xs">Training...</span>
                      )}
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

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  )
}
