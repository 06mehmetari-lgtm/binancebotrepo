'use client'
import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import {
  ComposedChart, Area, Bar, Line, Cell, BarChart,
  XAxis, YAxis, Tooltip, CartesianGrid,
  ResponsiveContainer, ReferenceLine, ReferenceArea,
} from 'recharts'

// ── Types ────────────────────────────────────────────────────────────────────

interface KlinePoint {
  time: number; timeStr: string
  open: number; high: number; low: number; close: number; volume: number
  rsi: number; macd: number; macdSig: number; macdHist: number
  atr: number; bbUp: number; bbLow: number; bbMid: number
}

interface Features {
  rsi_14: number; rsi_7: number; macd_hist: number; adx: number
  stoch_k: number; bb_position: number; volume_ratio: number
  ob_imbalance_1: number; drift_status: string; regime: string
  funding_rate: number; oi_change_1h: number; ls_ratio_z: number
  fear_greed_norm: number; vix_level: number
  // Phase 1 — CVD
  cvd_5m?: number; cvd_1h?: number; buy_ratio_5m?: number; cvd_acceleration?: number
  liq_ratio_1h?: number; whale_buy_ratio?: number
  // Phase 1 — MTF
  rsi_14_1h?: number; trend_alignment?: number
  bull_confluence?: number; bear_confluence?: number; ob_1h?: number; os_1h?: number
  // Phase 1 — Volume Profile
  vpoc_dist_pct?: number; vah_dist_pct?: number; val_dist_pct?: number
  va_position?: number; vpoc_dominance?: number; in_value_area?: number
  // Phase 2 — ML
  ml_score?: number; atr_pct?: number
}

interface Signal {
  direction: string; confidence: number; kelly_fraction: number
  regime: string; crisis_level: number; drift_status: string
  rsi: number; macd_hist: number; volume_ratio: number
  is_valid: boolean; reject_reason: string; source: string; timestamp: number
  ml_score?: number; rl_direction?: string
  stop_pct?: number; tp_pct?: number; risk_reward?: number
}

interface Vote { agent: string; signal: string; confidence: number; reasoning: string }
interface Verdict {
  direction: string; confidence: number
  consensus_reasoning: string; dissent_risk: string
}

interface BacktestStats {
  win_rate_pct: number; sharpe_ratio: number; total_return_pct: number
  max_drawdown_pct: number; total_trades: number; profit_factor: number
  avg_win_pct: number; avg_loss_pct: number; avg_bars_held: number
  long_win_rate_pct: number; short_win_rate_pct: number
  exit_reasons: { take_profit: number; stop_loss: number; time_exit: number }
  monthly_returns: Record<string, number>
}

interface CoinData {
  symbol: string
  klines: KlinePoint[]
  ticker24h: { lastPrice: number; priceChangePercent: number; quoteVolume: number } | null
  features: Features | null
  signal: Signal | null
  rl_signal: { direction: string; confidence: number } | null
  verdict: Verdict | null
  votes: Vote[]
  backtestStats: BacktestStats | null
  levels: { sl: number | null; tp: number | null; currentPrice: number; atr: number; atrPct: number; stop_pct: number | null; tp_pct: number | null; risk_reward: number | null }
  leverageRec: { recommended: number; baseLev: number; crisisMult: number; crisisLevel: number; atrPct: number; kellyFraction: number }
}

// ── Constants ────────────────────────────────────────────────────────────────

const DIR_STYLE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-800/50',
  short: 'text-red-400 bg-red-900/30 border border-red-800/50',
  flat: 'text-gray-500 bg-gray-800/50 border border-gray-700/50',
}
const DRIFT_COLOR: Record<string, string> = {
  STABLE: 'text-green-400', WARNING: 'text-yellow-400',
  DRIFTING: 'text-orange-400', SHOCK: 'text-red-500',
}
const REGIME_COLOR: Record<string, string> = {
  trending_up: 'text-green-400', trending_down: 'text-red-400',
  ranging: 'text-blue-400', volatile: 'text-yellow-400',
}
const AGENT_META: Record<string, { emoji: string; color: string }> = {
  bull_agent:       { emoji: '🐂', color: 'text-green-400' },
  bear_agent:       { emoji: '🐻', color: 'text-red-400' },
  neutral_agent:    { emoji: '⚖️', color: 'text-gray-400' },
  technical_agent:  { emoji: '📊', color: 'text-blue-400' },
  news_agent:       { emoji: '📰', color: 'text-purple-400' },
  macro_agent:      { emoji: '🌐', color: 'text-cyan-400' },
  onchain_agent:    { emoji: '⛓️', color: 'text-orange-400' },
  risk_agent:       { emoji: '🛡️', color: 'text-yellow-400' },
  evolution_agent:  { emoji: '🧬', color: 'text-pink-400' },
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | undefined | null, dec = 2) {
  if (n == null || isNaN(n as number)) return '—'
  return (n as number).toFixed(dec)
}

function fmtPrice(p: number) {
  if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (p >= 1) return p.toFixed(4)
  return p.toFixed(6)
}

