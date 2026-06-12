'use client'
import { useCallback, useEffect, useState } from 'react'
import { useStreamInvalidate } from '@/hooks/useStream'

interface TradingDecision {
  action?: string
  entry?: number | null
  stop_loss?: number | null
  take_profit?: number[]
  risk_score?: number
  win_probability?: number
  approved?: boolean
  position_size_pct?: number
  reason?: string[]
}

interface Signal {
  symbol: string; direction: string; confidence: number; kelly_fraction: number
  regime: string; crisis_level: number; drift_status: string; timestamp?: number
  consensus_reasoning?: string; vix?: number
  decision?: TradingDecision
  decision_reasons?: string[]
  is_valid?: boolean
  trade_action?: string
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
const DRIFT_COLOR: Record<string, string> = {
  STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500',
}
const DRIFT_KELLY: Record<string, number> = { STABLE: 0.50, WARNING: 0.35, DRIFTING: 0.20, SHOCK: 0.0 }
const CRISIS_COLOR = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-500 animate-pulse']
const CRISIS_LABEL = ['Normal', 'Caution', 'Warning', 'Alarm', 'CRISIS']
const CRISIS_MULT = [1.0, 0.65, 0.35, 0.10, 0.0]

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'bg-green-500' : pct >= 65 ? 'bg-orange-500' : 'bg-yellow-600'
  const textColor = pct >= 80 ? 'text-green-400' : pct >= 65 ? 'text-orange-400' : 'text-yellow-400'
  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-gray-500">Confidence</span>
        <span className={`text-sm font-bold ${textColor}`}>{pct}%</span>
      </div>
      <div className="relative w-full h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
        <div className="absolute top-0 h-full w-0.5 bg-yellow-500/40" style={{ left: '60%' }} />
      </div>
      <p className="text-gray-700 text-[10px] mt-0.5 text-right">60% gate</p>
    </div>
  )
}

function SignalCard({ sig }: { sig: Signal }) {
  const dir = sig.direction
  const crisis = sig.crisis_level ?? 0
  const drift = sig.drift_status ?? 'STABLE'
  const kellyPct = (sig.kelly_fraction ?? 0) * 100
  const effectivePosSize = Math.min(5, kellyPct * CRISIS_MULT[crisis] * (DRIFT_KELLY[drift] ?? 0.5) / 0.5) // rough approximation

  return (
    <div className={`bg-gray-900 rounded-lg border overflow-hidden transition-all hover:border-gray-600 ${
      dir === 'long' ? 'border-green-900/60' : dir === 'short' ? 'border-red-900/60' : 'border-gray-800'
    }`}>
      <div className="px-4 py-3 flex items-center justify-between border-b border-gray-800/60">
        <div className="flex items-center gap-3">
          <a href={`/coin/${sig.symbol}`} className="font-bold text-white text-base hover:text-orange-400 transition-colors">{sig.symbol}</a>
          <span className={`px-2 py-0.5 rounded text-xs font-bold ${DIR_STYLE[dir]}`}>
            {dir === 'long' ? '▲ LONG' : dir === 'short' ? '▼ SHORT' : '— FLAT'}
          </span>
        </div>
        {sig.timestamp && (
          <span className="text-gray-600 text-xs">{new Date(sig.timestamp * 1000 > 1e12 ? sig.timestamp : sig.timestamp * 1000).toLocaleTimeString()}</span>
        )}
      </div>

      <div className="px-4 py-3 space-y-3">
        <ConfidenceMeter value={sig.confidence} />

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-gray-500 mb-0.5">Kelly Size</p>
            <p className="text-white font-bold font-mono">{kellyPct.toFixed(1)}%</p>
            <p className="text-gray-600 text-[10px] mt-0.5">raw (pre-crisis/drift)</p>
          </div>
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-gray-500 mb-0.5">Crisis Level</p>
            <p className={`font-bold ${CRISIS_COLOR[crisis] ?? 'text-gray-400'}`}>
              {CRISIS_LABEL[crisis] ?? `L${crisis}`}
              <span className="text-gray-600 text-[10px] ml-1 font-normal">({(CRISIS_MULT[crisis] * 100).toFixed(0)}%)</span>
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs gap-2">
          <span className={`px-2 py-0.5 rounded border text-xs font-medium ${REGIME_STYLE[sig.regime] ?? 'text-gray-400 bg-gray-800/40 border-gray-700/40'}`}>
            {sig.regime?.replace('_', ' ') ?? 'unknown'}
          </span>
          <span className={`font-semibold text-xs ${DRIFT_COLOR[drift] ?? 'text-gray-400'}`}>
            {drift === 'STABLE' ? '✓' : drift === 'SHOCK' ? '⚠' : '~'} {drift}
            <span className="text-gray-600 font-normal ml-1">({(DRIFT_KELLY[drift] ?? 0.5) * 100}% Kelly)</span>
          </span>
        </div>

        {sig.decision && (sig.decision.entry || sig.decision.stop_loss) && (
          <div className="grid grid-cols-2 gap-2 text-xs">
            {sig.decision.entry != null && (
              <div className="bg-gray-800/40 rounded p-2">
                <p className="text-gray-500 mb-0.5">Entry</p>
                <p className="text-white font-mono font-bold">{sig.decision.entry}</p>
              </div>
            )}
            {sig.decision.stop_loss != null && (
              <div className="bg-gray-800/40 rounded p-2">
                <p className="text-gray-500 mb-0.5">Stop</p>
                <p className="text-red-400 font-mono font-bold">{sig.decision.stop_loss}</p>
              </div>
            )}
            {sig.decision.take_profit && sig.decision.take_profit.length > 0 && (
              <div className="col-span-2 bg-gray-800/40 rounded p-2">
                <p className="text-gray-500 mb-0.5">Take Profit</p>
                <p className="text-green-400 font-mono text-[11px]">{sig.decision.take_profit.join(' → ')}</p>
              </div>
            )}
            {(sig.decision.risk_score != null || sig.decision.win_probability != null) && (
              <div className="col-span-2 flex gap-3 text-[11px] text-gray-500">
                {sig.decision.win_probability != null && (
                  <span>P(win) <span className="text-blue-400 font-bold">{Math.round(sig.decision.win_probability * 100)}%</span></span>
                )}
                {sig.decision.risk_score != null && (
                  <span>Risk <span className="text-orange-400 font-bold">{sig.decision.risk_score.toFixed(2)}</span></span>
                )}
                {sig.decision.approved != null && (
                  <span>{sig.decision.approved ? '✓ Onaylı' : '✗ Red'}</span>
                )}
              </div>
            )}
          </div>
        )}

        {(sig.decision?.reason?.length || sig.decision_reasons?.length) && (
          <div className="pt-1 border-t border-gray-800/40">
            <p className="text-gray-600 text-[10px] uppercase tracking-wider mb-1">Karar nedenleri</p>
            <p className="text-gray-400 text-xs leading-relaxed line-clamp-3">
              {(sig.decision?.reason ?? sig.decision_reasons ?? []).join(' · ')}
            </p>
          </div>
        )}

        {sig.consensus_reasoning && (
          <div className="pt-1 border-t border-gray-800/40">
            <p className="text-gray-600 text-[10px] uppercase tracking-wider mb-1">AI Reasoning</p>
            <p className="text-gray-400 text-xs leading-relaxed line-clamp-3">{sig.consensus_reasoning}</p>
          </div>
        )}
      </div>
    </div>
  )
}

