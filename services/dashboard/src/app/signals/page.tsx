'use client'
import { useEffect, useState } from 'react'

interface Signal {
  symbol: string; direction: string; confidence: number; kelly_fraction: number
  regime: string; crisis_level: number; drift_status: string; timestamp?: number
}

const DIR_STYLE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-700/50',
  short: 'text-red-400 bg-red-900/30 border border-red-700/50',
  flat: 'text-gray-400 bg-gray-800/50 border border-gray-700/40',
}
const REGIME_STYLE: Record<string, string> = {
  trending_up: 'text-green-400 bg-green-900/20 border-green-800/50',
  trending_down: 'text-red-400 bg-red-900/20 border-red-800/50',
  ranging: 'text-blue-400 bg-blue-900/20 border-blue-800/50',
  volatile: 'text-yellow-400 bg-yellow-900/20 border-yellow-800/50',
}
const DRIFT_COLOR: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500' }
const CRISIS_COLOR = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-500 animate-pulse']
const CRISIS_LABEL = ['None', 'Low', 'Medium', 'High', 'CRITICAL']

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'bg-green-500' : pct >= 65 ? 'bg-orange-500' : 'bg-yellow-600'
  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-gray-500">Confidence</span>
        <span className={`text-sm font-bold ${pct >= 80 ? 'text-green-400' : pct >= 65 ? 'text-orange-400' : 'text-yellow-400'}`}>{pct}%</span>
      </div>
      <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = async () => {
    try {
      const data = await fetch('/api/signals').then(r => r.json())
      const active = (Array.isArray(data) ? data : [])
        .filter((s: Signal) => s.direction !== 'flat')
        .sort((a: Signal, b: Signal) => b.confidence - a.confidence)
      setSignals(active)
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { /* retry */ } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 5000); return () => clearInterval(t) }, [])

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-pulse text-orange-400">◉</span>
      <span className="text-sm">Fetching signals...</span>
    </div>
  )

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-white font-bold text-base">Active Signals</h1>
          <p className="text-gray-500 text-xs mt-0.5">Non-flat signals sorted by confidence · threshold ≥ 60%</p>
        </div>
        <div className="text-right">
          <span className="text-orange-400 font-bold text-xl">{signals.length}</span>
          <p className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate} · 5s` : '5s refresh'}</p>
        </div>
      </div>

      {signals.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
          <p className="text-gray-400 text-sm">No active signals — all positions are flat</p>
          <p className="text-gray-600 text-xs mt-1">The signal engine suppresses signals below 60% confidence</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {signals.map(sig => (
            <div key={sig.symbol} className={`bg-gray-900 rounded-lg border overflow-hidden transition-all hover:border-gray-600 ${sig.direction === 'long' ? 'border-green-900/60' : sig.direction === 'short' ? 'border-red-900/60' : 'border-gray-800'}`}>
              <div className="px-4 py-3 flex items-center justify-between border-b border-gray-800/60">
                <div className="flex items-center gap-3">
                  <span className="font-bold text-white text-base">{sig.symbol}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${DIR_STYLE[sig.direction]}`}>
                    {sig.direction === 'long' ? '▲ LONG' : sig.direction === 'short' ? '▼ SHORT' : '— FLAT'}
                  </span>
                </div>
                {sig.timestamp && (
                  <span className="text-gray-600 text-xs">{new Date(sig.timestamp).toLocaleTimeString()}</span>
                )}
              </div>

              <div className="px-4 py-3 space-y-3">
                <ConfidenceMeter value={sig.confidence} />

                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="bg-gray-800/50 rounded p-2">
                    <p className="text-gray-500 mb-0.5">Kelly Size</p>
                    <p className="text-white font-bold">{((sig.kelly_fraction ?? 0) * 100).toFixed(1)}%</p>
                  </div>
                  <div className="bg-gray-800/50 rounded p-2">
                    <p className="text-gray-500 mb-0.5">Crisis Level</p>
                    <p className={`font-bold ${CRISIS_COLOR[sig.crisis_level] ?? 'text-gray-400'}`}>
                      {CRISIS_LABEL[sig.crisis_level] ?? `L${sig.crisis_level}`}
                    </p>
                  </div>
                </div>

                <div className="flex items-center justify-between text-xs">
                  <span className={`px-2 py-0.5 rounded border text-xs font-medium ${REGIME_STYLE[sig.regime] ?? 'text-gray-400 bg-gray-800/40 border-gray-700/40'}`}>
                    {sig.regime ?? 'unknown'}
                  </span>
                  <span className={`font-semibold ${DRIFT_COLOR[sig.drift_status] ?? 'text-gray-400'}`}>
                    {sig.drift_status === 'STABLE' ? '✓' : sig.drift_status === 'SHOCK' ? '⚠' : '~'} {sig.drift_status}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
