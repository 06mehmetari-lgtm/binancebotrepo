'use client'
import { useEffect, useState } from 'react'

interface RiskData {
  immunity_halted: boolean
  daily_loss_pct: number
  daily_loss_display_pct?: number
  max_daily_loss_pct?: number
  daily_trades: number
  crisis_level: number
  regime: string | null
  vix: number | null
  ws_status: string
  funding_alerts: Array<{ symbol: string; rate: number; severity: string; direction: string }>
  recent_liquidations: Array<{ symbol: string; side: string; value_usdt: number; time: string }>
  drift_summary: Record<string, number>
  limits: {
    max_drawdown: number; max_daily_loss: number; max_position_pct: number
    min_confidence: number; max_trades_per_day: number; max_leverage: number; max_open_positions: number
  }
}

interface Position {
  symbol: string; direction: string; size_usd: number
  entry_price: number; current_price: number | null
  unrealized_pct: number; unrealized_usdt: number; age_hours: number
  entry_signal?: { confidence: number; regime: string }
}

interface SqsEntry {
  symbol: string; sqs: number; direction: string; confidence: number
  sharpe: number | null; win_rate: number | null; regime: string | null; drift: string
}

const CRISIS_COLORS = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-500 animate-pulse']
const CRISIS_BG = ['bg-green-900/20 border-green-800/40', 'bg-yellow-900/20 border-yellow-800/40', 'bg-orange-900/20 border-orange-800/40', 'bg-red-900/20 border-red-800/40', 'bg-red-900/40 border-red-600/60']
const CRISIS_LABELS = ['Normal', 'Caution', 'Warning', 'Alarm', 'CRISIS']
const CRISIS_MULTS = [1.0, 0.65, 0.35, 0.10, 0.0]
const DRIFT_COLORS: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500' }