function timeAgo(ts: number) {
  const s = Math.floor((Date.now() - ts * 1000) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

// ── Chart tooltip ────────────────────────────────────────────────────────────

function PriceTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload as KlinePoint
  if (!d) return null
  return (
    <div className="bg-gray-900 border border-gray-700 rounded p-2.5 text-xs space-y-1 shadow-xl">
      <p className="text-gray-400">{d.timeStr}</p>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <span className="text-gray-500">O</span><span className="text-white">{fmtPrice(d.open)}</span>
        <span className="text-gray-500">H</span><span className="text-green-300">{fmtPrice(d.high)}</span>
        <span className="text-gray-500">L</span><span className="text-red-300">{fmtPrice(d.low)}</span>
        <span className="text-gray-500">C</span><span className="text-white font-bold">{fmtPrice(d.close)}</span>
        <span className="text-gray-500">Vol</span><span className="text-orange-300">{(d.volume / 1e6).toFixed(2)}M</span>
        {!isNaN(d.rsi) && <><span className="text-gray-500">RSI</span><span className="text-purple-300">{d.rsi.toFixed(1)}</span></>}
      </div>
    </div>
  )
}

function RSITooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const v = payload[0]?.value
  if (v == null) return null
  return (
    <div className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs">
      <span className="text-purple-300">RSI {typeof v === 'number' ? v.toFixed(1) : v}</span>
    </div>
  )
}

function MACDTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  const hist = d?.macdHist
  if (hist == null) return null
  return (
    <div className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs">
      <span className={hist >= 0 ? 'text-green-400' : 'text-red-400'}>MACD {hist?.toFixed(4)}</span>
    </div>
  )
}

// ── Sub-components ───────────────────────────────────────────────────────────

function MetricBadge({ label, value, color = 'text-white', sub }: {
  label: string; value: string; color?: string; sub?: string
}) {
  return (
    <div className="bg-gray-800/60 rounded-lg p-3 border border-gray-700/50">
      <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{label}</p>
      <p className={`font-bold text-base leading-tight ${color}`}>{value}</p>
      {sub && <p className="text-gray-600 text-xs mt-0.5">{sub}</p>}
    </div>
  )
}

function ConfidenceMeter({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'bg-green-500' : pct >= 70 ? 'bg-orange-500' : pct >= 60 ? 'bg-yellow-600' : 'bg-red-600'
  const textColor = pct >= 80 ? 'text-green-400' : pct >= 70 ? 'text-orange-400' : pct >= 60 ? 'text-yellow-400' : 'text-red-400'
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <span className={`font-bold ${textColor}`}>{pct}%</span>
      </div>
      <div className="relative h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
        {/* 60% gate line */}
        <div className="absolute top-0 bottom-0 w-px bg-gray-400/60" style={{ left: '60%' }} />
      </div>
      {pct < 60 && <p className="text-xs text-red-400">Below 60% gate — signal suppressed to FLAT</p>}
    </div>
  )
}

