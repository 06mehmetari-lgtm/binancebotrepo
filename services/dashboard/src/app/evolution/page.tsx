'use client'
import { useEffect, useState } from 'react'

interface Genome { genome_id: string; fitness: number; generation: number; nodes: number; connections: number; symbol: string }
interface Shadow { shadow_id: string; sharpe: number; win_rate: number; trades: number; return: number; promotion_ready: boolean; max_drawdown: number }
interface Status { active_symbol_count: number; total_signals: number; avg_confidence: number; best_genome_fitness: number }
interface EvoData { genomes: Genome[]; shadow_leaderboard: Shadow[] }

const PROMOTION_CRITERIA = { trades: 100, sharpe: 1.5, win_rate: 0.52, max_drawdown: 0.10 }

function ProgressBar({ value, max, color, label }: { value: number; max: number; color: string; label: string }) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-500">{label}</span>
        <span className="text-gray-300 font-mono">{value}{typeof value === 'number' && value < 2 ? '' : ''}</span>
      </div>
      <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ShadowCard({ s }: { s: Shadow }) {
  const checks = [
    { label: 'Trades', value: s.trades, target: PROMOTION_CRITERIA.trades, met: s.trades >= PROMOTION_CRITERIA.trades, display: `${s.trades} / ${PROMOTION_CRITERIA.trades}` },
    { label: 'Sharpe Ratio', value: s.sharpe, target: PROMOTION_CRITERIA.sharpe, met: s.sharpe >= PROMOTION_CRITERIA.sharpe, display: `${s.sharpe?.toFixed(3)} / ${PROMOTION_CRITERIA.sharpe}` },
    { label: 'Win Rate', value: s.win_rate * 100, target: PROMOTION_CRITERIA.win_rate * 100, met: s.win_rate >= PROMOTION_CRITERIA.win_rate, display: `${(s.win_rate * 100).toFixed(1)}% / ${PROMOTION_CRITERIA.win_rate * 100}%` },
    { label: 'Max Drawdown', value: s.max_drawdown * 100, target: PROMOTION_CRITERIA.max_drawdown * 100, met: s.max_drawdown <= PROMOTION_CRITERIA.max_drawdown, display: `${(s.max_drawdown * 100).toFixed(1)}% / <${PROMOTION_CRITERIA.max_drawdown * 100}%`, invert: true },
  ]
  const passCount = checks.filter(c => c.met).length

  return (
    <div className={`bg-gray-900 rounded-lg border overflow-hidden transition-all ${s.promotion_ready ? 'border-yellow-500/60' : 'border-gray-800'}`}>
      <div className="px-4 py-3 border-b border-gray-800/60 flex items-center justify-between">
        <div>
          <span className="font-bold text-white">{s.shadow_id}</span>
          <span className="ml-2 text-gray-500 text-xs">{passCount}/{checks.length} criteria</span>
        </div>
        {s.promotion_ready
          ? <span className="bg-yellow-500/20 text-yellow-400 border border-yellow-500/40 px-2 py-0.5 rounded text-xs font-bold animate-pulse">READY FOR PROMOTION</span>
          : <span className="text-gray-600 text-xs">Paper Trading</span>}
      </div>
      <div className="p-4 space-y-2.5">
        {checks.map(c => (
          <div key={c.label} className="flex items-center gap-2 text-xs">
            <span className={`text-base ${c.met ? 'text-green-400' : 'text-gray-600'}`}>{c.met ? '✓' : '○'}</span>
            <span className="text-gray-500 w-24">{c.label}</span>
            <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
              <div className={`h-full rounded-full ${c.met ? 'bg-green-500' : c.invert ? 'bg-red-500' : 'bg-orange-500/60'}`}
                style={{ width: `${Math.min(100, c.invert ? (c.value <= (c.target) ? 100 : (c.target / c.value) * 100) : (c.value / c.target) * 100)}%` }} />
            </div>
            <span className={`font-mono text-right w-28 ${c.met ? 'text-green-400' : 'text-gray-400'}`}>{c.display}</span>
          </div>
        ))}
        <div className="pt-1 border-t border-gray-800/60 flex justify-between text-xs">
          <span className="text-gray-500">Return</span>
          <span className={`font-bold font-mono ${(s.return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>{((s.return ?? 0) * 100).toFixed(2)}%</span>
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
    } catch { /* retry */ } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 10000); return () => clearInterval(t) }, [])

  const genomes = (evo.genomes ?? []).sort((a, b) => b.fitness - a.fitness)
  const shadows = evo.shadow_leaderboard ?? []
  const bestFitness = genomes[0]?.fitness ?? 0

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-green-400">◌</span>
      <span className="text-sm">Loading evolution data...</span>
    </div>
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-white font-bold text-base">AI Learning & Evolution</h1>
        <span className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate} · 10s` : '10s refresh'}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        {[
          { label: 'Active Symbols', value: String(status.active_symbol_count ?? '—'), color: 'text-blue-400' },
          { label: 'Total Signals', value: String(status.total_signals ?? '—'), color: 'text-orange-400' },
          { label: 'Avg Confidence', value: status.avg_confidence ? `${(status.avg_confidence * 100).toFixed(1)}%` : '—', color: 'text-yellow-400' },
          { label: 'Best Genome', value: status.best_genome_fitness?.toFixed(4) ?? '—', color: 'text-green-400' },
        ].map(item => (
          <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
            <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{item.label}</p>
            <p className={`text-xl font-bold ${item.color}`}>{item.value}</p>
          </div>
        ))}
      </div>

      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-green-400 font-semibold text-sm uppercase tracking-wider">NEAT Genome Pool</h2>
          <span className="text-xs text-gray-600">{genomes.length} genomes · sorted by fitness</span>
        </div>
        {genomes.length === 0 ? (
          <p className="text-gray-500 text-sm p-4">No genomes evolved yet...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800 bg-gray-900/80">
                  <th className="text-left px-4 py-2.5">Rank</th>
                  <th className="text-left px-4 py-2.5">Genome ID</th>
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5 w-48">Fitness</th>
                  <th className="text-left px-4 py-2.5">Generation</th>
                  <th className="text-left px-4 py-2.5">Nodes</th>
                  <th className="text-left px-4 py-2.5">Connections</th>
                </tr>
              </thead>
              <tbody>
                {genomes.map((g, i) => (
                  <tr key={g.genome_id} className={`border-b border-gray-800/40 hover:bg-gray-800/25 transition-colors ${i === 0 ? 'bg-green-950/20' : ''}`}>
                    <td className="px-4 py-2.5">
                      <span className={`font-bold ${i === 0 ? 'text-yellow-400' : i < 3 ? 'text-green-400' : 'text-gray-500'}`}>
                        #{i + 1}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-gray-300">{g.genome_id}</td>
                    <td className="px-4 py-2.5 text-white font-semibold">{g.symbol}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-green-600 to-green-400"
                            style={{ width: `${bestFitness > 0 ? (g.fitness / bestFitness) * 100 : 0}%` }} />
                        </div>
                        <span className={`font-mono tabular-nums ${i === 0 ? 'text-green-400 font-bold' : 'text-gray-300'}`}>{g.fitness?.toFixed(4)}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-blue-400 tabular-nums">{g.generation}</td>
                    <td className="px-4 py-2.5 text-purple-400 tabular-nums">{g.nodes}</td>
                    <td className="px-4 py-2.5 text-orange-400 tabular-nums">{g.connections}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">Shadow Trading Universes</h2>
          <span className="text-xs text-gray-600">Promotion: ≥100 trades, Sharpe ≥1.5, WR ≥52%, DD &lt;10%</span>
        </div>
        {shadows.length === 0 ? (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 text-center">
            <p className="text-gray-500 text-sm">Shadow system warming up...</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {shadows.map(s => <ShadowCard key={s.shadow_id} s={s} />)}
          </div>
        )}
      </div>
    </div>
  )
}
