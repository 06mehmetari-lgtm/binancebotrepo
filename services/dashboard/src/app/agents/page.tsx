'use client'
import { useEffect, useState } from 'react'

interface Vote { agent: string; signal: string; confidence: number; reasoning?: string }
interface Verdict {
  direction: string; confidence: number
  consensus_reasoning?: string; dissent_risk?: string
}
interface Genome { fitness: number; generation: number; nodes: number; connections: number; status?: string }
interface OpenPosition { direction: string; size_usd?: number; entry_price?: number; entry_time?: number }
interface AgentData {
  symbol: string; votes: Vote[]; verdict: Verdict & { trade_action?: string; open_position?: OpenPosition }
  genome: Genome
  open_position?: OpenPosition | null
  portfolio?: { total_open: number; long_positions: number; short_positions: number } | null
  live_signal?: { direction: string; confidence: number; trade_action?: string; has_position?: boolean } | null
}

const SIG_COLOR: Record<string, string> = { long: 'text-green-400', short: 'text-red-400', flat: 'text-gray-400' }
const SIG_BG: Record<string, string> = { long: 'bg-green-500', short: 'bg-red-500', flat: 'bg-gray-600' }
const SIG_BADGE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-700/50',
  short: 'text-red-400 bg-red-900/30 border border-red-700/50',
  flat: 'text-gray-400 bg-gray-800/50 border border-gray-700/40',
}

const AGENT_META: Record<string, { emoji: string; role: string; desc: string; group: string }> = {
  bull_agent:      { emoji: '🐂', role: 'Directional', desc: 'Seeks bullish setups: uptrends, positive momentum, demand signals', group: 'directional' },
  bear_agent:      { emoji: '🐻', role: 'Directional', desc: 'Seeks bearish setups: downtrends, negative divergence, supply signals', group: 'directional' },
  neutral_agent:   { emoji: '⚖️', role: 'Directional', desc: 'Balanced perspective; anchors debate against extremes', group: 'directional' },
  technical_agent: { emoji: '📊', role: 'Analysis', desc: 'RSI, MACD, Bollinger, ADX, Stoch — pure price/indicator synthesis', group: 'analysis' },
  news_agent:      { emoji: '📰', role: 'Analysis', desc: 'NLP sentiment from headlines, Reddit, CryptoPanic feed', group: 'analysis' },
  macro_agent:     { emoji: '🌐', role: 'Analysis', desc: 'VIX, DXY, Fed policy, BTC dominance, macro correlation', group: 'analysis' },
  onchain_agent:   { emoji: '⛓️', role: 'Analysis', desc: 'Exchange flows, whale activity, funding rates, OI trends', group: 'analysis' },
  risk_agent:      { emoji: '🛡️', role: 'System', desc: 'VaR, Kelly sizing, drawdown limits — votes flat when risk is high', group: 'system' },
  evolution_agent: { emoji: '🧬', role: 'System', desc: 'NEAT genome signal; carries the evolved strategy for this symbol', group: 'system' },
  debate_agent:    { emoji: '⚡', role: 'Moderator', desc: 'Moderates Bull vs Bear exchange; synthesizes final JSON verdict', group: 'moderator' },
}

const CRISIS_MULT = [1.0, 0.65, 0.35, 0.10, 0.0]
const DRIFT_MULT: Record<string, number> = { STABLE: 0.50, WARNING: 0.35, DRIFTING: 0.20, SHOCK: 0.0 }
const DRIFT_COLOR: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500' }

