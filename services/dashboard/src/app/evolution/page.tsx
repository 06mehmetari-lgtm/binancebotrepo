'use client'
import { useEffect, useState } from 'react'

interface Genome {
  genome_id: string
  fitness: number
  generation: number
  nodes: number
  connections: number
  symbol: string
  status?: string
  win_rate?: number
  sharpe_ratio?: number
  total_trades?: number
  species?: string
}

interface Shadow {
  shadow_id: string
  sharpe: number
  win_rate: number
  trades: number
  return: number
  promotion_ready: boolean
  max_drawdown?: number
}

interface EvoData {
  genomes: Genome[]
  shadow_leaderboard: Shadow[]
}

interface Status {
  active_symbol_count: number
  total_signals: number
  avg_confidence: number
  best_genome_fitness: number
}

const STATUS_COLOR: Record<string, string> = {
  TRIAL: 'text-blue-400 bg-blue-900/30 border-blue-700/50',
  APPROVED: 'text-cyan-400 bg-cyan-900/30 border-cyan-700/50',
  ACTIVE: 'text-green-400 bg-green-900/30 border-green-700/50',
  PROBATION: 'text-yellow-400 bg-yellow-900/30 border-yellow-700/50',
  DEAD: 'text-red-400 bg-red-900/30 border-red-700/50',
  ARCHIVED: 'text-gray-500 bg-gray-800/30 border-gray-700/40',
}

const PROMO_CRITERIA = { trades: 100, sharpe: 1.5, win_rate: 0.52, max_drawdown: 0.10 }

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLOR[status] ?? 'text-gray-400 bg-gray-800/30 border-gray-700/40'
  return <span className={`px-1.5 py-0.5 rounded border text-xs font-semibold ${cls}`}>{status}</span>
}

