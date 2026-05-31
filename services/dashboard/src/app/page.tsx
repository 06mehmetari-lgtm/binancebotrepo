'use client'
import { useEffect, useState } from 'react'

interface Market { symbol: string; rsi_14: number; direction: string; confidence: number; regime: string; crisis_level: number; kelly_fraction: number; drift_status: string }
interface Signal { symbol: string; direction: string; confidence: number; regime: string; crisis_level: number; drift_status: string; kelly_fraction: number; rsi?: number }
interface Shadow { shadow_id: string; sharpe: number; win_rate: number; trades: number; return: number; promotion_ready: boolean; max_drawdown: number }
interface Status { active_symbol_count: number; total_signals: number; avg_confidence: number; best_genome_fitness: number; fear_greed: { value: number; classification: string }; macro_vix: number; ws_status: { status: string; symbols?: number } | null; shadow: { leaderboard: Shadow[] } }
interface SymbolResult { win_rate_pct: number; sharpe_ratio: number; total_return_pct: number; max_drawdown_pct: number; total_trades: number; profit_factor: number }
interface BacktestResults { summary: { symbols_tested: number }; results: Record<string, SymbolResult> }

const DRIFT_COLOR: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500 animate-pulse' }
const DIR_STYLE: Record<string, string> = { long: 'text-green-400 bg-green-900/30 border border-green-800/50', short: 'text-red-400 bg-red-900/30 border border-red-800/50', flat: 'text-gray-500 bg-gray-800/50 border border-gray-700/50' }
const REGIME_COLOR: Record<string, string> = { trending_up: 'text-green-400', trending_down: 'text-red-400', ranging: 'text-blue-400', volatile: 'text-yellow-400' }

function rsiTileColor(rsi: number) {
  if (rsi < 30) return 'bg-blue-950/80 border-blue-700/60 hover:border-blue-400'
  if (rsi < 45) return 'bg-green-950/70 border-green-800/60 hover:border-green-500'
  if (rsi < 55) return 'bg-gray-800/80 border-gray-700/60 hover:border-gray-400'
  if (rsi < 70) return 'bg-orange-950/70 border-orange-800/60 hover:border-orange-500'
  return 'bg-red-950/80 border-red-700/60 hover:border-red-400'
}

function rsiTextColor(rsi: number) {
  if (rsi < 30) return 'text-blue-300'
  if (rsi < 45) return 'text-green-300'
  if (rsi < 55) return 'text-gray-300'
  if (rsi < 70) return 'text-orange-300'
  return 'text-red-300'
}

function StatCard({ label, value, sub, color, dot }: { label: string; value: string; sub?: string; color: string; dot?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-3.5 flex flex-col gap-1">
      <p className="text-gray-500 text-xs uppercase tracking-wider flex items-center gap-1.5">
        {dot && <span className={`inline-block w-1.5 h-1.5 rounded-full ${dot}`} />}
        {label}
      </p>
      <p className={`text-xl font-bold leading-tight ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500">{sub}</p>}
    </div>
  )
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'bg-green-500' : pct >= 65 ? 'bg-orange-500' : 'bg-yellow-600'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-300 tabular-nums">{pct}%</span>
    </div>
  )
}

function WinRateBadge({ wr }: { wr: number }) {
  const color = wr >= 60 ? 'text-green-400 bg-green-900/30 border-green-800/40'
    : wr >= 52 ? 'text-yellow-400 bg-yellow-900/30 border-yellow-800/40'
    : 'text-gray-500 bg-gray-800/40 border-gray-700/40'
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-mono font-bold ${color}`}>
      {wr.toFixed(1)}%
    </span>
  )
}

