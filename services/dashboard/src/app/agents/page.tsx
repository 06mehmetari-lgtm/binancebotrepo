'use client'
import { useEffect, useState } from 'react'

interface Vote { agent: string; signal: string; confidence: number }
interface Verdict { direction: string; confidence: number; consensus_reasoning?: string; dissent_risk?: string }
interface Genome { fitness: number; generation: number; nodes: number; connections: number }
interface AgentData { symbol: string; votes: Vote[]; verdict: Verdict; genome: Genome }

const SIG_COLOR: Record<string, string> = { long: 'text-green-400', short: 'text-red-400', flat: 'text-gray-400' }
const SIG_BG: Record<string, string> = { long: 'bg-green-500', short: 'bg-red-500', flat: 'bg-gray-600' }
const SIG_BADGE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-700/50',
  short: 'text-red-400 bg-red-900/30 border border-red-700/50',
  flat: 'text-gray-400 bg-gray-800/50 border border-gray-700/40',
}

const AGENT_EMOJI: Record<string, string> = {
  bull_agent: '🐂', bear_agent: '🐻', neutral_agent: '⚖️', technical_agent: '📊',
  news_agent: '📰', macro_agent: '🌐', onchain_agent: '⛓️', risk_agent: '🛡️',
  evolution_agent: '🧬', debate_agent: '⚡',
}