function CriteriaBar({ value, target, met, label, display, invert }: {
  value: number; target: number; met: boolean; label: string; display: string; invert?: boolean
}) {
  const pct = invert
    ? (value <= target ? 100 : Math.min(100, (target / value) * 100))
    : Math.min(100, (value / target) * 100)
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`w-4 shrink-0 ${met ? 'text-green-400' : 'text-gray-600'}`}>{met ? '✓' : '○'}</span>
      <span className="text-gray-500 w-24 shrink-0">{label}</span>
      <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full ${met ? 'bg-green-500' : invert ? 'bg-red-500' : 'bg-orange-500/60'}`}
          style={{ width: `${pct}%` }} />
      </div>
      <span className={`font-mono w-28 text-right shrink-0 ${met ? 'text-green-400' : 'text-gray-400'}`}>{display}</span>
    </div>
  )
}

function ShadowCard({ s, rank }: { s: Shadow; rank: number }) {
  const dd = (s.max_drawdown ?? 0) * 100
  const wr = (s.win_rate ?? 0) * 100
  const ret = (s.return ?? 0) * 100
  const passCount = [
    s.trades >= PROMO_CRITERIA.trades,
    (s.sharpe ?? 0) >= PROMO_CRITERIA.sharpe,
    wr >= PROMO_CRITERIA.win_rate * 100,
    dd <= PROMO_CRITERIA.max_drawdown * 100,
  ].filter(Boolean).length

  return (
    <div className={`bg-gray-900 rounded-lg border overflow-hidden ${s.promotion_ready ? 'border-yellow-500/60' : 'border-gray-800'}`}>
      <div className="px-4 py-3 border-b border-gray-800/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`font-bold text-lg ${rank === 0 ? 'text-yellow-400' : 'text-gray-500'}`}>#{rank + 1}</span>
          <div>
            <p className="font-bold text-white text-sm">{s.shadow_id}</p>
            <p className="text-gray-500 text-xs">{passCount}/4 criteria met</p>
          </div>
        </div>
        {s.promotion_ready
          ? <span className="bg-yellow-500/20 text-yellow-400 border border-yellow-500/40 px-2 py-0.5 rounded text-xs font-bold animate-pulse">READY</span>
          : <span className="text-gray-600 text-xs">Paper Trading</span>}
      </div>
      <div className="p-4 space-y-2.5">
        <CriteriaBar label="Trades" value={s.trades} target={100} met={s.trades >= 100} display={`${s.trades} / 100`} />
        <CriteriaBar label="Sharpe" value={s.sharpe ?? 0} target={1.5} met={(s.sharpe ?? 0) >= 1.5} display={`${(s.sharpe ?? 0).toFixed(3)} / 1.5`} />
        <CriteriaBar label="Win Rate" value={wr} target={52} met={wr >= 52} display={`${wr.toFixed(1)}% / 52%`} />
        <CriteriaBar label="Max DD" value={dd} target={10} met={dd <= 10} invert display={`${dd.toFixed(1)}% / <10%`} />
        <div className="pt-1.5 border-t border-gray-800/60 flex justify-between text-xs">
          <span className="text-gray-500">Return</span>
          <span className={`font-bold font-mono ${ret >= 0 ? 'text-green-400' : 'text-red-400'}`}>{ret >= 0 ? '+' : ''}{ret.toFixed(2)}%</span>
        </div>
      </div>
    </div>
  )
}

export default function EvolutionPage() {
  const [evo, setEvo] = useState<Partial<EvoData>>({})
  const [status, setStatus] = useState<Partial<Status>>({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = async () => {
    try {
      const [e, st] = await Promise.all([
        fetch('/api/evolution').then(r => r.json()),
        fetch('/api/status').then(r => r.json()),
      ])
      setEvo(e || {})
      setStatus(st || {})
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 10000); return () => clearInterval(t) }, [])

  const genomes = (evo.genomes ?? []).sort((a, b) => b.fitness - a.fitness)
  const shadows = (evo.shadow_leaderboard ?? []).sort((a, b) => (b.sharpe ?? 0) - (a.sharpe ?? 0))
  const bestFitness = genomes[0]?.fitness ?? 0
  const generations = genomes.length > 0 ? Math.max(...genomes.map(g => g.generation ?? 0)) : 0
  const avgFitness = genomes.length > 0 ? genomes.reduce((s, g) => s + (g.fitness ?? 0), 0) / genomes.length : 0
  const speciesSet = new Set(genomes.map(g => g.species).filter(Boolean))

  if (loading && genomes.length === 0 && shadows.length === 0) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-green-400 text-lg">◌</span>
      <span className="text-sm">Loading evolution data...</span>
    </div>
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">AI Learning & Evolution</h1>
          <p className="text-gray-500 text-xs mt-0.5">NEAT genome evolution + Shadow system parallel testing</p>
        </div>
        <span className="text-xs text-gray-600 shrink-0">{lastUpdate ? `${lastUpdate} · 10s` : '10s refresh'}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        {[
          { label: 'Active Symbols', value: String(status.active_symbol_count ?? '—'), color: 'text-blue-400' },
          { label: 'Best Genome Fitness', value: status.best_genome_fitness?.toFixed(4) ?? '—', color: 'text-green-400' },
          { label: 'Max Generation', value: generations > 0 ? String(generations) : '—', color: 'text-purple-400' },
          { label: 'Genome Pool', value: String(genomes.length), color: 'text-orange-400' },
        ].map(item => (
          <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
            <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{item.label}</p>
            <p className={`text-xl font-bold ${item.color}`}>{item.value}</p>
          </div>
        ))}
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-green-400 font-semibold text-sm uppercase tracking-wider">NEAT Genome Pool</h2>
            <p className="text-gray-500 text-xs mt-0.5">Fitness = Sharpe × Win Rate × (1 − Max Drawdown)</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span>Avg fitness: <span className="text-white font-mono">{avgFitness.toFixed(4)}</span></span>
            {speciesSet.size > 0 && <span>Species: <span className="text-purple-400 font-mono">{speciesSet.size}</span></span>}
          </div>
        </div>

        <div className="px-4 py-2 border-b border-gray-800/60 flex flex-wrap gap-2 text-xs">
          {Object.entries(STATUS_COLOR).map(([s, cls]) => (
            <span key={s} className={`px-1.5 py-0.5 rounded border ${cls}`}>{s}</span>
          ))}
          <span className="text-gray-600 ml-1">← lifecycle states</span>
        </div>

        {genomes.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-gray-500 text-sm">No genomes evolved yet</p>
            <p className="text-gray-600 text-xs mt-1">NEAT evolution runs every 3 hours — initial population will appear shortly</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[600px]">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800 bg-gray-900/80">
                  <th className="text-left px-4 py-2.5">Rank</th>
                  <th className="text-left px-4 py-2.5">Genome ID</th>
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5">Status</th>
                  <th className="text-left px-4 py-2.5 w-44">Fitness</th>
                  <th className="hidden md:table-cell text-left px-4 py-2.5">Gen</th>
                  <th className="hidden md:table-cell text-left px-4 py-2.5">Nodes</th>
                  <th className="hidden lg:table-cell text-left px-4 py-2.5">Connections</th>
                  <th className="text-left px-4 py-2.5">Win Rate</th>
                  <th className="hidden sm:table-cell text-left px-4 py-2.5">Sharpe</th>
                </tr>
              </thead>
              <tbody>
                {genomes.map((g, i) => (
                  <tr key={g.genome_id} className={`border-b border-gray-800/40 hover:bg-gray-800/25 transition-colors ${i === 0 ? 'bg-green-950/20' : ''}`}>
                    <td className="px-4 py-2.5">
                      <span className={`font-bold ${i === 0 ? 'text-yellow-400' : i < 3 ? 'text-green-400' : 'text-gray-500'}`}>
                        {i === 0 ? '★' : `#${i + 1}`}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-gray-400 max-w-[120px] truncate">{g.genome_id}</td>
                    <td className="px-4 py-2.5 text-white font-semibold">{g.symbol ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={g.status ?? 'TRIAL'} />
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-20 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-green-700 to-green-400"
                            style={{ width: `${bestFitness > 0 ? Math.min(100, (g.fitness / bestFitness) * 100) : 0}%` }} />
                        </div>
                        <span className={`font-mono tabular-nums ${i === 0 ? 'text-green-400 font-bold' : 'text-gray-300'}`}>{g.fitness?.toFixed(4)}</span>
                      </div>
                    </td>
                    <td className="hidden md:table-cell px-4 py-2.5 text-blue-400 tabular-nums">{g.generation ?? '—'}</td>
                    <td className="hidden md:table-cell px-4 py-2.5 text-purple-400 tabular-nums">{g.nodes ?? '—'}</td>
                    <td className="hidden lg:table-cell px-4 py-2.5 text-orange-400 tabular-nums">{g.connections ?? '—'}</td>
                    <td className={`px-4 py-2.5 tabular-nums ${g.win_rate != null ? ((g.win_rate ?? 0) >= 0.52 ? 'text-green-400' : 'text-gray-400') : 'text-gray-600'}`}>
                      {g.win_rate != null ? `${((g.win_rate ?? 0) * 100).toFixed(1)}%` : '—'}
                    </td>
                    <td className={`hidden sm:table-cell px-4 py-2.5 tabular-nums font-mono ${g.sharpe_ratio != null ? ((g.sharpe_ratio ?? 0) >= 1.5 ? 'text-green-400' : 'text-gray-400') : 'text-gray-600'}`}>
                      {g.sharpe_ratio != null ? (g.sharpe_ratio ?? 0).toFixed(3) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div>
            <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">Shadow Trading Universes</h2>
            <p className="text-gray-500 text-xs mt-0.5">3 parallel paper-trading environments — best performer promotes to live capital</p>
          </div>
          <span className="text-xs text-gray-600">Promotion: ≥100 trades · Sharpe ≥1.5 · WR ≥52% · DD &lt;10%</span>
        </div>
        {shadows.length === 0 ? (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 text-center">
            <p className="text-gray-500 text-sm">Shadow system warming up...</p>
            <p className="text-gray-600 text-xs mt-1">Requires at least 100 paper trades to evaluate</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {shadows.map((s, i) => <ShadowCard key={s.shadow_id} s={s} rank={i} />)}
          </div>
        )}
      </div>
    </div>
  )
}
