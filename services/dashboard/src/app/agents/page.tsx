'use client'
import { useEffect, useState } from 'react'

interface Vote { agent: string; signal: string; confidence: number }
interface Verdict { direction: string; confidence: number; consensus: number; reasoning: string }

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
const SIG_COLOR: Record<string, string> = { long: 'text-green-400', short: 'text-red-400', flat: 'text-gray-400' }

export default function AgentsPage() {
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [votes, setVotes] = useState<Vote[]>([])
  const [verdict, setVerdict] = useState<Verdict | null>(null)

  useEffect(() => {
    const fetch_ = () =>
      fetch(`/api/agents?symbol=${symbol}`).then(r => r.json()).then(d => {
        setVotes(d.votes || [])
        setVerdict(d.verdict || null)
      })
    fetch_()
    const t = setInterval(fetch_, 10000)
    return () => clearInterval(t)
  }, [symbol])

  return (
    <div>
      <div className="flex items-center gap-4 mb-4">
        <h1 className="text-xl font-bold text-purple-400">9-Agent Debate System</h1>
        <div className="flex gap-2">
          {SYMBOLS.map(s => (
            <button key={s} onClick={() => setSymbol(s)}
              className={`px-3 py-1 rounded text-sm ${symbol === s ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {verdict && (
        <div className="bg-gray-900 border border-purple-800 rounded-lg p-4 mb-4">
          <div className="flex items-center gap-4">
            <span className="text-gray-400">Final verdict:</span>
            <span className={`text-2xl font-bold ${SIG_COLOR[verdict.direction] || 'text-gray-400'}`}>
              {verdict.direction.toUpperCase()}
            </span>
            <span className="text-gray-300">{(verdict.confidence * 100).toFixed(1)}% confidence</span>
            <span className="text-gray-300">{(verdict.consensus * 100).toFixed(0)}% consensus</span>
          </div>
          <p className="text-gray-500 text-sm mt-2">{verdict.reasoning}</p>
        </div>
      )}

      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-gray-400 text-sm mb-3">Agent Votes</h2>
        {votes.length === 0 ? (
          <p className="text-gray-500 text-sm">No votes yet...</p>
        ) : (
          <div className="space-y-2">
            {votes.map((v, i) => (
              <div key={i} className="flex items-center gap-4">
                <span className="text-gray-300 w-32">{v.agent}</span>
                <span className={`w-16 font-semibold ${SIG_COLOR[v.signal] || 'text-gray-400'}`}>
                  {v.signal.toUpperCase()}
                </span>
                <div className="flex-1 bg-gray-800 rounded-full h-2">
                  <div className={`h-2 rounded-full ${v.signal === 'long' ? 'bg-green-500' : v.signal === 'short' ? 'bg-red-500' : 'bg-gray-600'}`}
                    style={{ width: `${v.confidence * 100}%` }} />
                </div>
                <span className="text-gray-400 text-sm w-12">{(v.confidence * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