function AgentVoteRow({ v, index }: { v: Vote; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const meta = AGENT_META[v.agent]
  const pct = Math.round((v.confidence ?? 0) * 100)

  return (
    <div className="rounded-lg border border-gray-800/60 overflow-hidden">
      <div
        className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-800/30 transition-colors"
        onClick={() => v.reasoning && setExpanded(e => !e)}
      >
        <span className="text-base w-6 shrink-0">{meta?.emoji ?? '🤖'}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-gray-200 text-xs font-semibold">{v.agent.replace(/_agent$/, '').replace(/_/, ' ')}</span>
            {meta && <span className="text-gray-600 text-[10px] bg-gray-800/60 px-1.5 rounded">{meta.role}</span>}
          </div>
          {meta && <p className="text-gray-600 text-[10px] mt-0.5 leading-relaxed truncate">{meta.desc}</p>}
        </div>
        <span className={`px-1.5 py-0.5 rounded text-xs font-bold w-14 text-center shrink-0 ${SIG_BADGE[v.signal] ?? SIG_BADGE.flat}`}>
          {v.signal.toUpperCase()}
        </span>
        <div className="flex items-center gap-1.5 shrink-0 w-28">
          <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
            <div className={`h-full rounded-full transition-all ${SIG_BG[v.signal] ?? 'bg-gray-600'}`}
              style={{ width: `${pct}%` }} />
          </div>
          <span className={`text-xs font-mono tabular-nums w-8 text-right ${SIG_COLOR[v.signal] ?? 'text-gray-400'}`}>{pct}%</span>
        </div>
        {v.reasoning && (
          <span className="text-gray-700 text-xs shrink-0">{expanded ? '▲' : '▼'}</span>
        )}
      </div>
      {expanded && v.reasoning && (
        <div className="px-3 pb-3 pt-1 border-t border-gray-800/60 bg-gray-900/60">
          <p className="text-gray-400 text-xs leading-relaxed">{v.reasoning}</p>
        </div>
      )}
    </div>
  )
}

function KellyBreakdown({ verdict, genome }: { verdict: Verdict; genome: Genome | null }) {
  const crisis = 0  // would come from signal data; default normal
  const drift = 'STABLE'
  const baseKelly = (verdict.confidence ?? 0)
  const driftAdj = DRIFT_MULT[drift] ?? 0.5
  const crisisAdj = CRISIS_MULT[crisis] ?? 1.0
  const maxPos = 0.05  // 5% hard cap (immunity system)
  const rawKelly = baseKelly * driftAdj * crisisAdj
  const finalPos = Math.min(maxPos, rawKelly) * 100

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-orange-400 font-semibold text-xs uppercase tracking-wider">Kelly Position Sizing</h2>
        <p className="text-gray-600 text-xs mt-0.5">Crisis × drift × confidence → capped at 5%</p>
      </div>
      <div className="p-4 space-y-3">
        <div className="space-y-2 text-xs">
          {[
            { label: 'Base Kelly (confidence)', value: `${(baseKelly * 100).toFixed(1)}%`, color: 'text-white' },
            { label: `Drift adj (${drift} = ${(driftAdj * 100).toFixed(0)}%)`, value: `× ${driftAdj.toFixed(2)}`, color: DRIFT_COLOR[drift] },
            { label: `Crisis adj (L${crisis} = ${(crisisAdj * 100).toFixed(0)}% Kelly)`, value: `× ${crisisAdj.toFixed(2)}`, color: 'text-green-400' },
            { label: 'Raw Kelly', value: `${(rawKelly * 100).toFixed(2)}%`, color: 'text-orange-400' },
            { label: 'Hard cap (immunity)', value: '5.00%', color: 'text-red-400' },
          ].map(row => (
            <div key={row.label} className="flex justify-between items-center">
              <span className="text-gray-500">{row.label}</span>
              <span className={`font-mono font-bold ${row.color}`}>{row.value}</span>
            </div>
          ))}
        </div>
        <div className="pt-2 border-t border-gray-800/60">
          <div className="flex justify-between items-center mb-1.5">
            <span className="text-gray-400 text-xs font-semibold">Final Position Size</span>
            <span className={`text-lg font-black font-mono ${verdict.direction === 'long' ? 'text-green-400' : verdict.direction === 'short' ? 'text-red-400' : 'text-gray-500'}`}>
              {verdict.direction !== 'flat' ? `${finalPos.toFixed(2)}%` : 'FLAT'}
            </span>
          </div>
          {verdict.direction !== 'flat' && (
            <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${verdict.direction === 'long' ? 'bg-green-500' : 'bg-red-500'}`}
                style={{ width: `${Math.min(100, finalPos / maxPos / 100 * 100 * maxPos * 100)}%` }} />
            </div>
          )}
          <p className="text-gray-600 text-[10px] mt-1.5">Position size is 0% when direction = flat or crisis L4</p>
        </div>
      </div>
    </div>
  )
}

function ConsensusWheel({ votes }: { votes: Vote[] }) {
  if (!votes.length) return null
  const total = votes.length
  const longVotes = votes.filter(v => v.signal === 'long')
  const shortVotes = votes.filter(v => v.signal === 'short')
  const flatVotes = votes.filter(v => v.signal === 'flat')
  const longConf = longVotes.reduce((s, v) => s + v.confidence, 0) / (longVotes.length || 1)
  const shortConf = shortVotes.reduce((s, v) => s + v.confidence, 0) / (shortVotes.length || 1)

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
      <h2 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">Vote Breakdown</h2>
      <div className="space-y-2.5">
        {[
          { label: 'Long', votes: longVotes, total, bg: 'bg-green-500', text: 'text-green-400', avgConf: longConf },
          { label: 'Short', votes: shortVotes, total, bg: 'bg-red-500', text: 'text-red-400', avgConf: shortConf },
          { label: 'Flat', votes: flatVotes, total, bg: 'bg-gray-600', text: 'text-gray-400', avgConf: 0 },
        ].map(item => (
          <div key={item.label} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className={`font-semibold w-10 ${item.text}`}>{item.label}</span>
              <div className="flex-1 mx-2 bg-gray-800 rounded-full h-2 overflow-hidden">
                <div className={`h-full rounded-full ${item.bg}`}
                  style={{ width: total ? `${(item.votes.length / total) * 100}%` : '0%' }} />
              </div>
              <span className={`w-14 text-right font-mono ${item.text}`}>
                {item.votes.length}/{total}
                {item.votes.length > 0 && <span className="text-gray-600 ml-1">({Math.round(item.avgConf * 100)}%)</span>}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="pt-3 border-t border-gray-800/60 mt-2 text-xs text-gray-600">
        Avg confidence shown per vote direction · signals below 60% are suppressed to flat
      </div>
    </div>
  )
}

export default function AgentsPage() {
  const [symbols, setSymbols] = useState<string[]>([])
  const [signals, setSignals] = useState<Record<string, { direction: string; confidence: number }>>({})
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [search, setSearch] = useState('')
  const [data, setData] = useState<Partial<AgentData>>({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [portfolio, setPortfolio] = useState<{ total_open: number; long_positions: number; short_positions: number } | null>(null)

  useEffect(() => {
    fetch('/api/portfolio/state').then(r => r.json()).then(p => {
      if (p && typeof p.total_open === 'number') {
        setPortfolio({
          total_open: p.total_open,
          long_positions: p.long_positions ?? 0,
          short_positions: p.short_positions ?? 0,
        })
      }
    }).catch(() => {})
    fetch('/api/symbols').then(r => r.json()).then(d => {
      if (Array.isArray(d) && d.length > 0) { setSymbols(d); setSymbol(d[0]) }
    }).catch(() => setSymbols(['BTCUSDT', 'ETHUSDT', 'BNBUSDT']))
    // Fetch live signals to show direction badges
    fetch('/api/signals').then(r => r.json()).then((d: any[]) => {
      if (Array.isArray(d)) {
        const map: Record<string, { direction: string; confidence: number }> = {}
        d.forEach(s => { map[s.symbol] = { direction: s.direction, confidence: s.confidence } })
        setSignals(map)
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    const fetchData = async () => {
      try {
        const d = await fetch(`/api/agents?symbol=${symbol}`).then(r => r.json())
        setData(d || {})
        setLastUpdate(new Date().toLocaleTimeString())
      } catch { } finally { setLoading(false) }
    }
    fetchData()
    const t = setInterval(fetchData, 10000)
    return () => clearInterval(t)
  }, [symbol])

  const votes = data.votes ?? []
  const verdict = data.verdict
  const genome = data.genome ?? null

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">9-Agent Debate System</h1>
          <p className="text-gray-500 text-xs mt-0.5">Multi-agent LLM deliberation (Groq → Ollama → rule-based fallback) · each agent has a distinct role and perspective</p>
        </div>
        <span className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate} · 10s` : '10s refresh'}</span>
      </div>

      {/* Symbol Selector with search */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 space-y-2.5">
        <div className="flex items-center gap-3">
          <input
            value={search}
            onChange={e => setSearch(e.target.value.toUpperCase())}
            placeholder="Search symbol (e.g. BTC, ETH, SOL)..."
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-purple-500 transition-colors"
          />
          <div className="flex items-center gap-2 text-xs text-gray-600 shrink-0 flex-wrap justify-end">
            <span className="text-green-400 font-semibold" title="Yeni long sinyaller">Sinyal ▲ {Object.values(signals).filter(s => s.direction === 'long').length}</span>
            <span className="text-red-400 font-semibold" title="Yeni short sinyaller">Sinyal ▼ {Object.values(signals).filter(s => s.direction === 'short').length}</span>
            {portfolio && portfolio.total_open > 0 && (
              <span className="text-orange-400 font-bold border border-orange-700/50 px-2 py-0.5 rounded" title="Açık pozisyonlar (OMS+Shadow)">
                Pozisyon {portfolio.total_open} (▲{portfolio.long_positions} ▼{portfolio.short_positions})
              </span>
            )}
            <span>{symbols.length} coin</span>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
          {(symbols.length ? symbols : ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'])
            .filter(s => !search || s.includes(search))
            .map(s => {
              const sig = signals[s]
              const dirColor = sig?.direction === 'long' ? 'text-green-400' : sig?.direction === 'short' ? 'text-red-400' : ''
              const dirArrow = sig?.direction === 'long' ? '▲' : sig?.direction === 'short' ? '▼' : ''
              return (
                <button key={s} onClick={() => { setSymbol(s); setSearch('') }}
                  className={`px-2.5 py-1.5 rounded text-xs transition-all flex items-center gap-1 ${symbol === s
                    ? 'bg-purple-600/30 text-purple-300 border border-purple-600/50 font-bold'
                    : 'bg-gray-800/80 text-gray-400 hover:text-white border border-transparent hover:border-gray-600'}`}>
                  {s.replace('USDT', '')}
                  {dirArrow && <span className={`text-[10px] ${dirColor}`}>{dirArrow}</span>}
                </button>
              )
            })}
          {symbols.filter(s => !search || s.includes(search)).length === 0 && (
            <p className="text-gray-600 text-xs py-2">No symbols match "{search}"</p>
          )}
        </div>
      </div>

      {(data.open_position || data.verdict?.trade_action === 'close' || data.live_signal?.trade_action === 'close') && (
        <div className="bg-orange-950/40 border border-orange-600/50 rounded-xl px-4 py-3 text-sm">
          <span className="text-orange-300 font-bold">Senkron durum: </span>
          {data.open_position ? (
            <span className="text-orange-100">
              Açık {data.open_position.direction?.toUpperCase()} pozisyon var
              {data.verdict?.trade_action === 'close' || data.live_signal?.trade_action === 'close'
                ? ' — AI çıkış (SAT/KAPAT) öneriyor, OMS kapatacak'
                : data.verdict?.trade_action === 'hold'
                  ? ' — AI tutma öneriyor'
                  : ' — sinyal güncelleniyor'}
            </span>
          ) : (
            <span className="text-gray-400">Pozisyon verisi yükleniyor...</span>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-center mt-10 text-gray-500 text-sm animate-pulse">Loading agent data...</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
                <h2 className="text-purple-400 font-semibold text-sm uppercase tracking-wider">Agent Votes</h2>
                <div className="flex gap-3 text-xs">
                  <span className="text-green-400">▲ {votes.filter(v => v.signal === 'long').length} long</span>
                  <span className="text-red-400">▼ {votes.filter(v => v.signal === 'short').length} short</span>
                  <span className="text-gray-500">— {votes.filter(v => v.signal === 'flat').length} flat</span>
                </div>
              </div>
              {votes.length === 0 ? (
                <div className="p-6 text-center">
                  <p className="text-gray-500 text-sm">Waiting for agent analysis...</p>
                  <p className="text-gray-600 text-xs mt-1">Agents run on each new feature cycle for {symbol}</p>
                </div>
              ) : (
                <div className="p-3 space-y-1.5">
                  {votes.filter(v => v.agent !== 'debate_agent').map((v, i) => (
                    <AgentVoteRow key={v.agent ?? i} v={v} index={i} />
                  ))}
                </div>
              )}
            </div>

            {verdict && (
              <div className={`bg-gray-900 rounded-lg border overflow-hidden ${
                verdict.direction === 'long' ? 'border-green-800/60' : verdict.direction === 'short' ? 'border-red-800/60' : 'border-gray-800'
              }`}>
                <div className="px-4 py-3 border-b border-gray-800/60 flex items-center gap-2">
                  <span className="text-xl">{AGENT_META.debate_agent.emoji}</span>
                  <div>
                    <h2 className="text-white font-semibold text-sm">Debate Verdict</h2>
                    <p className="text-gray-500 text-xs">Synthesized by DebateAgent after Bull ↔ Bear exchange</p>
                  </div>
                </div>
                <div className="p-4 space-y-3">
                  <div className="flex items-center gap-4">
                    <span className={`text-2xl font-black ${SIG_COLOR[verdict.direction] ?? 'text-gray-400'}`}>
                      {verdict.trade_action === 'close' ? '🛑 KAPAT' :
                        verdict.direction === 'long' ? '▲ LONG' :
                        verdict.direction === 'short' ? '▼ SHORT' : '— FLAT'}
                    </span>
                    {verdict.trade_action && verdict.trade_action !== 'none' && (
                      <span className="text-xs px-2 py-1 rounded bg-gray-800 text-orange-300 border border-orange-700/40">
                        aksiyon: {verdict.trade_action}
                      </span>
                    )}
                    <div className="flex-1">
                      <div className="flex justify-between text-xs text-gray-500 mb-1">
                        <span>Consensus Confidence</span>
                        <span className={`font-bold ${(verdict.confidence ?? 0) >= 0.60 ? 'text-white' : 'text-yellow-400'}`}>
                          {Math.round((verdict.confidence ?? 0) * 100)}%
                          {(verdict.confidence ?? 0) < 0.60 && <span className="text-yellow-600 ml-1">(→ suppressed to flat)</span>}
                        </span>
                      </div>
                      <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
                        <div className={`h-2 rounded-full ${SIG_BG[verdict.direction] ?? 'bg-gray-600'}`}
                          style={{ width: `${Math.round((verdict.confidence ?? 0) * 100)}%` }} />
                      </div>
                      <div className="flex justify-between text-[10px] text-gray-700 mt-1">
                        <span>0%</span>
                        <span className="text-yellow-700">60% threshold</span>
                        <span>100%</span>
                      </div>
                    </div>
                  </div>
                  {verdict.consensus_reasoning && (
                    <div>
                      <p className="text-gray-500 text-xs uppercase tracking-wider mb-1.5">Consensus Reasoning</p>
                      <p className="text-gray-300 text-xs leading-relaxed bg-gray-800/40 rounded p-2.5 border border-gray-700/40">
                        {verdict.consensus_reasoning}
                      </p>
                    </div>
                  )}
                  {verdict.dissent_risk && (
                    <div>
                      <p className="text-yellow-600 text-xs uppercase tracking-wider mb-1.5">Dissent Risk</p>
                      <p className="text-yellow-300/80 text-xs leading-relaxed bg-yellow-900/10 border border-yellow-800/30 rounded p-2.5">
                        {verdict.dissent_risk}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-4">
            <ConsensusWheel votes={votes} />

            {verdict && <KellyBreakdown verdict={verdict} genome={genome} />}

            {genome && (
              <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-800 flex items-center gap-2">
                  <span className="text-lg">{AGENT_META.evolution_agent.emoji}</span>
                  <h2 className="text-green-400 font-semibold text-sm uppercase tracking-wider">Active NEAT Genome</h2>
                </div>
                <div className="p-4 space-y-3">
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
                      <span>Fitness (Sharpe × WR × (1−DD))</span>
                      <span className="text-white font-mono">{genome.fitness?.toFixed(4)}</span>
                    </div>
                    <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-2 rounded-full bg-gradient-to-r from-green-700 to-green-400"
                        style={{ width: `${Math.min(100, (genome.fitness ?? 0) * 100)}%` }} />
                    </div>
                  </div>
                  {genome.status && (
                    <div className="text-xs text-gray-500">
                      Status: <span className="text-white font-semibold">{genome.status}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
              <h2 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">Agent Groups</h2>
              <div className="space-y-3">
                {(['directional', 'analysis', 'system'] as const).map(group => {
                  const groupAgents = Object.entries(AGENT_META).filter(([, m]) => m.group === group)
                  return (
                    <div key={group}>
                      <p className={`text-xs font-semibold uppercase tracking-wider mb-1.5 ${group === 'directional' ? 'text-blue-400' : group === 'analysis' ? 'text-yellow-400' : 'text-purple-400'}`}>
                        {group}
                      </p>
                      <div className="space-y-1">
                        {groupAgents.map(([key, meta]) => {
                          const vote = votes.find(v => v.agent === key)
                          return (
                            <div key={key} className="flex items-center gap-2 text-xs">
                              <span className="w-5">{meta.emoji}</span>
                              <span className="text-gray-400 flex-1">{key.replace('_agent', '')}</span>
                              {vote
                                ? <span className={`font-bold text-[10px] ${SIG_COLOR[vote.signal]}`}>{vote.signal.toUpperCase()}</span>
                                : <span className="text-gray-700 text-[10px]">—</span>}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
