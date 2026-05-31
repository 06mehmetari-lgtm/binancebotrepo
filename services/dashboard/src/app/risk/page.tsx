'use client'
import { useEffect, useState } from 'react'

interface RiskData {
  immunity_halted: boolean
  daily_loss_pct: number
  daily_trades: number
  crisis_level: number
  regime: string | null
  vix: number | null
  ws_status: string
  funding_alerts: Array<{ symbol: string; rate: number; severity: string; direction: string }>
  recent_liquidations: Array<{ symbol: string; side: string; value_usdt: number; time: string }>
  drift_summary: Record<string, number>
  limits: {
    max_drawdown: number
    max_daily_loss: number
    max_position_pct: number
    min_confidence: number
    max_trades_per_day: number
    max_leverage: number
    max_open_positions: number
  }
  crisis_scale: Record<string, { label: string; multiplier: number; color: string }>
}

const CRISIS_COLORS = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-500 animate-pulse']
const CRISIS_BG = ['bg-green-900/20 border-green-800/40', 'bg-yellow-900/20 border-yellow-800/40', 'bg-orange-900/20 border-orange-800/40', 'bg-red-900/20 border-red-800/40', 'bg-red-900/40 border-red-600/60']
const CRISIS_LABELS = ['Normal', 'Caution', 'Warning', 'Alarm', 'CRISIS']
const CRISIS_MULTS = [1.0, 0.65, 0.35, 0.10, 0.0]
const DRIFT_COLORS: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500' }