function AgentVoteRow({ vote }: { vote: Vote }) {
  const meta = AGENT_META[vote.agent] ?? { emoji: '🤖', color: 'text-gray-400' }
  const pct = Math.round((vote.confidence ?? 0) * 100)
  const dirStyle = DIR_STYLE[vote.signal] ?? DIR_STYLE.flat
  const barColor = vote.signal === 'long' ? 'bg-green-500' : vote.signal === 'short' ? 'bg-red-500' : 'bg-gray-600'
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-base leading-none w-5 text-center">{meta.emoji}</span>
        <span className={`text-xs font-semibold ${meta.color} flex-1 truncate`}>
          {vote.agent.replace('_agent', '').toUpperCase()}
        </span>
        <span className={`text-xs px-1.5 py-0.5 rounded font-bold border ${dirStyle}`}>
          {vote.signal?.toUpperCase()}
        </span>
        <span className="text-xs text-gray-400 w-8 text-right tabular-nums">{pct}%</span>
      </div>
      <div className="h-1 bg-gray-700 rounded-full overflow-hidden ml-7">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function LeverageGauge({ rec }: { leverageRec: CoinData['leverageRec']; rec: number }) {
  const maxLev = 20
  const pct = (rec / maxLev) * 100
  const color = rec <= 2 ? 'bg-red-500' : rec <= 5 ? 'bg-yellow-500' : rec <= 10 ? 'bg-green-500' : 'bg-orange-500'
  return (
    <div className="space-y-2">
      <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between text-xs text-gray-500">
        <span>1×</span><span>5×</span><span>10×</span><span>20×</span>
      </div>
    </div>
  )
}

// ── Monthly return mini heatmap ───────────────────────────────────────────────

function MonthlyHeatmap({ monthly }: { monthly: Record<string, number> }) {
  const entries = Object.entries(monthly).sort(([a], [b]) => a.localeCompare(b))
  if (!entries.length) return null
  return (
    <div className="grid grid-cols-6 gap-1">
      {entries.map(([month, ret]) => {
        const intensity = Math.min(Math.abs(ret) / 20, 1)
        const bg = ret > 0
          ? `rgba(34,197,94,${0.15 + intensity * 0.6})`
          : `rgba(239,68,68,${0.15 + intensity * 0.6})`
        return (
          <div key={month} className="rounded p-1.5 text-center text-xs border border-gray-700/30"
            style={{ background: bg }}>
            <p className="text-gray-400 text-[10px]">{month.slice(2)}</p>
            <p className={`font-bold ${ret >= 0 ? 'text-green-300' : 'text-red-300'}`}>
              {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
            </p>
          </div>
        )
      })}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function CoinPage() {
  const params = useParams()
  const symbol = (params.symbol as string)?.toUpperCase() ?? ''
  const [data, setData] = useState<CoinData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [chartType, setChartType] = useState<'price' | 'rsi' | 'macd'>('price')
  const [leverageVal, setLeverageVal] = useState(1)

  const fetchData = useCallback(async () => {
    if (!symbol) return
    try {
      const res = await fetch(`/api/coin/${symbol}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const d: CoinData = await res.json()
      setData(d)
      setLeverageVal(d.leverageRec.recommended)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 10_000)
    return () => clearInterval(t)
  }, [fetchData])

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400 text-xl">⚡</span>
      <span>Loading {symbol}...</span>
    </div>
  )

  if (error) return (
    <div className="flex items-center justify-center mt-32 text-red-400">
      <span>Error: {error}</span>
    </div>
  )

  if (!data) return null

  const { klines, ticker24h, features, signal, rl_signal, verdict, votes, backtestStats, levels, leverageRec } = data
  const price = ticker24h?.lastPrice ?? levels.currentPrice
  const change = ticker24h?.priceChangePercent ?? 0
  const changeColor = change >= 0 ? 'text-green-400' : 'text-red-400'
  const dir = signal?.direction ?? 'flat'
  const conf = signal?.confidence ?? 0
  const longVotes = votes.filter(v => v.signal === 'long').length
  const shortVotes = votes.filter(v => v.signal === 'short').length
  const flatVotes = votes.filter(v => v.signal === 'flat').length

  // Chart data (last 100 bars for readability)
  const chartData = klines.slice(-100)

  // Determine price range for Y axis — guard against empty array (Infinity crash)
  const priceMin = chartData.length > 0
    ? Math.min(...chartData.map(k => Math.min(k.low, k.bbLow || k.close))) * 0.998
    : 0
  const priceMax = chartData.length > 0
    ? Math.max(...chartData.map(k => Math.max(k.high, k.bbUp || k.close))) * 1.002
    : 1
  const volumeMax = chartData.length > 0
    ? Math.max(...chartData.map(k => k.volume)) * 4
    : 1

  // X axis: show every ~10th label
  const xTick = Math.ceil(chartData.length / 10)

  // Tick formatter
  const xFmt = (v: string) => {
    const idx = chartData.findIndex(k => k.timeStr === v)
    return idx % xTick === 0 ? v.split(',')[0] : ''
  }

  const positionSizeUsd = 10000 * leverageRec.kellyFraction * leverageVal
  const crisisLabels = ['Normal', 'Caution', 'Warning', 'Alarm', 'CRISIS']

  return (
    <div className="space-y-4 max-w-screen-2xl mx-auto">

      {/* ── Back + Header ── */}
      <div className="flex items-center gap-3 flex-wrap">
        <a href="/" className="text-gray-500 hover:text-white text-sm flex items-center gap-1 transition-colors">
          ← Dashboard
        </a>
        <span className="text-gray-700">/</span>
        <span className="text-gray-400 text-sm">{symbol}</span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-black text-white">{symbol.replace('USDT', '')}<span className="text-gray-600">/USDT</span></h1>
        <span className="text-2xl font-mono font-bold text-white">{fmtPrice(price)}</span>
        <span className={`text-lg font-bold font-mono ${changeColor}`}>
          {change >= 0 ? '+' : ''}{change.toFixed(2)}%
        </span>
        <span className={`px-3 py-1 rounded-lg font-black text-sm border ${DIR_STYLE[dir]}`}>
          {dir.toUpperCase()}
        </span>
        {signal?.is_valid === false && (
          <span className="text-xs text-red-400 bg-red-900/20 border border-red-800/40 px-2 py-0.5 rounded">
            ✗ {signal.reject_reason}
          </span>
        )}
        {ticker24h && (
          <span className="text-xs text-gray-600 ml-auto">
            24h Vol: ${(ticker24h.quoteVolume / 1e6).toFixed(0)}M · 10s refresh
          </span>
        )}
      </div>

      {/* ── Two-column layout: Chart + AI Panel ── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">

        {/* ── Left: Charts ── */}
        <div className="xl:col-span-2 space-y-3">

          {/* Chart type tabs */}
          <div className="flex gap-1">
            {(['price', 'rsi', 'macd'] as const).map(t => (
              <button key={t} onClick={() => setChartType(t)}
                className={`text-xs px-3 py-1.5 rounded font-semibold uppercase tracking-wide transition-all ${
                  chartType === t
                    ? 'bg-orange-500/20 text-orange-400 border border-orange-500/40'
                    : 'text-gray-500 hover:text-gray-300 border border-transparent'
                }`}>
                {t === 'price' ? '📈 Price' : t === 'rsi' ? '📊 RSI' : '〰 MACD'}
              </button>
            ))}
          </div>

          {/* ── Price Chart ── */}
          {chartType === 'price' && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-800 flex items-center justify-between">
                <span className="text-sm font-semibold text-white">{symbol} · 1H · Last 100 bars</span>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  {levels.sl && <span className="text-red-400">SL {fmtPrice(levels.sl)}</span>}
                  {levels.tp && <span className="text-green-400">TP {fmtPrice(levels.tp)}</span>}
                </div>
              </div>

              {/* Price area */}
              <div style={{ height: 320 }} className="px-2 pt-3">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 5, right: 15, bottom: 0, left: 5 }}>
                    <defs>
                      <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={dir === 'short' ? '#ef4444' : '#f97316'} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={dir === 'short' ? '#ef4444' : '#f97316'} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                    <XAxis dataKey="timeStr" tickFormatter={xFmt} tick={{ fill: '#6b7280', fontSize: 10 }}
                      tickLine={false} axisLine={{ stroke: '#374151' }} />
                    <YAxis domain={[priceMin, priceMax]} tickFormatter={v => fmtPrice(v)}
                      tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false}
                      axisLine={false} width={70} />
                    <Tooltip content={<PriceTooltip />} />

                    {/* BB bands as dashed lines */}
                    <Line dataKey="bbUp" stroke="#3b82f6" strokeWidth={0.7} dot={false} strokeDasharray="3 2" />
                    <Line dataKey="bbMid" stroke="#4b5563" strokeWidth={0.7} dot={false} strokeDasharray="5 3" />
                    <Line dataKey="bbLow" stroke="#3b82f6" strokeWidth={0.7} dot={false} strokeDasharray="3 2" />

                    {/* Price area */}
                    <Area dataKey="close" stroke={dir === 'short' ? '#ef4444' : '#f97316'} strokeWidth={2}
                      fill="url(#priceGrad)" dot={false} />

                    {/* Signal levels */}
                    {levels.sl != null && (
                      <ReferenceLine y={levels.sl} stroke="#ef4444" strokeDasharray="6 3" strokeWidth={1.5}
                        label={{ value: `SL ${fmtPrice(levels.sl)}`, fill: '#ef4444', fontSize: 10, position: 'right' }} />
                    )}
                    {levels.tp != null && (
                      <ReferenceLine y={levels.tp} stroke="#22c55e" strokeDasharray="6 3" strokeWidth={1.5}
                        label={{ value: `TP ${fmtPrice(levels.tp)}`, fill: '#22c55e', fontSize: 10, position: 'right' }} />
                    )}
                    {price > 0 && (
                      <ReferenceLine y={price} stroke="#94a3b8" strokeDasharray="2 2" strokeWidth={1} />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              {/* Volume */}
              <div style={{ height: 80 }} className="px-2 pb-2">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 0, right: 15, bottom: 0, left: 5 }}>
                    <XAxis dataKey="timeStr" hide />
                    <YAxis domain={[0, volumeMax]} hide />
                    <Bar dataKey="volume">
                      {chartData.map((entry, idx) => (
                        <Cell key={`v-${idx}`} fill={entry.close >= entry.open ? '#16a34a' : '#dc2626'} fillOpacity={0.55} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* ── RSI Chart ── */}
          {chartType === 'rsi' && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-800">
                <span className="text-sm font-semibold text-white">RSI(14) — {symbol}</span>
                <span className="ml-3 text-xs text-gray-500">30 oversold · 70 overbought</span>
              </div>
              <div style={{ height: 300 }} className="px-2 py-3">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 5, right: 15, bottom: 5, left: 5 }}>
                    <defs>
                      <linearGradient id="rsiGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#a855f7" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#a855f7" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                    <XAxis dataKey="timeStr" tickFormatter={xFmt} tick={{ fill: '#6b7280', fontSize: 10 }}
                      tickLine={false} axisLine={{ stroke: '#374151' }} />
                    <YAxis domain={[0, 100]} ticks={[20, 30, 50, 70, 80]}
                      tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} width={30} />
                    <Tooltip content={<RSITooltip />} />

                    {/* Zone areas */}
                    <ReferenceArea y1={70} y2={100} fill="#ef4444" fillOpacity={0.06} />
                    <ReferenceArea y1={0} y2={30} fill="#3b82f6" fillOpacity={0.06} />
                    <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="4 2" strokeWidth={1}
                      label={{ value: '70', fill: '#ef4444', fontSize: 9, position: 'right' }} />
                    <ReferenceLine y={50} stroke="#6b7280" strokeDasharray="4 2" strokeWidth={0.8} />
                    <ReferenceLine y={30} stroke="#3b82f6" strokeDasharray="4 2" strokeWidth={1}
                      label={{ value: '30', fill: '#3b82f6', fontSize: 9, position: 'right' }} />

                    <Area dataKey="rsi" stroke="#a855f7" strokeWidth={2} fill="url(#rsiGrad)" dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* ── MACD Chart ── */}
          {chartType === 'macd' && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-800">
                <span className="text-sm font-semibold text-white">MACD(12,26,9) — {symbol}</span>
              </div>
              <div style={{ height: 300 }} className="px-2 py-3">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{ top: 5, right: 15, bottom: 5, left: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                    <XAxis dataKey="timeStr" tickFormatter={xFmt} tick={{ fill: '#6b7280', fontSize: 10 }}
                      tickLine={false} axisLine={{ stroke: '#374151' }} />
                    <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} width={55} />
                    <Tooltip content={<MACDTooltip />} />
                    <ReferenceLine y={0} stroke="#6b7280" strokeWidth={0.8} />

                    <Bar dataKey="macdHist">
                      {chartData.map((entry, idx) => (
                        <Cell key={`m-${idx}`} fill={(entry.macdHist ?? 0) >= 0 ? '#22c55e' : '#ef4444'} fillOpacity={0.75} />
                      ))}
                    </Bar>
                    <Line dataKey="macd" stroke="#f97316" strokeWidth={1.5} dot={false} />
                    <Line dataKey="macdSig" stroke="#a855f7" strokeWidth={1.2} dot={false} strokeDasharray="4 2" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="px-4 pb-3 flex gap-4 text-xs text-gray-500">
                <span><span className="text-orange-400">—</span> MACD</span>
                <span><span className="text-purple-400">- -</span> Signal</span>
                <span><span className="text-green-400">█</span> Hist +</span>
                <span><span className="text-red-400">█</span> Hist −</span>
              </div>
            </div>
          )}

          {/* ── Technical Indicators ── */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800">
              <h3 className="text-sm font-semibold text-white">Technical Indicators</h3>
            </div>
            <div className="p-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricBadge label="RSI-14" value={fmt(features?.rsi_14 ?? signal?.rsi, 1)}
                color={
                  (features?.rsi_14 ?? 50) < 30 ? 'text-blue-400' :
                  (features?.rsi_14 ?? 50) > 70 ? 'text-red-400' : 'text-white'
                }
                sub={(features?.rsi_14 ?? 50) < 30 ? 'Oversold' : (features?.rsi_14 ?? 50) > 70 ? 'Overbought' : 'Neutral'}
              />
              <MetricBadge label="RSI-7" value={fmt(features?.rsi_7, 1)}
                color={(features?.rsi_7 ?? 50) < 30 ? 'text-blue-400' : (features?.rsi_7 ?? 50) > 70 ? 'text-red-400' : 'text-white'}
              />
              <MetricBadge label="ADX" value={fmt(features?.adx, 1)}
                color={(features?.adx ?? 0) > 25 ? 'text-green-400' : (features?.adx ?? 0) > 15 ? 'text-yellow-400' : 'text-gray-400'}
                sub={(features?.adx ?? 0) > 25 ? 'Strong Trend' : 'Weak/No Trend'}
              />
              <MetricBadge label="Stochastic %K" value={fmt(features?.stoch_k, 1)}
                color={(features?.stoch_k ?? 50) < 20 ? 'text-blue-400' : (features?.stoch_k ?? 50) > 80 ? 'text-red-400' : 'text-white'}
              />
              <MetricBadge label="MACD Hist" value={fmt(features?.macd_hist ?? signal?.macd_hist, 4)}
                color={(features?.macd_hist ?? 0) > 0 ? 'text-green-400' : 'text-red-400'}
              />
              <MetricBadge label="BB Position" value={fmt((features?.bb_position ?? 0) * 100, 1) + '%'}
                color={(features?.bb_position ?? 0.5) > 0.8 ? 'text-red-400' : (features?.bb_position ?? 0.5) < 0.2 ? 'text-blue-400' : 'text-white'}
                sub="0=lower band, 100=upper"
              />
              <MetricBadge label="Volume Ratio" value={`${fmt(features?.volume_ratio ?? signal?.volume_ratio, 2)}×`}
                color={(features?.volume_ratio ?? 1) > 1.5 ? 'text-orange-400' : 'text-white'}
                sub={(features?.volume_ratio ?? 1) > 1.5 ? 'High volume' : 'Normal'}
              />
              <MetricBadge label="OB Imbalance" value={fmt(features?.ob_imbalance_1, 3)}
                color={(features?.ob_imbalance_1 ?? 0) > 0.1 ? 'text-green-400' : (features?.ob_imbalance_1 ?? 0) < -0.1 ? 'text-red-400' : 'text-white'}
              />
              {features?.funding_rate != null && (
                <MetricBadge label="Funding Rate" value={`${(features.funding_rate * 100).toFixed(4)}%`}
                  color={features.funding_rate > 0.0005 ? 'text-orange-400' : features.funding_rate < -0.0005 ? 'text-blue-400' : 'text-white'}
                  sub={features.funding_rate > 0 ? 'Longs pay' : 'Shorts pay'}
                />
              )}
              {features?.oi_change_1h != null && (
                <MetricBadge label="OI Change 1h" value={`${features.oi_change_1h >= 0 ? '+' : ''}${fmt(features.oi_change_1h, 2)}%`}
                  color={features.oi_change_1h > 2 ? 'text-green-400' : features.oi_change_1h < -2 ? 'text-red-400' : 'text-white'}
                />
              )}
              {features?.ls_ratio_z != null && (
                <MetricBadge label="L/S Ratio Z" value={fmt(features.ls_ratio_z, 2)}
                  color={Math.abs(features.ls_ratio_z) > 2 ? 'text-orange-400' : 'text-white'}
                  sub={features.ls_ratio_z > 1 ? 'Longs dominant' : features.ls_ratio_z < -1 ? 'Shorts dominant' : 'Balanced'}
                />
              )}
              <MetricBadge label="ATR%" value={`${fmt(levels.atrPct * 100, 2)}%`}
                color={(levels.atrPct * 100) > 2 ? 'text-red-400' : 'text-white'}
                sub="Volatility measure"
              />
            </div>

            <div className="px-4 pb-4 flex flex-wrap gap-3 text-xs">
              <span className={DRIFT_COLOR[features?.drift_status ?? ''] ?? 'text-gray-400'}>
                Drift: <b>{features?.drift_status ?? signal?.drift_status ?? '—'}</b>
              </span>
              <span className={REGIME_COLOR[features?.regime ?? ''] ?? 'text-gray-400'}>
                Regime: <b>{features?.regime ?? signal?.regime ?? '—'}</b>
              </span>
              {signal?.timestamp && (
                <span className="text-gray-600">Signal: {timeAgo(signal.timestamp)}</span>
              )}
            </div>
          </div>

          {/* ── Phase 1 Features: CVD + MTF + Volume Profile ── */}
          {features && (features.cvd_5m != null || features.bull_confluence != null || features.vpoc_dist_pct != null) && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h3 className="text-sm font-semibold text-white">Advanced Signals — CVD · MTF · Volume Profile</h3>
              </div>
              <div className="p-4 grid grid-cols-1 sm:grid-cols-3 gap-4">

                {/* CVD */}
                {(features.cvd_5m != null || features.cvd_1h != null) && (
                  <div className="space-y-2">
                    <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Cumulative Volume Delta</p>
                    {features.cvd_5m != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">CVD 5m</span>
                        <span className={`text-xs font-bold font-mono ${features.cvd_5m > 0.1 ? 'text-green-400' : features.cvd_5m < -0.1 ? 'text-red-400' : 'text-gray-400'}`}>
                          {features.cvd_5m > 0 ? '+' : ''}{features.cvd_5m.toFixed(3)}
                        </span>
                      </div>
                    )}
                    {features.cvd_1h != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">CVD 1h</span>
                        <span className={`text-xs font-bold font-mono ${features.cvd_1h > 0.1 ? 'text-green-400' : features.cvd_1h < -0.1 ? 'text-red-400' : 'text-gray-400'}`}>
                          {features.cvd_1h > 0 ? '+' : ''}{features.cvd_1h.toFixed(3)}
                        </span>
                      </div>
                    )}
                    {features.buy_ratio_5m != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">Buy Ratio 5m</span>
                        <span className={`text-xs font-bold font-mono ${features.buy_ratio_5m > 0.55 ? 'text-green-400' : features.buy_ratio_5m < 0.45 ? 'text-red-400' : 'text-gray-400'}`}>
                          {(features.buy_ratio_5m * 100).toFixed(1)}%
                        </span>
                      </div>
                    )}
                    {features.liq_ratio_1h != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">Liq Ratio 1h</span>
                        <span className={`text-xs font-bold font-mono ${features.liq_ratio_1h > 0 ? 'text-green-400' : features.liq_ratio_1h < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                          {features.liq_ratio_1h > 0 ? '+' : ''}{features.liq_ratio_1h.toFixed(3)}
                        </span>
                      </div>
                    )}
                  </div>
                )}

                {/* MTF Confluence */}
                {(features.bull_confluence != null || features.trend_alignment != null) && (
                  <div className="space-y-2">
                    <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Multi-Timeframe (1h)</p>
                    {features.trend_alignment != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">Trend Align</span>
                        <div className="flex items-center gap-1.5">
                          <div className="flex gap-0.5">
                            {[-1, 0, 1].map(v => (
                              <div key={v} className={`w-2.5 h-2.5 rounded-sm ${features.trend_alignment! >= v && v !== 0 ? (v > 0 ? 'bg-green-400' : 'bg-red-400') : features.trend_alignment! === 0 && v === 0 ? 'bg-gray-400' : 'bg-gray-700'}`} />
                            ))}
                          </div>
                          <span className={`text-xs font-bold ${(features.trend_alignment ?? 0) > 0 ? 'text-green-400' : (features.trend_alignment ?? 0) < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                            {features.trend_alignment > 0 ? '+' : ''}{features.trend_alignment}
                          </span>
                        </div>
                      </div>
                    )}
                    {features.bull_confluence != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">Bull Confluence</span>
                        <span className={`text-xs font-bold ${features.bull_confluence >= 2 ? 'text-green-400' : features.bull_confluence >= 1 ? 'text-yellow-400' : 'text-gray-500'}`}>
                          {features.bull_confluence}/2
                        </span>
                      </div>
                    )}
                    {features.bear_confluence != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">Bear Confluence</span>
                        <span className={`text-xs font-bold ${features.bear_confluence >= 2 ? 'text-red-400' : features.bear_confluence >= 1 ? 'text-orange-400' : 'text-gray-500'}`}>
                          {features.bear_confluence}/2
                        </span>
                      </div>
                    )}
                    {features.rsi_14_1h != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">RSI-14 (1h)</span>
                        <span className={`text-xs font-bold font-mono ${features.rsi_14_1h < 30 ? 'text-blue-400' : features.rsi_14_1h > 70 ? 'text-red-400' : 'text-white'}`}>
                          {features.rsi_14_1h.toFixed(1)}
                        </span>
                      </div>
                    )}
                  </div>
                )}

                {/* Volume Profile */}
                {(features.vpoc_dist_pct != null || features.va_position != null) && (
                  <div className="space-y-2">
                    <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Volume Profile</p>
                    {features.vpoc_dist_pct != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">VPOC Dist</span>
                        <span className={`text-xs font-bold font-mono ${Math.abs(features.vpoc_dist_pct) < 0.5 ? 'text-yellow-400' : 'text-white'}`}>
                          {features.vpoc_dist_pct > 0 ? '+' : ''}{features.vpoc_dist_pct.toFixed(2)}%
                        </span>
                      </div>
                    )}
                    {features.va_position != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">VA Position</span>
                        <span className={`text-xs font-bold ${features.va_position > 0 ? 'text-green-400' : features.va_position < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                          {features.va_position > 0 ? '▲ Above VA' : features.va_position < 0 ? '▼ Below VA' : '= In VA'}
                        </span>
                      </div>
                    )}
                    {features.in_value_area != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">In Value Area</span>
                        <span className={`text-xs font-bold ${features.in_value_area ? 'text-blue-400' : 'text-orange-400'}`}>
                          {features.in_value_area ? 'YES' : 'NO'}
                        </span>
                      </div>
                    )}
                    {features.vpoc_dominance != null && (
                      <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                        <span className="text-xs text-gray-400">VPOC Dominance</span>
                        <span className="text-xs font-bold font-mono text-white">
                          {(features.vpoc_dominance * 100).toFixed(1)}%
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Right: AI Analysis ── */}
        <div className="space-y-3">

          {/* Current Signal */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">AI Signal</h3>
              <span className="text-xs text-gray-600">{signal?.source ?? '—'}</span>
            </div>

            <div className="flex items-center gap-3">
              <span className={`text-2xl font-black px-4 py-2 rounded-lg border ${DIR_STYLE[dir]}`}>
                {dir === 'long' ? '▲ LONG' : dir === 'short' ? '▼ SHORT' : '— FLAT'}
              </span>
            </div>

            <ConfidenceMeter value={conf} label="Signal Confidence" />

            {/* ML Score + RL Direction */}
            <div className="flex items-center gap-2 flex-wrap">
              {signal?.ml_score != null && (
                <div className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border ${
                  signal.ml_score > 0.15 ? 'bg-green-900/20 border-green-800/40 text-green-400'
                  : signal.ml_score < -0.15 ? 'bg-red-900/20 border-red-800/40 text-red-400'
                  : 'bg-gray-800/50 border-gray-700/40 text-gray-400'
                }`}>
                  <span>🧠 ML</span>
                  <span className="font-mono font-bold">{signal.ml_score > 0 ? '+' : ''}{signal.ml_score.toFixed(3)}</span>
                </div>
              )}
              {(signal?.rl_direction || rl_signal) && (() => {
                const rlDir = signal?.rl_direction ?? rl_signal?.direction ?? 'flat'
                const rlConf = rl_signal?.confidence ?? 0
                return rlDir !== 'flat' ? (
                  <div className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border ${
                    rlDir === 'long' ? 'bg-green-900/20 border-green-800/40 text-green-400'
                    : 'bg-red-900/20 border-red-800/40 text-red-400'
                  }`}>
                    <span>🤖 RL/PPO</span>
                    <span className="font-bold">{rlDir.toUpperCase()}</span>
                    {rlConf > 0 && <span className="font-mono text-gray-400">{Math.round(rlConf * 100)}%</span>}
                  </div>
                ) : null
              })()}
              {signal?.risk_reward != null && signal.risk_reward > 0 && (
                <div className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border bg-gray-800/50 border-gray-700/40 text-gray-300">
                  <span>R:R</span>
                  <span className="font-bold">1:{signal.risk_reward.toFixed(1)}</span>
                </div>
              )}
            </div>

            {verdict?.consensus_reasoning && (
              <div className="bg-gray-800/60 rounded-lg p-3 border border-gray-700/40">
                <p className="text-xs text-gray-500 uppercase tracking-wide mb-1.5">AI Reasoning</p>
                <p className="text-xs text-gray-300 leading-relaxed">{verdict.consensus_reasoning}</p>
              </div>
            )}
            {verdict?.dissent_risk && (
              <div className="bg-yellow-900/20 rounded-lg p-2.5 border border-yellow-800/40">
                <p className="text-xs text-yellow-400">⚠ {verdict.dissent_risk}</p>
              </div>
            )}

            {/* Vote tally */}
            <div className="space-y-2">
              <p className="text-xs text-gray-500 uppercase tracking-wide">Agent Votes</p>
              <div className="flex gap-2">
                {[
                  { label: '▲ Long', count: longVotes, color: 'text-green-400 bg-green-900/30 border-green-800/40' },
                  { label: '▼ Short', count: shortVotes, color: 'text-red-400 bg-red-900/30 border-red-800/40' },
                  { label: '— Flat', count: flatVotes, color: 'text-gray-400 bg-gray-800/50 border-gray-700/40' },
                ].map(({ label, count, color }) => (
                  <div key={label} className={`flex-1 text-center py-1.5 rounded border text-xs font-bold ${color}`}>
                    {count} {label}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Agent votes breakdown */}
          {votes.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
              <h3 className="text-sm font-semibold text-white">9-Agent Breakdown</h3>
              <div className="space-y-2.5">
                {votes.map((v, i) => <AgentVoteRow key={i} vote={v} />)}
              </div>
            </div>
          )}

          {/* Leverage Recommendation */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
            <h3 className="text-sm font-semibold text-white">Kaldıraç Tavsiyesi</h3>

            <div className="flex items-center gap-3">
              <div className="text-center">
                <p className="text-3xl font-black text-orange-400">{leverageRec.recommended}×</p>
                <p className="text-xs text-gray-500">Recommended</p>
              </div>
              <div className="flex-1 text-xs space-y-1 text-gray-400">
                <div className="flex justify-between">
                  <span>ATR Volatility</span><span>{leverageRec.atrPct}%</span>
                </div>
                <div className="flex justify-between">
                  <span>Crisis Level</span>
                  <span className={leverageRec.crisisLevel > 2 ? 'text-red-400' : 'text-green-400'}>
                    L{leverageRec.crisisLevel} {crisisLabels[leverageRec.crisisLevel]}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Crisis Mult</span><span>{(leverageRec.crisisMult * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between">
                  <span>Kelly Size</span><span>{(leverageRec.kellyFraction * 100).toFixed(2)}%</span>
                </div>
              </div>
            </div>

            <LeverageGauge leverageRec={leverageRec} rec={leverageRec.recommended} />

            {/* Interactive leverage slider */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-gray-400">
                <span>Position size @ {leverageVal}×</span>
                <span className="text-orange-400 font-bold">${positionSizeUsd.toFixed(0)}</span>
              </div>
              <input type="range" min={1} max={20} value={leverageVal}
                onChange={e => setLeverageVal(Number(e.target.value))}
                className="w-full accent-orange-500" />
              <div className="flex justify-between text-xs text-gray-600">
                <span>1×</span><span>10×</span><span>20×</span>
              </div>
            </div>

            {dir !== 'flat' && levels.sl && levels.tp && (
              <div className="bg-gray-800/60 rounded-lg p-3 border border-gray-700/40 text-xs space-y-1.5">
                <p className="text-gray-400 uppercase tracking-wide mb-1">Entry Plan ({leverageVal}×)</p>
                <div className="flex justify-between">
                  <span className="text-gray-500">Entry</span>
                  <span className="text-white font-mono">{fmtPrice(price)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-red-400">Stop Loss</span>
                  <span className="text-red-400 font-mono">{fmtPrice(levels.sl)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-green-400">Take Profit</span>
                  <span className="text-green-400 font-mono">{fmtPrice(levels.tp)}</span>
                </div>
                <div className="flex justify-between border-t border-gray-700/40 pt-1.5">
                  <span className="text-gray-500">R:R Ratio</span>
                  <span className="text-white font-bold">
                    {levels.risk_reward ? `1 : ${levels.risk_reward.toFixed(2)}` : '1 : 1.75'}
                  </span>
                </div>
                {levels.stop_pct && levels.tp_pct && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">ATR Stop / TP</span>
                    <span className="text-gray-400 font-mono text-[10px]">
                      {Math.abs(levels.stop_pct).toFixed(2)}% / {Math.abs(levels.tp_pct).toFixed(2)}%
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-gray-500">Max Loss</span>
                  <span className="text-red-400 font-mono">
                    ${(positionSizeUsd * Math.abs(levels.sl - price) / price).toFixed(0)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Max Profit</span>
                  <span className="text-green-400 font-mono">
                    ${(positionSizeUsd * Math.abs(levels.tp - price) / price).toFixed(0)}
                  </span>
                </div>
              </div>
            )}
          </div>

        </div>
      </div>

      {/* ── Backtest Performance ── */}
      {backtestStats && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">Backtest Performance — {symbol}</h3>
            <span className="text-xs text-gray-500">1-Year Historical Simulation</span>
          </div>
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
              <MetricBadge label="Win Rate" value={`${fmt(backtestStats.win_rate_pct, 1)}%`}
                color={backtestStats.win_rate_pct >= 52 ? 'text-green-400' : 'text-red-400'}
                sub={backtestStats.win_rate_pct >= 52 ? '✓ Above gate' : '✗ Below 52% gate'}
              />
              <MetricBadge label="Sharpe Ratio" value={fmt(backtestStats.sharpe_ratio)}
                color={backtestStats.sharpe_ratio >= 1.5 ? 'text-green-400' : backtestStats.sharpe_ratio >= 1 ? 'text-yellow-400' : 'text-red-400'}
              />
              <MetricBadge label="Total Return" value={`${backtestStats.total_return_pct >= 0 ? '+' : ''}${fmt(backtestStats.total_return_pct, 1)}%`}
                color={backtestStats.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}
              />
              <MetricBadge label="Max Drawdown" value={`${fmt(backtestStats.max_drawdown_pct, 1)}%`}
                color={backtestStats.max_drawdown_pct < 10 ? 'text-green-400' : 'text-red-400'}
              />
              <MetricBadge label="Total Trades" value={String(backtestStats.total_trades)}
                color="text-white" sub="1h bars"
              />
              <MetricBadge label="Profit Factor" value={fmt(backtestStats.profit_factor)}
                color={backtestStats.profit_factor >= 1.5 ? 'text-green-400' : backtestStats.profit_factor >= 1 ? 'text-yellow-400' : 'text-red-400'}
              />
              <MetricBadge label="Avg Hold" value={`${fmt(backtestStats.avg_bars_held, 1)}h`}
                color="text-white"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Win Rate by Direction</p>
                <div className="space-y-1.5">
                  {[
                    { label: '▲ Long', val: backtestStats.long_win_rate_pct, color: 'bg-green-500' },
                    { label: '▼ Short', val: backtestStats.short_win_rate_pct, color: 'bg-red-500' },
                  ].map(({ label, val, color }) => (
                    <div key={label} className="flex items-center gap-2 text-xs">
                      <span className="text-gray-400 w-14">{label}</span>
                      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div className={`h-full ${color}`} style={{ width: `${val ?? 0}%` }} />
                      </div>
                      <span className="text-gray-300 tabular-nums w-12 text-right">{fmt(val, 1)}%</span>
                    </div>
                  ))}
                </div>

                <div className="mt-3 text-xs space-y-1 text-gray-400">
                  <div className="flex justify-between">
                    <span>Avg Win</span><span className="text-green-400">+{fmt(backtestStats.avg_win_pct, 2)}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Avg Loss</span><span className="text-red-400">-{fmt(backtestStats.avg_loss_pct, 2)}%</span>
                  </div>
                </div>

                {backtestStats.exit_reasons && (
                  <div className="mt-3 text-xs space-y-1">
                    <p className="text-gray-500 uppercase tracking-wide">Exit Reasons</p>
                    {Object.entries(backtestStats.exit_reasons).map(([reason, count]) => (
                      <div key={reason} className="flex justify-between text-gray-400">
                        <span className="capitalize">{reason.replace('_', ' ')}</span>
                        <span>{count} trades</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Monthly Returns</p>
                <MonthlyHeatmap monthly={backtestStats.monthly_returns ?? {}} />
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
