'use client'
import { useEffect, useState } from 'react'

interface Signal { symbol: string; direction: string; confidence: number; kelly_fraction: number; regime: string; crisis_level: number; drift_status: string; timestamp: number }

const DIR_COLOR: Record<string, string> = { long: 'text-green-400', short: 'text-red-400', flat: 'text-gray-400' }

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([])
  useEffect(() => {
    const fetch_ = () => fetch('/api/signals').then(r => r.json()).then(d => setSignals(Array.isArray(d) ? d : []))
    fetch_()
    const t = setInterval(fetch_, 5000)
    return () => clearInterval(t)
  }, [])

  return (
    <div>
      <h1 className="text-xl font-bold text-orange-400 mb-4">Live Trading Signals</h1>
      {signals.length === 0 ? (
        <p className="text-gray-500">No signals yet — waiting for agent system...</p>
      ) : (
        <div className="space-y-4">
          {signals.map(sig => (
            <div key={sig.symbol} className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <div className="flex justify-between items-start">
                <div>
                  <span className="text-white font-bold text-lg">{sig.symbol}</span>
                  <span className={`ml-3 text-2xl font-bold ${DIR_COLOR[sig.direction]}`}>
                    {sig.direction.toUpperCase()}
                  </span>
                </div>
                <span className="text-gray-500 text-xs">{new Date(sig.timestamp).toLocaleTimeString()}</span>
              </div>
              <div className="mt-3 grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
                <Metric label="Confidence" value={(sig.confidence * 100).toFixed(1) + '%'} />
                <Metric label="Kelly Size" value={(sig.kelly_fraction * 100).toFixed(1) + '%'} />
                <Metric label="Regime" value={sig.regime} />
                <Metric label="Crisis" value={`Level ${sig.crisis_level}`} warn={sig.crisis_level > 0} />
                <Metric label="Drift" value={sig.drift_status} warn={sig.drift_status !== 'STABLE'} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <p className="text-gray-500 text-xs">{label}</p>
      <p className={warn ? 'text-yellow-400' : 'text-gray-200'}>{value}</p>
    </div>
  )
}