function GaugeBar({ value, max, color, danger, label }: { value: number; max: number; color: string; danger?: number; label: string }) {
  const pct = Math.min(100, (value / max) * 100)
  const isDanger = danger !== undefined && value >= danger
  return (
    <div>
      <div className="flex justify-between items-center mb-1.5">
        <span className="text-gray-400 text-xs">{label}</span>
        <span className={`text-sm font-bold font-mono ${isDanger ? 'text-red-400' : 'text-white'}`}>
          {value.toFixed(2)} / {max}
        </span>
      </div>
      <div className="relative w-full h-3 bg-gray-800 rounded-full overflow-hidden">
        <div className={`absolute left-0 h-full rounded-full transition-all duration-500 ${isDanger ? 'bg-red-500' : color}`} style={{ width: `${pct}%` }} />
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

function SqsBar({ v }: { v: number }) {
  const color = v >= 70 ? 'bg-green-500' : v >= 50 ? 'bg-yellow-500' : v >= 30 ? 'bg-orange-500' : 'bg-red-500'
  const textColor = v >= 70 ? 'text-green-400' : v >= 50 ? 'text-yellow-400' : v >= 30 ? 'text-orange-400' : 'text-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${v}%` }} />
      </div>
      <span className={`text-xs font-bold font-mono w-7 text-right ${textColor}`}>{v}</span>
    </div>
  )
}

function fmtPrice(p: number | null) {
  if (!p) return '—'
  if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (p >= 1) return p.toFixed(4)
  return p.toFixed(6)
}

export default function RiskPage() {
  const [data, setData] = useState<Partial<RiskData>>({})
  const [positions, setPositions] = useState<Position[]>([])
  const [sqsTop, setSqsTop] = useState<SqsEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [clearBusy, setClearBusy] = useState(false)
  const [clearMsg, setClearMsg] = useState('')

  const fetchData = async () => {
    try {
      const [riskJson, posJson, sqsJson] = await Promise.all([
        fetch('/api/risk').then(r => r.json()),
        fetch('/api/positions').then(r => r.json()),
        fetch('/api/sqs').then(r => r.json()),
      ])
      setData(riskJson || {})
      setPositions(posJson?.positions ?? [])
      if (Array.isArray(sqsJson)) {
        setSqsTop(sqsJson.filter((s: SqsEntry) => s.direction !== 'flat').slice(0, 8))
      }
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 5000); return () => clearInterval(t) }, [])

  const clearImmunityHalt = async () => {
    if (!window.confirm(
      'Bağışıklık kilidi kaldırılsın mı? Günlük zarar sayacı sıfırlanır; sabit limitler (%2 günlük zarar, %5 pozisyon vb.) geçerli kalır.'
    )) return
    setClearBusy(true)
    setClearMsg('')
    try {
      const res = await fetch('/api/emergency', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'clear_immunity_halt' }),
      })
      const j = await res.json()
      setClearMsg(j.message ?? (res.ok ? 'Kilit kaldırıldı' : j.error ?? 'Hata'))
      await fetchData()
    } catch (e) {
      setClearMsg(String(e))
    } finally {
      setClearBusy(false)
    }
  }

  const crisis = data.crisis_level ?? 0
  const dailyLoss =
    data.daily_loss_display_pct ??
    (data.daily_loss_pct ?? 0) * 100
  const maxDailyLoss =
    (data.max_daily_loss_pct ?? data.limits?.max_daily_loss ?? 0.02) * 100
  const dailyTrades = data.daily_trades ?? 0
  const maxTrades = data.limits?.max_trades_per_day ?? 50
  const isHalted = data.immunity_halted ?? false
  const driftSummary = data.drift_summary ?? {}
  const totalDriftSamples = Object.values(driftSummary).reduce((a, b) => a + b, 0)
  const totalUnrealized = positions.reduce((s, p) => s + p.unrealized_usdt, 0)

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-red-400">⚡</span>
      <span>Loading risk data...</span>
    </div>
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">Risk & Immunity System</h1>
          <p className="text-gray-500 text-xs mt-0.5">Hard limits enforced on every order — cannot be bypassed by any AI component</p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {data.vix != null && (
            <span className={`text-xs font-mono px-2 py-1 rounded border ${
              data.vix > 40 ? 'text-red-400 border-red-700/50 bg-red-900/20' :
              data.vix > 25 ? 'text-yellow-400 border-yellow-700/50 bg-yellow-900/20' :
              'text-green-400 border-green-700/50 bg-green-900/20'
            }`}>
              VIX {data.vix.toFixed(1)}
            </span>
          )}
          <span className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate} · 5s` : '5s refresh'}</span>
        </div>
      </div>

      {isHalted && (
        <div className="bg-red-900/40 border border-red-500/60 rounded-lg p-4 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-start gap-3 flex-1">
            <span className="text-red-400 text-2xl animate-pulse shrink-0">⚠</span>
            <div>
              <p className="text-red-300 font-bold text-sm">BAĞIŞIKLIK SİSTEMİ DURDURULDU</p>
              <p className="text-red-200/90 text-xs mt-1 leading-relaxed">
                Günlük zarar limiti (%2) veya acil durdurma sonrası koruma devrede — yeni emirler reddediliyor.
                Şu an kayıtlı günlük zarar: <span className="font-mono font-bold">{dailyLoss.toFixed(2)}%</span>
                {' '}(limit {maxDailyLoss.toFixed(0)}%).
                Acil durdurma kullandıysanız aşağıdaki düğme ile kilidi kaldırın; sabit limitler değişmez.
              </p>
              <p className="text-red-400/60 text-[11px] mt-1.5">IMMUNITY SYSTEM HALTED — not max portfolio drawdown (10%)</p>
            </div>
          </div>
          <button
            type="button"
            onClick={clearImmunityHalt}
            disabled={clearBusy}
            className="shrink-0 px-4 py-2 rounded-lg text-xs font-bold bg-green-800/60 border border-green-600 text-green-200 hover:bg-green-800 disabled:opacity-50"
          >
            {clearBusy ? '⏳...' : '▶ Kilidi Kaldır & Devam Et'}
          </button>
        </div>
      )}
      {clearMsg && (
        <p className="text-xs text-orange-300 bg-orange-950/30 border border-orange-800/50 rounded-lg px-3 py-2">{clearMsg}</p>
      )}

      {/* Crisis Level */}
      <div className={`rounded-xl border p-4 ${CRISIS_BG[crisis] ?? CRISIS_BG[0]}`}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-white font-semibold text-sm">Crisis Level</h2>
          <div className="flex items-center gap-3">
            {data.regime && (
              <span className={`text-xs px-2 py-0.5 rounded border ${
                data.regime === 'trending_up' ? 'text-green-400 border-green-700/50 bg-green-900/20' :
                data.regime === 'trending_down' ? 'text-red-400 border-red-700/50 bg-red-900/20' :
                data.regime === 'volatile' ? 'text-orange-400 border-orange-700/50 bg-orange-900/20' :
                'text-blue-400 border-blue-700/50 bg-blue-900/20'
              }`}>{data.regime.replace('_', ' ')}</span>
            )}
            <span className={`text-2xl font-black ${CRISIS_COLORS[crisis]}`}>
              {CRISIS_LABELS[crisis]} (L{crisis})
            </span>
          </div>
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

      {/* Active Positions + SQS Top Signals */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Open positions */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">⚡ Open Positions</h2>
            <div className="flex items-center gap-2 text-xs">
              <span className={totalUnrealized >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
                {totalUnrealized >= 0 ? '+' : ''}${totalUnrealized.toFixed(2)}
              </span>
              <span className="text-gray-600">{positions.length} / 3</span>
            </div>
          </div>
          {positions.length === 0 ? (
            <p className="text-gray-500 text-sm p-5 text-center">No open positions</p>
          ) : (
            <div className="divide-y divide-gray-800/40">
              {positions.map(pos => (
                <a key={pos.symbol} href={`/coin/${pos.symbol}`}
                  className="flex items-center justify-between px-4 py-3 hover:bg-gray-800/30 transition-colors">
                  <div className="flex items-center gap-3">
                    <span className={`text-xs px-1.5 py-0.5 rounded border font-bold ${
                      pos.direction === 'long' ? 'text-green-400 border-green-700/50 bg-green-900/20' : 'text-red-400 border-red-700/50 bg-red-900/20'
                    }`}>{pos.direction === 'long' ? '▲' : '▼'}</span>
                    <div>
                      <p className="text-white font-bold text-sm">{pos.symbol}</p>
                      <p className="text-gray-500 text-xs">
                        {fmtPrice(pos.entry_price)} → {fmtPrice(pos.current_price)}
                        {' · '}
                        {pos.age_hours < 1 ? `${Math.round(pos.age_hours * 60)}m` : `${pos.age_hours.toFixed(1)}h`}
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className={`font-bold font-mono text-sm ${pos.unrealized_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pos.unrealized_usdt >= 0 ? '+' : ''}${pos.unrealized_usdt.toFixed(2)}
                    </p>
                    <p className={`text-xs font-mono ${pos.unrealized_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pos.unrealized_pct >= 0 ? '+' : ''}{pos.unrealized_pct.toFixed(2)}%
                    </p>
                  </div>
                </a>
              ))}
            </div>
          )}
        </div>

        {/* Top SQS signals */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-purple-400 font-semibold text-sm uppercase tracking-wider">🏆 Top Signal Quality</h2>
            <span className="text-xs text-gray-600">SQS score (0–100)</span>
          </div>
          {sqsTop.length === 0 ? (
            <p className="text-gray-500 text-sm p-5 text-center">Computing SQS scores...</p>
          ) : (
            <div className="divide-y divide-gray-800/40">
              {sqsTop.map(s => (
                <a key={s.symbol} href={`/coin/${s.symbol}`}
                  className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800/30 transition-colors">
                  <span className={`text-xs font-bold w-4 ${s.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                    {s.direction === 'long' ? '▲' : '▼'}
                  </span>
                  <span className="text-white font-bold text-xs w-20 shrink-0">{s.symbol.replace('USDT', '')}</span>
                  <div className="flex-1 min-w-0">
                    <SqsBar v={s.sqs} />
                  </div>
                  <div className="text-right shrink-0 text-xs text-gray-500 space-y-0.5">
                    {s.sharpe != null && <p>Sharpe {s.sharpe.toFixed(2)}</p>}
                    {s.win_rate != null && <p>WR {s.win_rate.toFixed(0)}%</p>}
                  </div>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Daily Limits + Drift */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-4">
          <h2 className="text-red-400 font-semibold text-sm uppercase tracking-wider">Daily Limits</h2>
          <GaugeBar label="Daily Loss" value={dailyLoss} max={maxDailyLoss} color="bg-orange-500" danger={maxDailyLoss} />
          <GaugeBar label="Trades Today" value={dailyTrades} max={maxTrades} color="bg-blue-500" danger={maxTrades} />
          <div className="pt-2 border-t border-gray-800/60 text-xs text-gray-500">
            Sayaçlar UTC gece yarısı sıfırlanır. %2 günlük zarar veya acil durum sonrası işlem askıya alınır —
            Risk sayfasındaki &quot;Kilidi Kaldır&quot; ile paper modda devam edebilirsiniz.
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
                        status === 'STABLE' ? 'bg-green-500' : status === 'WARNING' ? 'bg-yellow-500' :
                        status === 'DRIFTING' ? 'bg-orange-500' : 'bg-red-500'
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

      {/* Hard Limits */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800">
          <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">Absolute Hard Limits</h2>
        </div>
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <LimitCard icon="📉" label="Max Drawdown (shadow)" value="10%" description="Shadow promotion gate — separate from daily immunity halt on this page" />
          <LimitCard icon="🗓" label="Max Daily Loss" value="2%" description="No new trades once daily loss hits 2% of portfolio" />
          <LimitCard icon="📊" label="Max Position Size" value="5%" description="No single trade can exceed 5% of total portfolio value" />
          <LimitCard icon="🎯" label="Min Signal Confidence" value="60%" description="Signals below 60% confidence are suppressed to flat" />
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
                <span className="font-mono text-orange-400 font-bold">${(liq.value_usdt / 1000).toFixed(1)}K</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