export default function Home() {
  const [markets, setMarkets] = useState<Market[]>([])
  const [signals, setSignals] = useState<Signal[]>([])
  const [shadow, setShadow] = useState<Shadow[]>([])
  const [status, setStatus] = useState<Partial<Status>>({})
  const [backtest, setBacktest] = useState<BacktestResults | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchAll = async () => {
    try {
      const [m, s, sh, st, bt] = await Promise.all([
        fetch('/api/markets').then(r => r.json()),
        fetch('/api/signals').then(r => r.json()),
        fetch('/api/shadow').then(r => r.json()),
        fetch('/api/status').then(r => r.json()),
        fetch('/api/backtest').then(r => r.json()),
      ])
      setMarkets(Array.isArray(m) ? m : [])
      setSignals(Array.isArray(s) ? s : [])
      setShadow(Array.isArray(sh) ? sh : [])
      setStatus(st || {})
      if (bt?.results) setBacktest(bt)
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { /* retry on next tick */ } finally { setLoading(false) }
  }

  useEffect(() => { fetchAll(); const t = setInterval(fetchAll, 5000); return () => clearInterval(t) }, [])

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400">⚡</span>
      <span className="text-sm">Connecting to Prometheus...</span>
    </div>
  )

  const wsStatus = status.ws_status?.status ?? 'UNKNOWN'
  const wsColor = wsStatus === 'CONNECTED' ? 'text-green-400' : wsStatus === 'UNKNOWN' ? 'text-gray-500' : 'text-red-400'
  const wsDot = wsStatus === 'CONNECTED' ? 'bg-green-400 animate-pulse' : wsStatus === 'UNKNOWN' ? 'bg-gray-600' : 'bg-red-500'
  const wsSymbols = status.ws_status?.symbols
  const activeSignals = signals.filter(s => s.direction !== 'flat')
  const heatmapSymbols = markets.slice(0, 40)
  const shadowData = shadow.length ? shadow : (status.shadow?.leaderboard ?? [])
  const vixVal = status.macro_vix ?? 0

  // Top Performers: merge backtest + current signal data
  const topPerformers = backtest?.results
    ? Object.entries(backtest.results)
        .map(([sym, bt]) => ({
          symbol: sym,
          win_rate: bt.win_rate_pct,
          sharpe: bt.sharpe_ratio,
          ret: bt.total_return_pct,
          dd: bt.max_drawdown_pct,
          trades: bt.total_trades,
          score: bt.sharpe_ratio * (bt.win_rate_pct / 100),
          signal: signals.find(s => s.symbol === sym),
        }))
        .filter(p => p.trades > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 15)
    : []

  // Top Opportunities: active signals with backtest win rate enrichment
  const topOpps = [...activeSignals]
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 10)
    .map(sig => ({
      ...sig,
      btWR: backtest?.results?.[sig.symbol]?.win_rate_pct,
      btSharpe: backtest?.results?.[sig.symbol]?.sharpe_ratio,
    }))

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-white font-bold text-base">Overview</h1>
        <span className="text-xs text-gray-600">{lastUpdate ? `Updated ${lastUpdate}` : ''} · 5s refresh</span>
      </div>

      {/* ── Stat Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2.5">
        <StatCard label="WebSocket" value={wsStatus} sub={wsSymbols ? `${wsSymbols} symbols` : undefined} color={wsColor} dot={wsDot} />
        <StatCard label="Active Symbols" value={String(status.active_symbol_count ?? markets.length)} color="text-blue-400" />
        <StatCard label="Active Signals" value={String(activeSignals.length)} sub={`of ${signals.length} total`} color="text-orange-400" />
        <StatCard label="Best Genome" value={status.best_genome_fitness?.toFixed(4) ?? '—'} color="text-purple-400" />
        <StatCard label="Fear & Greed" value={String(status.fear_greed?.value ?? '—')} sub={status.fear_greed?.classification} color="text-yellow-400" />
        <StatCard label="VIX" value={vixVal ? vixVal.toFixed(1) : '—'} sub={vixVal > 40 ? 'EXTREME' : vixVal > 25 ? 'ELEVATED' : 'NORMAL'} color={vixVal > 40 ? 'text-red-400 animate-pulse' : vixVal > 25 ? 'text-orange-400' : 'text-green-400'} />
      </div>

      {/* ── Top Performers (Backtest ranked) ── */}
      {topPerformers.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-green-400 font-semibold text-sm uppercase tracking-wider">🏆 Top Performers</h2>
            <span className="text-xs text-gray-600">Ranked by Sharpe × Win Rate · Click for full analysis</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2">#</th>
                  <th className="text-left px-4 py-2">Symbol</th>
                  <th className="text-left px-4 py-2">Win Rate</th>
                  <th className="text-left px-4 py-2">Sharpe</th>
                  <th className="text-left px-4 py-2">Return</th>
                  <th className="text-left px-4 py-2">Max DD</th>
                  <th className="text-left px-4 py-2">Trades</th>
                  <th className="text-left px-4 py-2">Live Signal</th>
                  <th className="text-left px-4 py-2">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {topPerformers.map((p, i) => (
                  <tr key={p.symbol}
                    className="border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors cursor-pointer"
                    onClick={() => window.location.href = `/coin/${p.symbol}`}>
                    <td className="px-4 py-2.5 text-gray-600 text-xs">
                      {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `#${i + 1}`}
                    </td>
                    <td className="px-4 py-2.5 font-bold text-white hover:text-orange-400 transition-colors">
                      {p.symbol.replace('USDT', '')}<span className="text-gray-600">/USDT</span>
                    </td>
                    <td className="px-4 py-2.5"><WinRateBadge wr={p.win_rate} /></td>
                    <td className={`px-4 py-2.5 font-mono font-bold text-xs ${p.sharpe >= 1.5 ? 'text-green-400' : p.sharpe >= 1 ? 'text-yellow-400' : 'text-gray-400'}`}>
                      {p.sharpe.toFixed(2)}
                    </td>
                    <td className={`px-4 py-2.5 font-mono text-xs ${p.ret >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {p.ret >= 0 ? '+' : ''}{p.ret.toFixed(1)}%
                    </td>
                    <td className={`px-4 py-2.5 font-mono text-xs ${p.dd < 10 ? 'text-green-400' : 'text-red-400'}`}>
                      {p.dd.toFixed(1)}%
                    </td>
                    <td className="px-4 py-2.5 text-gray-400 text-xs">{p.trades}</td>
                    <td className="px-4 py-2.5">
                      {p.signal
                        ? <span className={`text-xs px-2 py-0.5 rounded font-bold border ${DIR_STYLE[p.signal.direction]}`}>{p.signal.direction.toUpperCase()}</span>
                        : <span className="text-gray-700 text-xs">—</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      {p.signal ? <ConfidenceBar value={p.signal.confidence} /> : <span className="text-gray-700 text-xs">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Top Opportunities (Live Signals) ── */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">⚡ Live Opportunities</h2>
          <span className="text-xs text-gray-600">{topOpps.length} active · Click for chart & AI analysis</span>
        </div>
        {topOpps.length === 0 ? (
          <p className="text-gray-500 text-sm p-4">No active signals — market may be in flat regime</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2">Symbol</th>
                  <th className="text-left px-4 py-2">Direction</th>
                  <th className="text-left px-4 py-2">Confidence</th>
                  <th className="text-left px-4 py-2">RSI-14</th>
                  <th className="text-left px-4 py-2">Regime</th>
                  <th className="text-left px-4 py-2">Kelly%</th>
                  <th className="text-left px-4 py-2">BT Win Rate</th>
                  <th className="text-left px-4 py-2">BT Sharpe</th>
                  <th className="text-left px-4 py-2">Drift</th>
                </tr>
              </thead>
              <tbody>
                {topOpps.map(sig => {
                  const mkt = markets.find(m => m.symbol === sig.symbol)
                  return (
                    <tr key={sig.symbol}
                      className="border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors cursor-pointer"
                      onClick={() => window.location.href = `/coin/${sig.symbol}`}>
                      <td className="px-4 py-2.5 font-bold text-white hover:text-orange-400 transition-colors">
                        {sig.symbol}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${DIR_STYLE[sig.direction]}`}>{sig.direction.toUpperCase()}</span>
                      </td>
                      <td className="px-4 py-2.5"><ConfidenceBar value={sig.confidence} /></td>
                      <td className={`px-4 py-2.5 font-mono text-xs ${rsiTextColor(mkt?.rsi_14 ?? sig.rsi ?? 50)}`}>
                        {(mkt?.rsi_14 ?? sig.rsi)?.toFixed(1) ?? '—'}
                      </td>
                      <td className={`px-4 py-2.5 text-xs ${REGIME_COLOR[sig.regime] ?? 'text-gray-400'}`}>{sig.regime ?? '—'}</td>
                      <td className="px-4 py-2.5 text-gray-300 text-xs">{((sig.kelly_fraction ?? 0) * 100).toFixed(1)}%</td>
                      <td className="px-4 py-2.5">
                        {sig.btWR != null ? <WinRateBadge wr={sig.btWR} /> : <span className="text-gray-700 text-xs">—</span>}
                      </td>
                      <td className={`px-4 py-2.5 font-mono text-xs ${(sig.btSharpe ?? 0) >= 1.5 ? 'text-green-400' : (sig.btSharpe ?? 0) >= 1 ? 'text-yellow-400' : 'text-gray-500'}`}>
                        {sig.btSharpe != null ? sig.btSharpe.toFixed(2) : '—'}
                      </td>
                      <td className={`px-4 py-2.5 text-xs font-semibold ${DRIFT_COLOR[sig.drift_status] ?? 'text-gray-400'}`}>{sig.drift_status}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── RSI Heatmap ── */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">Market Heatmap — RSI</h2>
          <div className="flex items-center gap-3 text-xs text-gray-600">
            <span className="text-blue-400">■</span> Oversold
            <span className="text-green-400">■</span> Bullish
            <span className="text-gray-400">■</span> Neutral
            <span className="text-orange-400">■</span> Bearish
            <span className="text-red-400">■</span> Overbought
            <span className="text-gray-600">· Click for chart</span>
          </div>
        </div>
        <div className="p-3 grid grid-cols-5 sm:grid-cols-8 md:grid-cols-10 lg:grid-cols-15 gap-1.5">
          {heatmapSymbols.map(m => (
            <a key={m.symbol} href={`/coin/${m.symbol}`}
              className={`border rounded p-1.5 text-center transition-all cursor-pointer ${rsiTileColor(m.rsi_14)}`}>
              <p className="text-xs font-bold text-white truncate leading-tight">{m.symbol.replace('USDT', '')}</p>
              <p className={`text-xs font-mono ${rsiTextColor(m.rsi_14)}`}>{m.rsi_14?.toFixed(0) ?? '—'}</p>
              <p className="text-xs leading-none mt-0.5">{m.direction === 'long' ? '▲' : m.direction === 'short' ? '▼' : <span className="text-gray-600">–</span>}</p>
            </a>
          ))}
          {heatmapSymbols.length === 0 && <p className="col-span-10 text-gray-500 text-sm py-4 text-center">Loading market data...</p>}
        </div>
      </div>

      {/* ── Shadow Leaderboard ── */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800">
          <h2 className="text-purple-400 font-semibold text-sm uppercase tracking-wider">👻 Shadow Leaderboard</h2>
        </div>
        {shadowData.length === 0 ? (
          <p className="text-gray-500 text-sm p-4">Shadow system warming up — requires 100 trades to evaluate...</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800 text-xs bg-gray-900/60">
                <th className="text-left px-4 py-2">Universe</th>
                <th className="text-left px-4 py-2">Sharpe</th>
                <th className="text-left px-4 py-2">Win Rate</th>
                <th className="text-left px-4 py-2">Trades</th>
                <th className="text-left px-4 py-2">Return</th>
                <th className="text-left px-4 py-2">Max DD</th>
                <th className="text-left px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {shadowData.map(s => (
                <tr key={s.shadow_id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="px-4 py-2.5 font-semibold text-white">{s.shadow_id}</td>
                  <td className={`px-4 py-2.5 font-mono ${s.sharpe >= 1.5 ? 'text-green-400' : s.sharpe >= 1.0 ? 'text-yellow-400' : 'text-gray-400'}`}>{s.sharpe?.toFixed(2) ?? '—'}</td>
                  <td className={`px-4 py-2.5 font-mono ${s.win_rate >= 0.52 ? 'text-green-400' : 'text-gray-400'}`}>{((s.win_rate ?? 0) * 100).toFixed(1)}%</td>
                  <td className="px-4 py-2.5 text-gray-300">{s.trades}</td>
                  <td className={`px-4 py-2.5 font-mono ${(s.return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>{((s.return ?? 0) * 100).toFixed(2)}%</td>
                  <td className={`px-4 py-2.5 font-mono ${(s.max_drawdown ?? 0) < 0.1 ? 'text-green-400' : 'text-red-400'}`}>{((s.max_drawdown ?? 0) * 100).toFixed(1)}%</td>
                  <td className="px-4 py-2.5">
                    {s.promotion_ready
                      ? <span className="bg-yellow-500/20 text-yellow-400 border border-yellow-500/40 px-2 py-0.5 rounded text-xs font-bold animate-pulse">🚀 READY</span>
                      : <span className="text-gray-600 text-xs">Training</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
