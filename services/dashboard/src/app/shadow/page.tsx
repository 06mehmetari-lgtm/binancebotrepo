'use client'
import { useCallback, useEffect, useState } from 'react'
import { ShadowEquityChart, type ShadowCurve } from '@/components/ShadowEquityChart'
import { useStreamInvalidate } from '@/hooks/useStream'

interface Shadow {
  shadow_id: string
  sharpe: number
  win_rate: number
  trades: number
  return: number
  promotion_ready: boolean
  max_drawdown?: number
  checks?: Record<string, boolean>
}

const PROMO_CRITERIA = [
  { key: 'trades', label: 'Min Trades', target: 100, unit: '', description: 'Statistical significance requires 100+ closed trades' },
  { key: 'sharpe', label: 'Sharpe Ratio', target: 1.5, unit: '', description: 'Risk-adjusted return must exceed 1.5' },
  { key: 'win_rate', label: 'Win Rate', target: 52, unit: '%', description: 'Must win more than half of all trades' },
  { key: 'max_drawdown', label: 'Max Drawdown', target: 10, unit: '%', invert: true, description: 'Peak-to-trough loss must stay below 10%' },
]

function CriteriaRow({ label, pct, met, invert, display, description }: {
  label: string; pct: number; met: boolean; invert?: boolean; display: string; description?: string
}) {
  return (
    <div className="group flex items-center gap-2 text-xs relative">
      <span className={`w-4 shrink-0 text-sm ${met ? 'text-green-400' : 'text-gray-600'}`}>{met ? '✓' : '○'}</span>
      <span className="text-gray-400 w-28 shrink-0">{label}</span>
      <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${met ? 'bg-green-500' : invert ? 'bg-red-500' : 'bg-orange-500/60'}`}
          style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className={`font-mono text-right w-28 shrink-0 ${met ? 'text-green-400' : 'text-gray-400'}`}>{display}</span>
      {description && (
        <div className="hidden group-hover:block absolute left-32 top-5 z-10 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 text-xs whitespace-nowrap pointer-events-none shadow-lg">
          {description}
        </div>
      )}
    </div>
  )
}

function MetricBox({ label, value, color, sub }: { label: string; value: string; color: string; sub?: string }) {
  return (
    <div className="bg-gray-800/50 rounded-lg p-3">
      <p className="text-gray-500 text-xs mb-1">{label}</p>
      <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
      {sub && <p className="text-gray-600 text-xs mt-0.5">{sub}</p>}
    </div>
  )
}

function ShadowCard({ s, rank }: { s: Shadow; rank: number }) {
  const dd = (s.max_drawdown ?? 0) * 100
  const wr = (s.win_rate ?? 0) * 100
  const ret = (s.return ?? 0) * 100

  const rows = [
    {
      label: 'Min Trades',
      pct: Math.min(100, (s.trades / 100) * 100),
      met: s.trades >= 100,
      display: `${s.trades} / 100`,
      description: 'Statistical significance requires 100+ closed trades',
    },
    {
      label: 'Sharpe Ratio',
      pct: Math.min(100, ((s.sharpe ?? 0) / 1.5) * 100),
      met: (s.sharpe ?? 0) >= 1.5,
      display: `${(s.sharpe ?? 0).toFixed(3)} / ≥ 1.5`,
      description: 'Risk-adjusted return must exceed 1.5',
    },
    {
      label: 'Win Rate',
      pct: Math.min(100, (wr / 52) * 100),
      met: wr >= 52,
      display: `${wr.toFixed(1)}% / ≥ 52%`,
      description: 'Must win more than 52% of trades',
    },
    {
      label: 'Max Drawdown',
      pct: dd <= 10 ? 100 : Math.min(100, (10 / dd) * 100),
      met: dd <= 10,
      invert: true,
      display: `${dd.toFixed(1)}% / < 10%`,
      description: 'Peak-to-trough loss must stay below 10%',
    },
  ]

  const passCount = rows.filter(r => r.met).length
  const progressPct = (passCount / rows.length) * 100

  return (
    <div className={`bg-gray-900 rounded-xl border overflow-hidden transition-all ${
      s.promotion_ready
        ? 'border-yellow-500/70 shadow-lg shadow-yellow-900/20'
        : rank === 0
        ? 'border-green-800/60'
        : 'border-gray-800'
    }`}>
      <div className="px-4 py-3 border-b border-gray-800/60 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`text-2xl font-black w-8 ${rank === 0 ? 'text-yellow-400' : rank === 1 ? 'text-gray-400' : 'text-gray-600'}`}>
            #{rank + 1}
          </span>
          <div>
            <p className="font-bold text-white text-sm">{s.shadow_id}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <div className="w-20 h-1 bg-gray-800 rounded-full overflow-hidden">
                <div className="h-full bg-orange-500 rounded-full" style={{ width: `${progressPct}%` }} />
              </div>
              <span className="text-gray-500 text-xs">{passCount}/{rows.length} criteria</span>
            </div>
          </div>
        </div>
        {s.promotion_ready
          ? <span className="bg-yellow-500/20 text-yellow-300 border border-yellow-500/40 px-2.5 py-1 rounded text-xs font-bold animate-pulse">PROMOTION READY</span>
          : <span className="bg-gray-800/80 text-gray-500 text-xs px-2.5 py-1 rounded">Paper Trading</span>}
      </div>

      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-2">
          <MetricBox
            label="Total Return"
            value={`${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%`}
            color={ret >= 0 ? 'text-green-400' : 'text-red-400'}
          />
          <MetricBox
            label="Sharpe Ratio"
            value={(s.sharpe ?? 0).toFixed(3)}
            color={(s.sharpe ?? 0) >= 1.5 ? 'text-green-400' : (s.sharpe ?? 0) >= 1 ? 'text-yellow-400' : 'text-gray-400'}
            sub={(s.sharpe ?? 0) >= 1.5 ? 'Target met' : 'Below target'}
          />
          <MetricBox
            label="Win Rate"
            value={`${wr.toFixed(1)}%`}
            color={wr >= 52 ? 'text-green-400' : 'text-gray-400'}
          />
          <MetricBox
            label="Max Drawdown"
            value={`${dd.toFixed(2)}%`}
            color={dd <= 10 ? 'text-green-400' : dd <= 15 ? 'text-yellow-400' : 'text-red-400'}
          />
        </div>

        <div>
          <p className="text-gray-600 text-xs uppercase tracking-wider mb-2.5">Promotion Criteria</p>
          <div className="space-y-2">
            {rows.map(r => <CriteriaRow key={r.label} {...r} />)}
          </div>
        </div>

        <div className="pt-2 border-t border-gray-800/50 flex items-center justify-between text-xs">
          <span className="text-gray-500">{s.trades} trades simulated</span>
          {s.promotion_ready
            ? <span className="text-yellow-400 font-semibold">Ready to promote to live trading</span>
            : <span className="text-gray-600">{100 - Math.min(100, s.trades)} more trades needed</span>}
        </div>
      </div>
    </div>
  )
}

function ComparisonTable({ shadows }: { shadows: Shadow[] }) {
  if (!shadows.length) return null
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-x-auto">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-gray-400 font-semibold text-xs uppercase tracking-wider">Side-by-Side Comparison</h2>
      </div>
      <table className="w-full text-xs min-w-[600px]">
        <thead>
          <tr className="text-gray-500 border-b border-gray-800/60 bg-gray-900/60">
            <th className="text-left px-4 py-2.5">Universe</th>
            <th className="text-left px-4 py-2.5">Trades</th>
            <th className="text-left px-4 py-2.5">Sharpe</th>
            <th className="text-left px-4 py-2.5">Win Rate</th>
            <th className="text-left px-4 py-2.5">Return</th>
            <th className="text-left px-4 py-2.5">Max DD</th>
            <th className="text-left px-4 py-2.5">Status</th>
          </tr>
        </thead>
        <tbody>
          {shadows.map((s, i) => {
            const dd = (s.max_drawdown ?? 0) * 100
            const wr = (s.win_rate ?? 0) * 100
            const ret = (s.return ?? 0) * 100
            return (
              <tr key={s.shadow_id} className={`border-b border-gray-800/30 hover:bg-gray-800/20 ${i === 0 ? 'bg-green-950/10' : ''}`}>
                <td className="px-4 py-2.5">
                  <span className="font-bold text-white">{s.shadow_id}</span>
                  {i === 0 && <span className="ml-1.5 text-yellow-500/80 text-xs">★ BEST</span>}
                </td>
                <td className={`px-4 py-2.5 font-mono ${s.trades >= 100 ? 'text-green-400' : 'text-gray-400'}`}>{s.trades}</td>
                <td className={`px-4 py-2.5 font-mono ${(s.sharpe ?? 0) >= 1.5 ? 'text-green-400' : 'text-gray-400'}`}>{(s.sharpe ?? 0).toFixed(3)}</td>
                <td className={`px-4 py-2.5 font-mono ${wr >= 52 ? 'text-green-400' : 'text-gray-400'}`}>{wr.toFixed(1)}%</td>
                <td className={`px-4 py-2.5 font-mono ${ret >= 0 ? 'text-green-400' : 'text-red-400'}`}>{ret >= 0 ? '+' : ''}{ret.toFixed(2)}%</td>
                <td className={`px-4 py-2.5 font-mono ${dd <= 10 ? 'text-green-400' : 'text-red-400'}`}>{dd.toFixed(2)}%</td>
                <td className="px-4 py-2.5">
                  {s.promotion_ready
                    ? <span className="text-yellow-400 font-bold">READY</span>
                    : <span className="text-gray-600">Training</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function ShadowPage() {
  const [data, setData] = useState<Shadow[]>([])
  const [equityCurves, setEquityCurves] = useState<Record<string, ShadowCurve[]>>({})
  const [startEquity, setStartEquity] = useState(10000)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [streamLive, setStreamLive] = useState(false)

  const fetchData = useCallback(() => {
    fetch('/api/shadow')
      .then(r => r.json())
      .then(d => {
        const arr = (Array.isArray(d) ? d : d.leaderboard ?? []) as Shadow[]
        setData([...arr].sort((a, b) => (b.sharpe ?? 0) - (a.sharpe ?? 0)))
        if (d.equity_curves) setEquityCurves(d.equity_curves)
        if (d.start_equity) setStartEquity(d.start_equity)
        setLastUpdate(new Date().toLocaleTimeString())
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const { connected } = useStreamInvalidate({
    hints: ['trade_closed', 'portfolio'],
    onEvent: fetchData,
    debounceMs: 300,
  })

  useEffect(() => { setStreamLive(connected) }, [connected])
  useEffect(() => { fetchData(); const t = setInterval(fetchData, 10000); return () => clearInterval(t) }, [fetchData])

  const anyReady = data.some(s => s.promotion_ready)
  const bestSharpe = data[0]?.sharpe ?? 0

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">Shadow Trading Universes</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            3 parallel paper-trading environments running simultaneously — best performer earns live capital
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-gray-600 flex items-center gap-1.5 justify-end">
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${streamLive ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            {lastUpdate ? `${lastUpdate} · ${streamLive ? 'canlı' : '10s'}` : '10s refresh'}
          </p>
          {anyReady && <p className="text-yellow-400 text-xs font-bold mt-0.5 animate-pulse">PROMOTION CANDIDATE DETECTED</p>}
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <p className="text-gray-500 text-xs uppercase tracking-wider mb-3">Promotion Gate — ALL 4 must be met</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {PROMO_CRITERIA.map(c => (
            <div key={c.key} className="bg-gray-800/50 rounded-lg p-3">
              <p className="text-gray-500 text-xs">{c.label}</p>
              <p className="text-white font-bold text-base font-mono mt-1">
                {c.invert ? '< ' : '≥ '}{c.target}{c.unit}
              </p>
              <p className="text-gray-600 text-xs mt-1 leading-relaxed">{c.description}</p>
            </div>
          ))}
        </div>
      </div>

      {!loading && Object.keys(equityCurves).some(k => (equityCurves[k]?.length ?? 0) > 1) && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">📈 Shadow Equity (zaman serisi)</h2>
            <span className="text-xs text-gray-600">SHADOW_A / B / C karşılaştırma</span>
          </div>
          <div className="p-4">
            <ShadowEquityChart curves={equityCurves} startEquity={startEquity} />
          </div>
        </div>
      )}

      {!loading && data.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
          {[
            { label: 'Universes', value: String(data.length), color: 'text-blue-400' },
            { label: 'Best Sharpe', value: bestSharpe.toFixed(3), color: bestSharpe >= 1.5 ? 'text-green-400' : 'text-yellow-400' },
            { label: 'Total Trades', value: String(data.reduce((s, u) => s + u.trades, 0)), color: 'text-orange-400' },
            { label: 'Promotion Ready', value: anyReady ? 'YES' : 'NO', color: anyReady ? 'text-yellow-400 animate-pulse' : 'text-gray-500' },
          ].map(item => (
            <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
              <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{item.label}</p>
              <p className={`text-xl font-bold ${item.color}`}>{item.value}</p>
            </div>
          ))}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 gap-3 text-gray-500">
          <span className="animate-spin text-blue-400 text-lg">◌</span>
          <span className="text-sm">Loading shadow universes...</span>
        </div>
      ) : data.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
          <p className="text-gray-400 text-sm font-semibold">Shadow system is warming up</p>
          <p className="text-gray-600 text-xs mt-2 max-w-xs mx-auto">
            The shadow system needs to simulate at least 100 paper trades before performance can be evaluated.
            This typically takes 2–4 weeks of operation.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {data.map((s, i) => <ShadowCard key={s.shadow_id} s={s} rank={i} />)}
          </div>
          <ComparisonTable shadows={data} />
        </div>
      )}
    </div>
  )
}