function GaugeBar({ value, max, color, danger, label }: { value: number; max: number; color: string; danger?: number; label: string }) {
  const pct = Math.min(100, (value / max) * 100)
  const isDanger = danger !== undefined && value >= danger
  const barColor = isDanger ? 'bg-red-500' : color
  return (
    <div>
      <div className="flex justify-between items-center mb-1.5">
        <span className="text-gray-400 text-xs">{label}</span>
        <span className={`text-sm font-bold font-mono ${isDanger ? 'text-red-400' : 'text-white'}`}>
          {value.toFixed(2)} / {max}
        </span>
      </div>
      <div className="relative w-full h-3 bg-gray-800 rounded-full overflow-hidden">
        <div className={`absolute left-0 h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
        {danger !== undefined && (
          <div className="absolute h-full w-0.5 bg-red-500/50" style={{ left: `${(danger / max) * 100}%` }} />
        )}
      </div>
    </div>
  )
}

function LimitCard({ label, value, description, icon }: { label: string; value: string; description: string; icon: string }) {
  return (
    <div className="bg-gray-800/50 rounded-lg p-3">
      <div className="flex items-start gap-2">
        <span className="text-lg">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-gray-500 text-xs">{label}</p>
          <p className="text-white font-bold font-mono text-sm mt-0.5">{value}</p>
          <p className="text-gray-600 text-xs mt-1 leading-relaxed">{description}</p>
        </div>
      </div>
    </div>
  )
}

export default function RiskPage() {
  const [data, setData] = useState<Partial<RiskData>>({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = async () => {
    try {
      const d = await fetch('/api/risk').then(r => r.json())
      setData(d || {})
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 5000); return () => clearInterval(t) }, [])

  const crisis = data.crisis_level ?? 0
  const dailyLoss = (data.daily_loss_pct ?? 0) * 100
  const maxDailyLoss = (data.limits?.max_daily_loss ?? 0.02) * 100
  const dailyTrades = data.daily_trades ?? 0
  const maxTrades = data.limits?.max_trades_per_day ?? 50
  const isHalted = data.immunity_halted ?? false
  const driftSummary = data.drift_summary ?? {}
  const totalDriftSamples = Object.values(driftSummary).reduce((a, b) => a + b, 0)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">Risk & Immunity System</h1>
          <p className="text-gray-500 text-xs mt-0.5">Hard limits enforced on every order — cannot be bypassed by any AI component</p>
        </div>
        <span className="text-xs text-gray-600 shrink-0">{lastUpdate ? `${lastUpdate} · 5s` : '5s refresh'}</span>
      </div>

      {isHalted && (
        <div className="bg-red-900/40 border border-red-500/60 rounded-lg p-4 flex items-center gap-3">
          <span className="text-red-400 text-2xl animate-pulse">⚠</span>
          <div>
            <p className="text-red-300 font-bold text-sm">IMMUNITY SYSTEM HALTED</p>
            <p className="text-red-400/80 text-xs mt-0.5">Max drawdown limit exceeded — all trading suspended until daily reset</p>
          </div>
        </div>
      )}

      <div className={`rounded-xl border p-4 ${CRISIS_BG[crisis] ?? CRISIS_BG[0]}`}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-white font-semibold text-sm">Crisis Level</h2>
          <span className={`text-2xl font-black ${CRISIS_COLORS[crisis]}`}>
            {CRISIS_LABELS[crisis]} (L{crisis})
          </span>
        </div>
        <div className="grid grid-cols-5 gap-1.5">
          {CRISIS_LABELS.map((label, i) => (
            <div key={i} className={`rounded-lg p-2.5 text-center border transition-all ${
              i === crisis ? CRISIS_BG[i] : 'bg-gray-900/40 border-gray-800/40 opacity-40'
            }`}>
              <p className={`text-xs font-bold ${i === crisis ? CRISIS_COLORS[i] : 'text-gray-500'}`}>L{i}</p>
              <p className="text-gray-400 text-xs mt-0.5">{label}</p>
              <p className={`font-mono text-xs font-semibold mt-1 ${i === crisis ? CRISIS_COLORS[i] : 'text-gray-600'}`}>
                {(CRISIS_MULTS[i] * 100).toFixed(0)}%
              </p>
              <p className="text-gray-600 text-xs">Kelly</p>
            </div>
          ))}
        </div>
        <p className="text-gray-500 text-xs mt-3">
          At crisis level {crisis}, position sizes are scaled to {(CRISIS_MULTS[crisis] * 100).toFixed(0)}% of normal Kelly size.
          {crisis === 4 ? ' All trading is suspended.' : ''}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-4">
          <h2 className="text-red-400 font-semibold text-sm uppercase tracking-wider">Daily Limits</h2>
          <GaugeBar
            label="Daily Loss"
            value={dailyLoss}
            max={maxDailyLoss}
            color="bg-orange-500"
            danger={maxDailyLoss}
          />
          <GaugeBar
            label="Trades Today"
            value={dailyTrades}
            max={maxTrades}
            color="bg-blue-500"
            danger={maxTrades}
          />
          <div className="pt-2 border-t border-gray-800/60 text-xs text-gray-500">
            Limits reset at 00:00 UTC daily. Exceeding daily loss triggers trading suspension for the day.
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
          <h2 className="text-purple-400 font-semibold text-sm uppercase tracking-wider">Market Drift Status</h2>
          {totalDriftSamples === 0 ? (
            <p className="text-gray-500 text-sm">Collecting drift data...</p>
          ) : (
            <div className="space-y-2">
              {(['STABLE', 'WARNING', 'DRIFTING', 'SHOCK'] as const).map(status => {
                const count = driftSummary[status] ?? 0
                const pct = totalDriftSamples > 0 ? (count / totalDriftSamples) * 100 : 0
                return (
                  <div key={status} className="flex items-center gap-2 text-xs">
                    <span className={`w-16 font-semibold ${DRIFT_COLORS[status]}`}>{status}</span>
                    <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
                      <div className={`h-full rounded-full ${
                        status === 'STABLE' ? 'bg-green-500' : status === 'WARNING' ? 'bg-yellow-500' : status === 'DRIFTING' ? 'bg-orange-500' : 'bg-red-500'
                      }`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-gray-400 w-16 text-right font-mono">{count} ({pct.toFixed(0)}%)</span>
                  </div>
                )
              })}
            </div>
          )}
          <div className="pt-2 border-t border-gray-800/60 text-xs text-gray-500">
            Kelly fractions: STABLE=50%, WARNING=35%, DRIFTING=20%, SHOCK=0%
          </div>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800">
          <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">Absolute Hard Limits</h2>
        </div>
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <LimitCard icon="📉" label="Max Drawdown" value="10%" description="Entire system halts if total drawdown exceeds this threshold" />
          <LimitCard icon="🗓" label="Max Daily Loss" value="2%" description="No new trades once daily loss hits 2% of portfolio" />
          <LimitCard icon="📊" label="Max Position Size" value="7%" description="No single trade can exceed 7% of total portfolio value" />
          <LimitCard icon="🎯" label="Min Signal Confidence" value="52%" description="Signals below 52% confidence are suppressed to flat" />
          <LimitCard icon="⚡" label="Max Trades / Day" value="50" description="Hard limit on daily trade count prevents overtrading" />
          <LimitCard icon="🔒" label="Max Leverage" value="3×" description="Maximum leverage allowed by the immunity system" />
          <LimitCard icon="🏦" label="Max Open Positions" value="3" description="No more than 3 simultaneous open positions" />
          <LimitCard icon="💧" label="Min Spread" value="< 0.5%" description="Refuses orders when spread exceeds 0.5% (low liquidity)" />
          <LimitCard icon="📡" label="Funding Threshold" value="±0.3%" description="Extreme funding rate triggers caution mode (L1 crisis)" />
        </div>
        <div className="px-4 py-3 border-t border-gray-800 bg-red-950/10">
          <p className="text-red-400/70 text-xs">
            These limits are immutable — defined in <code className="text-red-300 font-mono">immunity.py</code> and cannot be changed at runtime by any AI component, NEAT genome, or RL agent.
          </p>
        </div>
      </div>

      {(data.funding_alerts ?? []).length > 0 && (
        <div className="bg-gray-900 border border-yellow-800/40 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="text-yellow-400 font-semibold text-sm uppercase tracking-wider">Funding Rate Alerts</h2>
          </div>
          <div className="divide-y divide-gray-800/40">
            {(data.funding_alerts ?? []).slice(0, 5).map((alert, i) => (
              <div key={i} className="px-4 py-3 flex items-center justify-between text-xs">
                <div className="flex items-center gap-3">
                  <span className={`font-bold ${alert.severity === 'HIGH' ? 'text-red-400' : 'text-yellow-400'}`}>{alert.severity}</span>
                  <span className="text-white font-semibold">{alert.symbol}</span>
                  <span className="text-gray-500">{alert.direction}</span>
                </div>
                <span className={`font-mono font-bold ${alert.rate > 0 ? 'text-orange-400' : 'text-blue-400'}`}>
                  {(alert.rate * 100).toFixed(4)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {(data.recent_liquidations ?? []).length > 0 && (
        <div className="bg-gray-900 border border-red-900/40 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="text-red-400 font-semibold text-sm uppercase tracking-wider">Recent Large Liquidations (&gt;$50K)</h2>
          </div>
          <div className="divide-y divide-gray-800/40">
            {(data.recent_liquidations ?? []).slice(0, 5).map((liq, i) => (
              <div key={i} className="px-4 py-3 flex items-center justify-between text-xs">
                <div className="flex items-center gap-3">
                  <span className={`font-bold ${liq.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>{liq.side}</span>
                  <span className="text-white font-semibold">{liq.symbol}</span>
                </div>
                <span className="font-mono text-orange-400 font-bold">
                  ${(liq.value_usdt / 1000).toFixed(1)}K
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