const PAGE_SIZE = 30

export default function SignalsPage() {
  const [allSignals, setAllSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [showFlat, setShowFlat] = useState(false)
  const [page, setPage] = useState(0)

  const fetchData = useCallback(async () => {
    try {
      const data = await fetch('/api/signals').then(r => r.json())
      const arr = (Array.isArray(data) ? data : []) as Signal[]
      setAllSignals(arr.sort((a, b) => b.confidence - a.confidence))
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 60000)
    return () => clearInterval(t)
  }, [fetchData])

  useStreamInvalidate({
    hints: ['signal', 'agents'],
    debounceMs: 500,
    onEvent: () => { void fetchData() },
  })

  const active = allSignals.filter(s => s.direction !== 'flat')
  const flat = allSignals.filter(s => s.direction === 'flat')
  const avgConf = active.length > 0 ? active.reduce((s, x) => s + x.confidence, 0) / active.length : 0
  const longCount = active.filter(s => s.direction === 'long').length
  const shortCount = active.filter(s => s.direction === 'short').length

  const displayed = showFlat ? allSignals : active
  const totalPages = Math.ceil(displayed.length / PAGE_SIZE)
  const paged = displayed.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-pulse text-orange-400">◉</span>
      <span className="text-sm">Fetching signals...</span>
    </div>
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">Active Signals</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            Regime + 13 agent + risk engine · karar: entry/stop/TP · eşik ≥ 60%
          </p>
        </div>
        <span className="text-xs text-gray-600 shrink-0">{lastUpdate ? `${lastUpdate} · 5s` : '5s refresh'}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        {[
          { label: 'Active Signals', value: String(active.length), color: 'text-orange-400' },
          { label: 'Long', value: String(longCount), color: 'text-green-400' },
          { label: 'Short', value: String(shortCount), color: 'text-red-400' },
          { label: 'Avg Confidence', value: active.length > 0 ? `${Math.round(avgConf * 100)}%` : '—', color: avgConf >= 0.7 ? 'text-green-400' : 'text-orange-400' },
        ].map(item => (
          <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
            <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{item.label}</p>
            <p className={`text-xl font-bold ${item.color}`}>{item.value}</p>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => setShowFlat(v => !v)}
          className={`px-3 py-1.5 text-xs rounded border transition-colors ${showFlat
            ? 'bg-gray-700/40 text-gray-300 border-gray-600'
            : 'bg-gray-800/80 text-gray-500 border-transparent hover:text-gray-300'}`}>
          {showFlat ? 'Hide flat signals' : `Show flat signals (${flat.length})`}
        </button>
        {flat.length > 0 && !showFlat && (
          <span className="text-xs text-gray-600">{flat.length} symbols suppressed — confidence below 60%</span>
        )}
      </div>

      {displayed.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
          <p className="text-gray-400 text-sm">No active signals — all positions are flat</p>
          <p className="text-gray-600 text-xs mt-1">The signal engine suppresses all signals below 60% confidence</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {paged.map(sig => <SignalCard key={sig.symbol} sig={sig} />)}
          </div>
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-xs mt-2">
              <span className="text-gray-500">{displayed.length} sinyal · sayfa {page + 1}/{totalPages}</span>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                  className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">‹ Önceki</button>
                <span className="px-2 text-gray-600">{page + 1} / {totalPages}</span>
                <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                  className="px-3 py-1.5 rounded bg-gray-800 text-gray-400 disabled:opacity-30 hover:bg-gray-700">Sonraki ›</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