export default function AgentsPage() {
  const [symbols, setSymbols] = useState<string[]>([])
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [data, setData] = useState<Partial<AgentData>>({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  useEffect(() => {
    fetch('/api/symbols').then(r => r.json()).then(d => {
      if (Array.isArray(d) && d.length > 0) { setSymbols(d); setSymbol(d[0]) }
    }).catch(() => setSymbols(['BTCUSDT', 'ETHUSDT', 'BNBUSDT']))
  }, [])

  useEffect(() => {
    const fetchData = async () => {
      try {
        const d = await fetch(`/api/agents?symbol=${symbol}`).then(r => r.json())
        setData(d || {})
        setLastUpdate(new Date().toLocaleTimeString())
      } catch { /* retry */ } finally { setLoading(false) }
    }
    fetchData()
    const t = setInterval(fetchData, 10000)
    return () => clearInterval(t)
  }, [symbol])

  const votes = data.votes ?? []
  const verdict = data.verdict
  const genome = data.genome

  const longVotes = votes.filter(v => v.signal === 'long').length
  const shortVotes = votes.filter(v => v.signal === 'short').length
  const flatVotes = votes.filter(v => v.signal === 'flat').length

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">9-Agent Debate System</h1>
          <p className="text-gray-500 text-xs mt-0.5">Multi-agent LLM consensus via Claude API</p>
        </div>
        <span className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate} · 10s` : '10s refresh'}</span>
      </div>

      <div className="flex flex-wrap gap-1.5 items-center">
        <span className="text-gray-600 text-xs mr-1">Symbol:</span>
        {(symbols.length ? symbols : ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']).slice(0, 20).map(s => (
          <button key={s} onClick={() => setSymbol(s)}
            className={`px-2.5 py-1 rounded text-xs transition-colors ${symbol === s ? 'bg-purple-600/30 text-purple-300 border border-purple-600/50 font-bold' : 'bg-gray-800/80 text-gray-400 hover:text-white border border-transparent'}`}>
            {s.replace('USDT', '')}
          </button>
        ))}
        {symbols.length > 20 && <span className="text-gray-600 text-xs">+{symbols.length - 20} more</span>}
      </div>

      {loading ? (
        <div className="text-center mt-10 text-gray-500 text-sm animate-pulse">Loading agent data...</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
                <h2 className="text-purple-400 font-semibold text-sm uppercase tracking-wider">Agent Votes</h2>
                <div className="flex gap-3 text-xs">
                  <span className="text-green-400">▲ {longVotes} long</span>
                  <span className="text-red-400">▼ {shortVotes} short</span>
                  <span className="text-gray-500">— {flatVotes} flat</span>
                </div>
              </div>
              {votes.length === 0 ? (
                <p className="text-gray-500 text-sm p-4">Waiting for agent analysis...</p>
              ) : (
                <div className="p-4 space-y-2.5">
                  {votes.map((v, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <span className="text-base w-6">{AGENT_EMOJI[v.agent] ?? '🤖'}</span>
                      <span className="text-gray-300 text-xs w-28 truncate">{v.agent.replace('_agent', '').replace('_', ' ')}</span>
                      <span className={`px-1.5 py-0.5 rounded text-xs font-bold w-12 text-center ${SIG_BADGE[v.signal] ?? SIG_BADGE.flat}`}>
                        {v.signal.toUpperCase()}
                      </span>
                      <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
                        <div className={`h-2 rounded-full transition-all ${SIG_BG[v.signal] ?? 'bg-gray-600'}`}
                          style={{ width: `${Math.round(v.confidence * 100)}%` }} />
                      </div>
                      <span className={`text-xs tabular-nums w-10 text-right font-mono ${SIG_COLOR[v.signal] ?? 'text-gray-400'}`}>
                        {Math.round(v.confidence * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {verdict && (
              <div className={`bg-gray-900 rounded-lg border overflow-hidden ${verdict.direction === 'long' ? 'border-green-800/60' : verdict.direction === 'short' ? 'border-red-800/60' : 'border-gray-800'}`}>
                <div className="px-4 py-3 border-b border-gray-800/60">
                  <h2 className="text-white font-semibold text-sm uppercase tracking-wider">Debate Verdict</h2>
                </div>
                <div className="p-4 space-y-3">
                  <div className="flex items-center gap-4">
                    <span className={`text-2xl font-black ${SIG_COLOR[verdict.direction] ?? 'text-gray-400'}`}>
                      {verdict.direction === 'long' ? '▲ LONG' : verdict.direction === 'short' ? '▼ SHORT' : '— FLAT'}
                    </span>
                    <div className="flex-1">
                      <div className="flex justify-between text-xs text-gray-500 mb-1">
                        <span>Confidence</span>
                        <span className="font-bold text-white">{Math.round((verdict.confidence ?? 0) * 100)}%</span>
                      </div>
                      <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
                        <div className={`h-2 rounded-full ${SIG_BG[verdict.direction] ?? 'bg-gray-600'}`}
                          style={{ width: `${Math.round((verdict.confidence ?? 0) * 100)}%` }} />
                      </div>
                    </div>
                  </div>
                  {verdict.consensus_reasoning && (
                    <div>
                      <p className="text-gray-600 text-xs uppercase tracking-wider mb-1">Consensus Reasoning</p>
                      <p className="text-gray-300 text-xs leading-relaxed bg-gray-800/40 rounded p-2.5">{verdict.consensus_reasoning}</p>
                    </div>
                  )}
                  {verdict.dissent_risk && (
                    <div>
                      <p className="text-yellow-600 text-xs uppercase tracking-wider mb-1">Dissent Risk</p>
                      <p className="text-yellow-300/80 text-xs leading-relaxed bg-yellow-900/10 border border-yellow-800/30 rounded p-2.5">{verdict.dissent_risk}</p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-4">
            {genome && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-800">
                  <h2 className="text-green-400 font-semibold text-sm uppercase tracking-wider">NEAT Genome</h2>
                </div>
                <div className="p-4 space-y-3 text-sm">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { label: 'Fitness', value: genome.fitness?.toFixed(4) ?? '—', color: 'text-green-400' },
                      { label: 'Generation', value: String(genome.generation ?? '—'), color: 'text-blue-400' },
                      { label: 'Nodes', value: String(genome.nodes ?? '—'), color: 'text-purple-400' },
                      { label: 'Connections', value: String(genome.connections ?? '—'), color: 'text-orange-400' },
                    ].map(item => (
                      <div key={item.label} className="bg-gray-800/50 rounded p-2.5">
                        <p className="text-gray-500 text-xs mb-0.5">{item.label}</p>
                        <p className={`font-bold text-base ${item.color}`}>{item.value}</p>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>Fitness score</span>
                      <span>{genome.fitness?.toFixed(4)}</span>
                    </div>
                    <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-2 rounded-full bg-gradient-to-r from-green-600 to-green-400"
                        style={{ width: `${Math.min(100, (genome.fitness ?? 0) * 100)}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
              <h2 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">Vote Distribution</h2>
              <div className="space-y-2">
                {[
                  { label: 'Long', count: longVotes, total: votes.length, color: 'bg-green-500', textColor: 'text-green-400' },
                  { label: 'Short', count: shortVotes, total: votes.length, color: 'bg-red-500', textColor: 'text-red-400' },
                  { label: 'Flat', count: flatVotes, total: votes.length, color: 'bg-gray-600', textColor: 'text-gray-400' },
                ].map(item => (
                  <div key={item.label} className="flex items-center gap-2 text-xs">
                    <span className={`w-8 ${item.textColor} font-semibold`}>{item.label}</span>
                    <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
                      <div className={`h-2 rounded-full ${item.color}`}
                        style={{ width: votes.length ? `${(item.count / votes.length) * 100}%` : '0%' }} />
                    </div>
                    <span className={`w-5 text-right ${item.textColor}`}>{item.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
