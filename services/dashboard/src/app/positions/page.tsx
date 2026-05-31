'use client'
import { useEffect, useState, Fragment } from 'react'
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Area, AreaChart,
} from 'recharts'
import { PositionDecisionPanel } from '@/components/PositionDecisionPanel'
import type { PositionDecision } from '@/lib/positions'

type Position = PositionDecision

interface Trade {
  symbol: string; direction: string; entry_price: number; exit_price: number
  pnl_pct: number; pnl_usdt: number; size_usd: number; closed_at: number
}

interface PositionData {
  positions: Position[]
  daily_pnl: number
  trade_history: Trade[]
  position_count: number
  trading_halted?: boolean
  halt_reason?: string | null
}

interface CurvePoint { ts: number; equity: number; pnl: number; symbol: string; direction: string }

interface PortfolioData {
  curve: CurvePoint[]
  stats: {
    start_equity: number; current_equity: number; total_pnl: number; total_pnl_pct: number
    daily_pnl: number; total_trades: number; win_rate: number; avg_win_usdt: number
    avg_loss_usdt: number; profit_factor: number | null; max_drawdown_pct: number
  }
}

const DIR_STYLE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-800/50',
  short: 'text-red-400 bg-red-900/30 border border-red-800/50',
}

function fmtPrice(p: number | null | undefined) {
  if (p == null || !p) return '—'
  if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (p >= 1) return p.toFixed(4)
  return p.toFixed(6)
}

function timeAgo(ts: number) {
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function fmtTs(ts: number) {
  return new Date(ts * 1000).toLocaleDateString('tr-TR', { month: 'short', day: 'numeric' })
}

function PnLBar({ pct }: { pct: number }) {
  const abs = Math.min(Math.abs(pct), 10)
  const width = (abs / 10) * 100
  const color = pct >= 0 ? 'bg-green-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${width}%` }} />
      </div>
      <span className={`text-xs font-mono tabular-nums font-bold ${pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
        {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
      </span>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center space-y-3">
      <div className="text-4xl">📭</div>
      <p className="text-white font-semibold">No Open Positions</p>
      <p className="text-gray-500 text-sm max-w-sm mx-auto">
        The OMS is in Paper/DRY_RUN mode. Positions open when the signal engine generates valid signals
        with confidence ≥ 60% that pass immunity system checks.
      </p>
      <div className="flex flex-wrap justify-center gap-2 mt-4 text-xs text-gray-600">
        <span className="bg-gray-800 px-2 py-1 rounded">Min confidence: 60%</span>
        <span className="bg-gray-800 px-2 py-1 rounded">Max 3 concurrent positions</span>
        <span className="bg-gray-800 px-2 py-1 rounded">Max size: 5% portfolio</span>
      </div>
    </div>
  )
}

function EquityCurve({ curve }: { curve: CurvePoint[] }) {
  if (curve.length < 2) {
    return (
      <div className="h-40 flex items-center justify-center text-gray-600 text-sm">
        Equity curve will appear after first closed trade
      </div>
    )
  }
  const start = curve[0]?.equity ?? 10000
  const isPositive = (curve[curve.length - 1]?.equity ?? start) >= start
  const gradId = 'eqGrad'

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: { payload: CurvePoint }[] }) => {
    if (!active || !payload?.length) return null
    const d = payload[0].payload
    const pnl = d.equity - start
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-2.5 text-xs shadow-xl">
        <p className="text-gray-400">{fmtTs(d.ts)}</p>
        <p className="text-white font-bold font-mono">${d.equity.toLocaleString('en-US', { maximumFractionDigits: 2 })}</p>
        <p className={`font-mono font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
        </p>
        {d.symbol && <p className="text-gray-500 mt-0.5">{d.symbol} {d.direction}</p>}
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={curve} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={isPositive ? '#16a34a' : '#dc2626'} stopOpacity={0.25} />
            <stop offset="95%" stopColor={isPositive ? '#16a34a' : '#dc2626'} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
        <XAxis dataKey="ts" tickFormatter={fmtTs} tick={{ fill: '#6b7280', fontSize: 10 }}
          tickLine={false} axisLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false}
          tickFormatter={v => `$${(v / 1000).toFixed(1)}K`} width={52} domain={['auto', 'auto']} />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine y={start} stroke="#374151" strokeDasharray="4 4" strokeWidth={1} />
        <Area
          type="monotone" dataKey="equity" stroke={isPositive ? '#16a34a' : '#dc2626'}
          strokeWidth={2} fill={`url(#${gradId})`} dot={false} activeDot={{ r: 4, fill: isPositive ? '#16a34a' : '#dc2626' }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export default function PositionsPage() {
  const [data, setData] = useState<PositionData | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [emergencyBusy, setEmergencyBusy] = useState(false)
  const [emergencyMsg, setEmergencyMsg] = useState('')
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null)

  const fetchData = async () => {
    try {
      const [posRes, portRes] = await Promise.all([
        fetch('/api/positions'),
        fetch('/api/portfolio'),
      ])
      if (posRes.ok) setData(await posRes.json())
      if (portRes.ok) setPortfolio(await portRes.json())
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { /* retry */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 5000)
    return () => clearInterval(t)
  }, [])

  const runEmergencyClose = async () => {
    const ok = window.confirm(
      'ACİL DURUM: Tüm açık pozisyonlar (OMS + Shadow) hemen kapatılacak ve yeni işlem açılması durdurulacak.\n\nDevam edilsin mi?'
    )
    if (!ok) return
    setEmergencyBusy(true)
    setEmergencyMsg('')
    try {
      const res = await fetch('/api/emergency', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'close_all' }),
      })
      const j = await res.json()
      setEmergencyMsg(j.message ?? (res.ok ? 'Tetiklendi' : j.error ?? 'Hata'))
      await fetchData()
    } catch (e) {
      setEmergencyMsg(String(e))
    } finally {
      setEmergencyBusy(false)
    }
  }

  const resumeTrading = async () => {
    if (!window.confirm('İşlem duraklatması kaldırılsın mı? (Pozisyon açma tekrar aktif olur)')) return
    setEmergencyBusy(true)
    try {
      const res = await fetch('/api/emergency', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'resume' }),
      })
      const j = await res.json()
      setEmergencyMsg(j.message ?? 'İşlem duraklatması kaldırıldı')
      await fetchData()
    } finally {
      setEmergencyBusy(false)
    }
  }

  const restartTrading = async () => {
    setEmergencyBusy(true)
    setEmergencyMsg('')
    try {
      const res = await fetch('/api/emergency', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'restart_trading' }),
      })
      const j = await res.json()
      setEmergencyMsg(j.message ?? (res.ok ? 'Tarama yenilendi' : j.error ?? 'Hata'))
      await fetchData()
    } catch (e) {
      setEmergencyMsg(String(e))
    } finally {
      setEmergencyBusy(false)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400">⚡</span>
      <span>Loading positions...</span>
    </div>
  )

  const { positions = [], daily_pnl = 0, trade_history = [], trading_halted = false, halt_reason } = data ?? {}
  const totalUnrealized = positions.reduce((s, p) => s + (p.unrealized_usdt ?? 0), 0)
  const totalExposed = positions.reduce((s, p) => s + p.size_usd, 0)
  const winTrades = trade_history.filter(t => t.pnl_pct > 0).length
  const winRate = trade_history.length > 0 ? (winTrades / trade_history.length * 100) : 0
  const stats = portfolio?.stats
  const curve = portfolio?.curve ?? []

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-white font-bold text-base">Portfolio — Paper Trading</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            OMS + Shadow · AI koruyucu ~1s · öğrenme açık pozisyonlarda öncelikli
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {trading_halted ? (
            <button
              type="button"
              onClick={resumeTrading}
              disabled={emergencyBusy}
              className="px-3 py-1.5 rounded-lg text-xs font-bold bg-yellow-900/40 border border-yellow-700 text-yellow-300 hover:bg-yellow-900/60"
            >
              ▶ İşleme Devam
            </button>
          ) : (
            <button
              type="button"
              onClick={runEmergencyClose}
              disabled={emergencyBusy}
              className="px-4 py-2 rounded-lg text-xs font-black bg-red-700 hover:bg-red-600 text-white border border-red-500 shadow-lg shadow-red-900/40 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {emergencyBusy ? '⏳ Kapatılıyor...' : '🛑 ACİL DURUM — Tümünü Kapat'}
            </button>
          )}
          <button
            type="button"
            onClick={restartTrading}
            disabled={emergencyBusy}
            className="px-4 py-2 rounded-lg text-xs font-bold bg-green-800/50 border border-green-600 text-green-300 hover:bg-green-800/70 disabled:opacity-40"
            title="Duraklatmayı kaldırır, portfolio ve sinyal taramasını yeniler"
          >
            {emergencyBusy ? '⏳...' : '⟳ İşlem Yeniden Başlat'}
          </button>
          <span className="text-xs text-gray-600">{lastUpdate} · 5s</span>
        </div>
      </div>

      {trading_halted && (
        <div className="bg-red-950/50 border border-red-700 rounded-xl px-4 py-3 text-sm text-red-200">
          <span className="font-bold">⛔ İşlemler duraklatıldı</span>
          {halt_reason && <span className="text-red-300/80"> — {halt_reason}</span>}
        </div>
      )}
      {emergencyMsg && (
        <p className="text-xs text-orange-300 bg-orange-950/30 border border-orange-800/50 rounded-lg px-3 py-2">{emergencyMsg}</p>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Open Positions</p>
          <p className={`text-2xl font-black ${positions.length > 0 ? 'text-white' : 'text-gray-600'}`}>
            {positions.length} <span className="text-sm font-normal text-gray-500">/ 3 max</span>
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Unrealized P&L</p>
          <p className={`text-2xl font-black ${totalUnrealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {totalUnrealized >= 0 ? '+' : ''}${totalUnrealized.toFixed(2)}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Daily Realized P&L</p>
          <p className={`text-2xl font-black ${daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {daily_pnl >= 0 ? '+' : ''}${daily_pnl.toFixed(2)}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Today's Win Rate</p>
          <p className={`text-2xl font-black ${winRate >= 52 ? 'text-green-400' : winRate > 0 ? 'text-yellow-400' : 'text-gray-600'}`}>
            {trade_history.length > 0 ? `${winRate.toFixed(0)}%` : '—'}
          </p>
          <p className="text-xs text-gray-600">{winTrades}/{trade_history.length} trades</p>
        </div>
      </div>

      {/* Portfolio equity curve */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">📈 Equity Curve</h2>
          {stats && (
            <div className="flex items-center gap-4 text-xs">
              <span className="text-gray-500">
                Start: <span className="text-gray-300 font-mono">${stats.start_equity.toLocaleString()}</span>
              </span>
              <span className="text-gray-500">
                Now: <span className="text-white font-bold font-mono">${stats.current_equity.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
              </span>
              <span className={stats.total_pnl >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
                {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)} ({stats.total_pnl_pct >= 0 ? '+' : ''}{stats.total_pnl_pct.toFixed(2)}%)
              </span>
            </div>
          )}
        </div>
        <div className="p-4">
          <EquityCurve curve={curve} />
        </div>
        {stats && stats.total_trades > 0 && (
          <div className="px-4 pb-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-gray-800/50 rounded-lg p-2.5 text-center">
              <p className="text-gray-500 text-xs">Total Trades</p>
              <p className="text-white font-bold">{stats.total_trades}</p>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-2.5 text-center">
              <p className="text-gray-500 text-xs">Win Rate</p>
              <p className={`font-bold ${stats.win_rate >= 52 ? 'text-green-400' : 'text-yellow-400'}`}>{stats.win_rate.toFixed(1)}%</p>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-2.5 text-center">
              <p className="text-gray-500 text-xs">Profit Factor</p>
              <p className={`font-bold font-mono ${stats.profit_factor != null && stats.profit_factor >= 1.5 ? 'text-green-400' : 'text-yellow-400'}`}>
                {stats.profit_factor != null ? stats.profit_factor.toFixed(2) : '—'}
              </p>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-2.5 text-center">
              <p className="text-gray-500 text-xs">Max Drawdown</p>
              <p className={`font-bold font-mono ${stats.max_drawdown_pct < 5 ? 'text-green-400' : stats.max_drawdown_pct < 10 ? 'text-yellow-400' : 'text-red-400'}`}>
                {stats.max_drawdown_pct.toFixed(2)}%
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Exposure bar */}
      {totalExposed > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex justify-between text-xs text-gray-400">
            <span>Capital Exposed</span>
            <span>${totalExposed.toFixed(0)} / $10,000 portfolio (max $500)</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-orange-500 rounded-full transition-all"
              style={{ width: `${Math.min(totalExposed / 500 * 100, 100)}%` }}
            />
          </div>
          <p className="text-xs text-gray-600">{(totalExposed / 10000 * 100).toFixed(2)}% of portfolio · Max 5% per position</p>
        </div>
      )}

      {/* Open Positions */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">⚡ Open Positions</h2>
          <span className="text-xs text-gray-600">{positions.length} active</span>
        </div>

        {positions.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5">Direction</th>
                  <th className="text-left px-4 py-2.5">Entry</th>
                  <th className="text-left px-4 py-2.5">Current</th>
                  <th className="text-left px-4 py-2.5">Size</th>
                  <th className="text-left px-4 py-2.5">Unrealized P&L</th>
                  <th className="text-left px-4 py-2.5">Unrealized $</th>
                  <th className="text-left px-4 py-2.5">Age</th>
                  <th className="text-left px-4 py-2.5">Confidence</th>
                  <th className="text-left px-4 py-2.5">Regime</th>
                  <th className="text-left px-4 py-2.5">AI</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => {
                  const exp = expandedSymbol === pos.symbol
                  const entry = pos.entry_signal ?? {}
                  const regime = String(entry.regime ?? pos.verdict?.direction ?? '—')
                  return (
                  <Fragment key={pos.symbol}>
                  <tr
                    className={`border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors cursor-pointer ${
                      (pos.unrealized_pct ?? 0) > 0.5 ? 'bg-green-950/10' :
                      (pos.unrealized_pct ?? 0) < -0.5 ? 'bg-red-950/10' : ''
                    }`}
                    onClick={() => setExpandedSymbol(exp ? null : pos.symbol)}>
                    <td className="px-4 py-3 font-bold text-white">{pos.symbol}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-bold border ${DIR_STYLE[pos.direction] ?? ''}`}>
                        {pos.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-300">{fmtPrice(pos.entry_price)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-white">{fmtPrice(pos.current_price)}</td>
                    <td className="px-4 py-3 text-xs text-gray-300">${pos.size_usd.toFixed(0)}</td>
                    <td className="px-4 py-3"><PnLBar pct={pos.unrealized_pct ?? 0} /></td>
                    <td className={`px-4 py-3 font-mono text-xs font-bold ${(pos.unrealized_usdt ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {(pos.unrealized_usdt ?? 0) >= 0 ? '+' : ''}${(pos.unrealized_usdt ?? 0).toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {(pos.age_hours ?? 0) < 1 ? `${Math.round((pos.age_hours ?? 0) * 60)}m` : `${(pos.age_hours ?? 0).toFixed(1)}h`}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {entry.confidence != null ? `${Math.round(Number(entry.confidence) <= 1 ? Number(entry.confidence) * 100 : Number(entry.confidence))}%` : '—'}
                    </td>
                    <td className={`px-4 py-3 text-xs ${
                      regime === 'trending_up' ? 'text-green-400' :
                      regime === 'trending_down' ? 'text-red-400' :
                      regime === 'volatile' ? 'text-yellow-400' : 'text-blue-400'
                    }`}>
                      {regime}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 max-w-[200px] truncate" title={pos.open_reason}>
                      {exp ? '▲' : '▼'} {pos.open_reason?.slice(0, 48) ?? '—'}
                    </td>
                  </tr>
                  {exp && (
                    <tr className="bg-gray-950/50">
                      <td colSpan={10}>
                        <PositionDecisionPanel pos={pos} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                )})}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Trade History */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">📋 Recent Trades</h2>
          <span className="text-xs text-gray-600">Last {trade_history.length} closed trades</span>
        </div>

        {trade_history.length === 0 ? (
          <p className="text-gray-500 text-sm p-6 text-center">No closed trades yet — waiting for positions to close</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5">Direction</th>
                  <th className="text-left px-4 py-2.5">Entry</th>
                  <th className="text-left px-4 py-2.5">Exit</th>
                  <th className="text-left px-4 py-2.5">Size</th>
                  <th className="text-left px-4 py-2.5">P&L %</th>
                  <th className="text-left px-4 py-2.5">P&L $</th>
                  <th className="text-left px-4 py-2.5">Closed</th>
                </tr>
              </thead>
              <tbody>
                {trade_history.map((trade, i) => (
                  <tr key={i}
                    className="border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors cursor-pointer"
                    onClick={() => window.location.href = `/coin/${trade.symbol}`}>
                    <td className="px-4 py-2.5 font-bold text-white hover:text-orange-400 transition-colors">{trade.symbol}</td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs px-1.5 py-0.5 rounded font-bold border ${DIR_STYLE[trade.direction] ?? 'text-gray-400'}`}>
                        {trade.direction === 'long' ? '▲' : '▼'} {trade.direction?.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-400">{fmtPrice(trade.entry_price)}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-300">{fmtPrice(trade.exit_price)}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-400">${trade.size_usd?.toFixed(0) ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`font-mono text-xs font-bold ${trade.pnl_pct > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {trade.pnl_pct > 0 ? '+' : ''}{(trade.pnl_pct * 100).toFixed(2)}%
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 font-mono text-xs font-bold ${trade.pnl_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {trade.pnl_usdt >= 0 ? '+' : ''}${trade.pnl_usdt?.toFixed(2) ?? '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">
                      {trade.closed_at ? timeAgo(trade.closed_at) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
