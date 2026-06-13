'use client'
import { useEffect, useState, Fragment, useCallback, useMemo } from 'react'
import { PositionDecisionPanel } from '@/components/PositionDecisionPanel'
import RiskLimitsEditor from '@/components/RiskLimitsEditor'
import PortfolioCapitalEditor from '@/components/PortfolioCapitalEditor'
import { ExitCountdownCell } from '@/components/ExitCountdownCell'
import { LeverageBadge } from '@/components/LeverageBadge'
import { MotorEngineBar, LearnStageBadge, LessonSnippet } from '@/components/MotorEngineBar'
import { LiveEquityChart, type CurvePoint } from '@/components/LiveEquityChart'
import { PositionBubbleChart, buildBubblePoints } from '@/components/PositionBubbleChart'
import { LivePnLBanner } from '@/components/LivePnLBanner'
import { useLiveEquity } from '@/hooks/useLiveEquity'
import { useLivePositionPnL } from '@/hooks/useLivePositionPnL'
import { useStreamInvalidate } from '@/hooks/useStream'
import type { PositionDecision } from '@/lib/positions'

type Position = PositionDecision

interface Trade {
  symbol: string; direction: string; entry_price: number; exit_price: number
  pnl_pct: number; pnl_usdt: number; size_usd: number; closed_at: number
  leverage?: number; exit_reason?: string; close_reason?: string
  hold_seconds?: number; fee_total_usd?: number; margin_usd?: number
}

interface ActivityEvent {
  type?: string
  symbol?: string
  direction?: string
  confidence?: number
  ts?: number
  timestamp?: number
  message?: string
  source?: string
}

interface PositionData {
  positions: Position[]
  daily_pnl: number
  trade_history: Trade[]
  position_count: number
  trading_halted?: boolean
  halt_reason?: string | null
}

interface PortfolioData {
  curve: CurvePoint[]
  stats: {
    start_equity: number; current_equity: number; realized_equity?: number; unrealized_usdt?: number
    portfolio_try?: number | null; usd_try_rate?: number | null; fee_per_side_pct?: number | null
    total_pnl: number; total_pnl_pct: number
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

function fmtDateTime(ts: number) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('tr-TR', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function PnLBar({ pct }: { pct: number }) {
  const abs = Math.min(Math.abs(pct), 10)
  const width = (abs / 10) * 100
  const color = pct >= 0 ? 'bg-green-500' : 'bg-red-500'
  const decimals = Math.abs(pct) < 1 ? 3 : 2
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all duration-300`} style={{ width: `${width}%` }} />
      </div>
      <span className={`text-sm font-mono tabular-nums font-black ${pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
        {pct >= 0 ? '+' : ''}{pct.toFixed(decimals)}%
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
        <span className="bg-gray-800 px-2 py-1 rounded">Max 30 concurrent positions</span>
        <span className="bg-gray-800 px-2 py-1 rounded">Bakiye dashboard&apos;dan ayarlanır</span>
      </div>
    </div>
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
  const [maxOpenLimit, setMaxOpenLimit] = useState(30)
  const [portfolioValue, setPortfolioValue] = useState(10000)
  const [maxPositionPct, setMaxPositionPct] = useState(0.05)
  const [streamLive, setStreamLive] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [activity, setActivity] = useState<ActivityEvent[]>([])

  const fetchData = useCallback(async () => {
    try {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 20000)
      const [posRes, portRes, capRes, actRes] = await Promise.all([
        fetch('/api/positions', { signal: controller.signal, cache: 'no-store' }),
        fetch('/api/portfolio', { signal: controller.signal, cache: 'no-store' }),
        fetch('/api/portfolio/capital', { signal: controller.signal, cache: 'no-store' }),
        fetch('/api/activity', { signal: controller.signal, cache: 'no-store' }),
      ])
      clearTimeout(timer)
      if (posRes.ok) {
        setData(await posRes.json())
        setLoadError('')
      } else {
        const body = await posRes.json().catch(() => ({}))
        setLoadError((body as { error?: string }).error ?? `positions API ${posRes.status}`)
      }
      if (portRes.ok) setPortfolio(await portRes.json())
      if (capRes.ok) {
        const cap = await capRes.json()
        if (cap.usd_cap) setPortfolioValue(cap.usd_cap)
      }
      if (actRes.ok) setActivity(await actRes.json())
      setLastUpdate(new Date().toLocaleTimeString())
    } catch (e) {
      setLoadError(e instanceof Error && e.name === 'AbortError'
        ? 'API zaman aşımı — Redis kontrol edin'
        : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const onStreamEvent = useCallback(() => {
    fetchData()
  }, [fetchData])

  const { connected: sseConnected } = useStreamInvalidate({
    hints: ['trade_closed', 'portfolio', 'guard', 'emergency'],
    onEvent: onStreamEvent,
    debounceMs: 200,
  })

  useEffect(() => {
    setStreamLive(sseConnected)
  }, [sseConnected])

  useEffect(() => {
    fetchData()
    fetch('/api/risk-limits')
      .then(r => r.json())
      .then(d => {
        if (d.limits?.max_open_positions) setMaxOpenLimit(d.limits.max_open_positions)
        if (d.limits?.max_position_pct) setMaxPositionPct(d.limits.max_position_pct)
      })
      .catch(() => {})
    const t = setInterval(fetchData, 2000)
    return () => clearInterval(t)
  }, [fetchData])

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

  const basePositions = data?.positions ?? []
  const daily_pnl = data?.daily_pnl ?? 0
  const trade_history = data?.trade_history ?? []
  const trading_halted = data?.trading_halted ?? false
  const halt_reason = data?.halt_reason
  const stats = portfolio?.stats
  const curve = portfolio?.curve ?? []
  const {
    positions,
    totalUnrealized,
    liveAt,
    isLive: pnlLive,
  } = useLivePositionPnL(basePositions, basePositions.length > 0)
  const liveCurve = useLiveEquity(curve, stats?.current_equity, 2000)
  const bubblePoints = useMemo(
    () => buildBubblePoints(positions, trade_history),
    [positions, trade_history],
  )

  const tradeTimeline = useMemo(() => {
    const items: { ts: number; label: string; kind: 'open' | 'close' | 'signal' | 'other' }[] = []
    for (const p of positions) {
      if (p.entry_time) {
        items.push({
          ts: p.entry_time,
          kind: 'open',
          label: `ALIM ${p.symbol} ${p.direction.toUpperCase()} ${p.leverage ?? 1}x · margin $${(p.margin_usd ?? p.size_usd).toFixed(0)} · ${p.entry_at_label ?? ''}`,
        })
      }
    }
    for (const t of trade_history) {
      if (t.closed_at) {
        const exit = t.exit_reason || t.close_reason || 'kapanış'
        const lev = t.leverage ? ` ${t.leverage}x` : ''
        items.push({
          ts: t.closed_at,
          kind: 'close',
          label: `SATIŞ ${t.symbol} ${t.direction?.toUpperCase() ?? ''}${lev} · ${exit} · ${((t.pnl_pct ?? 0) * 100).toFixed(2)}%`,
        })
      }
    }
    for (const ev of activity) {
      const ts = Number(ev.ts ?? ev.timestamp ?? 0)
      if (!ts) continue
      if (ev.type === 'signal' && ev.symbol) {
        items.push({
          ts: ts > 1e12 ? ts / 1000 : ts,
          kind: 'signal',
          label: `SİNYAL ${ev.symbol} ${String(ev.direction ?? '').toUpperCase()} conf ${Math.round((ev.confidence ?? 0) * 100)}%`,
        })
      }
    }
    return items.sort((a, b) => b.ts - a.ts).slice(0, 25)
  }, [positions, trade_history, activity])

  if (loading && !data && !loadError) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400">⚡</span>
      <span>Pozisyonlar yükleniyor…</span>
    </div>
  )

  if (!data && loadError) return (
    <div className="max-w-lg mx-auto mt-20 space-y-4 text-center">
      <p className="text-red-400 font-bold">Pozisyonlar yüklenemedi</p>
      <p className="text-gray-500 text-sm font-mono">{loadError}</p>
      <button
        type="button"
        onClick={() => { setLoading(true); fetchData() }}
        className="px-4 py-2 rounded-lg bg-orange-800 text-white text-sm font-bold"
      >
        Tekrar dene
      </button>
      <p className="text-xs text-gray-600 text-left bg-gray-900 border border-gray-800 rounded-lg p-3">
        Al/sat için pipeline çalışmalı: data_ingestion, feature_engine, signal_engine, oms, shadow_system.
        <br />
        <code className="text-gray-400">cd ~/prometheus && bash scripts/server-deploy-full.sh</code>
      </p>
    </div>
  )


  const totalExposed = positions.reduce((s, p) => s + (p.margin_usd ?? p.size_usd), 0)
  const totalNotional = positions.reduce((s, p) => s + (p.notional_usd ?? p.size_usd), 0)
  const winTrades = trade_history.filter(t => t.pnl_pct > 0).length
  const winRate = trade_history.length > 0 ? (winTrades / trade_history.length * 100) : 0

  return (
    <div className="space-y-5">
      {/* KASA — en üstte, kaçırılmaz */}
      <PortfolioCapitalEditor openCount={positions.length} maxOpen={maxOpenLimit} />

      <MotorEngineBar
        openCount={positions.length}
        maxOpen={maxOpenLimit}
        streamLive={streamLive}
        pollingActive
        tradingHalted={trading_halted}
      />

      {positions.length > 0 && (
        <LivePnLBanner
          totalUsdt={totalUnrealized}
          dailyPnl={daily_pnl}
          positionCount={positions.length}
          liveAt={liveAt}
          isLive={pnlLive}
        />
      )}

      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-white font-bold text-base">Portfolio — Paper Trading</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            OMS + Shadow · kaldıraç & alım/satım logları · kasa yukarıda ayarlanır
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
          <span className="text-xs text-gray-600 flex items-center gap-1.5">
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${streamLive ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            {lastUpdate} · {pnlLive ? 'PnL 1sn' : streamLive ? 'canlı 2s' : '2s'}
          </span>
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

      <RiskLimitsEditor openCount={positions.length} />

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Open Positions</p>
          <p className={`text-2xl font-black ${positions.length > 0 ? 'text-white' : 'text-gray-600'}`}>
            {positions.length}{' '}
            <span className="text-sm font-normal text-gray-500">/ {maxOpenLimit} max</span>
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

      {/* Equity + pozisyon balonları — yan yana canlı */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">📈 Equity Curve (canlı)</h2>
            <span className="text-[10px] text-green-500/80 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              2sn güncelleme
            </span>
          </div>
          <div className="p-4">
            {stats && (
              <div className="flex items-center gap-3 text-xs flex-wrap mb-3">
                <span className="text-gray-500">
                  Başlangıç: <span className="text-gray-300 font-mono">${stats.start_equity.toLocaleString()}</span>
                </span>
                <span className="text-gray-500">
                  Şimdi: <span className="text-white font-bold font-mono">${stats.current_equity.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
                </span>
                <span className={stats.total_pnl >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
                  {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)} ({stats.total_pnl_pct >= 0 ? '+' : ''}{stats.total_pnl_pct.toFixed(2)}%)
                </span>
              </div>
            )}
            <LiveEquityChart curve={liveCurve} startEquity={stats?.start_equity ?? 10000} height={200} />
          </div>
          {stats && stats.total_trades > 0 && (
            <div className="px-4 pb-4 grid grid-cols-2 gap-2">
              <div className="bg-gray-800/50 rounded-lg p-2 text-center">
                <p className="text-gray-500 text-[10px]">Win Rate</p>
                <p className={`font-bold text-sm ${stats.win_rate >= 52 ? 'text-green-400' : 'text-yellow-400'}`}>{stats.win_rate.toFixed(1)}%</p>
              </div>
              <div className="bg-gray-800/50 rounded-lg p-2 text-center">
                <p className="text-gray-500 text-[10px]">Max DD</p>
                <p className={`font-bold text-sm font-mono ${stats.max_drawdown_pct < 10 ? 'text-green-400' : 'text-red-400'}`}>{stats.max_drawdown_pct.toFixed(2)}%</p>
              </div>
            </div>
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-violet-400 font-semibold text-sm uppercase tracking-wider">🫧 Pozisyon Balonları (canlı)</h2>
            <span className="text-[10px] text-gray-500">
              {positions.length} açık · {trade_history.length} kapanış
            </span>
          </div>
          <div className="p-4">
            <PositionBubbleChart points={bubblePoints} height={200} />
          </div>
          {stats?.unrealized_usdt != null && (
            <div className="px-4 pb-4 text-xs text-gray-500">
              Gerçekleşmemiş:{' '}
              <span className={stats.unrealized_usdt >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
                {stats.unrealized_usdt >= 0 ? '+' : ''}${stats.unrealized_usdt.toFixed(2)}
              </span>
            </div>
          )}
        </div>
      </div>

      {stats && stats.total_trades > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 text-center">
            <p className="text-gray-500 text-xs">Total Trades</p>
            <p className="text-white font-bold">{stats.total_trades}</p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 text-center">
            <p className="text-gray-500 text-xs">Profit Factor</p>
            <p className={`font-bold font-mono ${stats.profit_factor != null && stats.profit_factor >= 1.5 ? 'text-green-400' : 'text-yellow-400'}`}>
              {stats.profit_factor != null ? stats.profit_factor.toFixed(2) : '—'}
            </p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 text-center">
            <p className="text-gray-500 text-xs">Avg Win</p>
            <p className="text-green-400 font-bold font-mono">${stats.avg_win_usdt.toFixed(2)}</p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 text-center">
            <p className="text-gray-500 text-xs">Avg Loss</p>
            <p className="text-red-400 font-bold font-mono">${stats.avg_loss_usdt.toFixed(2)}</p>
          </div>
        </div>
      )}

      {/* Exposure bar */}
      {totalExposed > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex justify-between text-xs text-gray-400">
            <span>Capital Exposed</span>
            <span>
              Margin ${totalExposed.toFixed(0)} · Notional ${totalNotional.toFixed(0)} / ${portfolioValue.toLocaleString()} (
              max ${(portfolioValue * maxPositionPct).toFixed(0)}/pozisyon)
            </span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-orange-500 rounded-full transition-all"
              style={{ width: `${Math.min(totalExposed / portfolioValue * 100, 100)}%` }}
            />
          </div>
          <p className="text-xs text-gray-600">
            {(totalExposed / portfolioValue * 100).toFixed(2)}% portföy · Max {(maxPositionPct * 100).toFixed(0)}% / pozisyon
          </p>
        </div>
      )}

      {/* İşlem akışı */}
      {tradeTimeline.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="text-cyan-400 font-semibold text-sm uppercase tracking-wider">🕐 Alım / Satım akışı</h2>
            <p className="text-gray-600 text-xs mt-0.5">Açılışlar, kapanışlar ve son sinyaller — log takibi</p>
          </div>
          <ul className="divide-y divide-gray-800/60 max-h-64 overflow-y-auto text-xs">
            {tradeTimeline.map((item, i) => (
              <li key={i} className="px-4 py-2 flex gap-3 hover:bg-gray-800/20">
                <span className="text-gray-600 font-mono shrink-0 w-36">{fmtDateTime(item.ts)}</span>
                <span className={
                  item.kind === 'open' ? 'text-green-400' :
                  item.kind === 'close' ? 'text-orange-400' :
                  item.kind === 'signal' ? 'text-blue-400' : 'text-gray-400'
                }>
                  {item.kind === 'open' ? '▲' : item.kind === 'close' ? '▼' : '◆'}
                </span>
                <span className="text-gray-300">{item.label}</span>
              </li>
            ))}
          </ul>
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
                  <th className="text-left px-4 py-2.5">Dir</th>
                  <th className="text-left px-4 py-2.5">Alım kaldıracı</th>
                  <th className="text-left px-4 py-2.5">Alım zamanı</th>
                  <th className="text-left px-4 py-2.5">Tahmini satış ⏱</th>
                  <th className="text-left px-4 py-2.5">Öğrenme</th>
                  <th className="text-left px-4 py-2.5">Son ders</th>
                  <th className="text-left px-4 py-2.5">Entry</th>
                  <th className="text-left px-4 py-2.5">Now</th>
                  <th className="text-left px-4 py-2.5">Margin</th>
                  <th className="text-left px-4 py-2.5">Notional</th>
                  <th className="text-left px-4 py-2.5">Qty≈</th>
                  <th className="text-left px-4 py-2.5">uPnL</th>
                  <th className="text-left px-4 py-2.5">$uPnL</th>
                  <th className="text-left px-4 py-2.5">Çıkış planı</th>
                  <th className="text-left px-4 py-2.5">Conf</th>
                  <th className="text-left px-4 py-2.5">AI</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => {
                  const exp = expandedSymbol === pos.symbol
                  const regime = pos.regime ?? pos.context_regime ?? String(pos.current_signal?.regime ?? '—')
                  const confPct = pos.ai_confidence_pct ?? (
                    pos.verdict?.confidence != null
                      ? Math.round(pos.verdict.confidence * 100)
                      : null
                  )
                  const rowKey = `${pos.symbol}-${pos.direction}-${pos.source}`
                  return (
                  <Fragment key={rowKey}>
                  <tr
                    className={`border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors cursor-pointer ${
                      (pos.unrealized_pct ?? 0) > 0.5 ? 'bg-green-950/10' :
                      (pos.unrealized_pct ?? 0) < -0.5 ? 'bg-red-950/10' : ''
                    }`}
                    onClick={() => setExpandedSymbol(exp ? null : pos.symbol)}>
                    <td className="px-4 py-3 font-bold text-white">
                      {pos.symbol}
                      {pos.sources_label ? (
                        <span className="ml-1 text-[10px] text-gray-500 font-normal">({pos.sources_label})</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-bold border ${DIR_STYLE[pos.direction] ?? ''}`}>
                        {pos.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <LeverageBadge
                        entryLeverage={pos.entry_leverage ?? pos.leverage ?? 1}
                        reasons={pos.leverage_reasons}
                        notionalUsd={pos.notional_usd}
                        marginUsd={pos.margin_usd ?? pos.size_usd}
                      />
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 font-mono whitespace-nowrap">
                      {pos.entry_at_label ?? (pos.entry_time ? fmtDateTime(pos.entry_time) : '—')}
                    </td>
                    <td className="px-4 py-3">
                      <ExitCountdownCell pos={pos} />
                    </td>
                    <td className="px-4 py-3">
                      <LearnStageBadge
                        stage={pos.learning_stage}
                        winRate={pos.learn_win_rate}
                        trades={pos.learn_trades}
                      />
                      {pos.ladder?.learn_note && (
                        <span className="block text-[9px] text-amber-600/80 mt-0.5">{pos.ladder.learn_note}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <LessonSnippet
                        lesson={pos.last_lesson ?? pos.ladder?.entry_lesson}
                        avoid={pos.avoid_hint}
                        entryHint={pos.best_entry_hint}
                      />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-300">{fmtPrice(pos.entry_price)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-white">{fmtPrice(pos.current_price)}</td>
                    <td className="px-4 py-3 text-xs text-gray-300 font-mono">${(pos.margin_usd ?? pos.size_usd).toFixed(0)}</td>
                    <td className="px-4 py-3 text-xs text-violet-300 font-mono">${(pos.notional_usd ?? pos.size_usd).toFixed(0)}</td>
                    <td className="px-4 py-3 text-xs text-gray-500 font-mono">{pos.qty_estimate?.toFixed(4) ?? '—'}</td>
                    <td className="px-4 py-3"><PnLBar pct={pos.unrealized_pct ?? 0} /></td>
                    <td className={`px-4 py-3 font-mono text-sm font-black ${(pos.unrealized_usdt ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {(pos.unrealized_usdt ?? 0) >= 0 ? '+' : ''}${(pos.unrealized_usdt ?? 0).toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-[10px] text-gray-500 max-w-[140px]" title={pos.exit_plan}>
                      {pos.exit_plan ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {confPct != null ? `${confPct}%` : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 max-w-[180px] truncate" title={pos.open_reason}>
                      {exp ? '▲' : '▼'} {pos.open_reason?.slice(0, 40) ?? '—'}
                    </td>
                  </tr>
                  {exp && (
                    <tr className="bg-gray-950/50">
                      <td colSpan={17}>
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
                  <th className="text-left px-4 py-2.5">Dir</th>
                  <th className="text-left px-4 py-2.5">Lev</th>
                  <th className="text-left px-4 py-2.5">Entry</th>
                  <th className="text-left px-4 py-2.5">Exit</th>
                  <th className="text-left px-4 py-2.5">Margin</th>
                  <th className="text-left px-4 py-2.5">P&L %</th>
                  <th className="text-left px-4 py-2.5">P&L $</th>
                  <th className="text-left px-4 py-2.5">Tutma</th>
                  <th className="text-left px-4 py-2.5">Satış zamanı</th>
                  <th className="text-left px-4 py-2.5">Çıkış nedeni</th>
                </tr>
              </thead>
              <tbody>
                {trade_history.map((trade, i) => {
                  const exitR = trade.exit_reason || trade.close_reason || '—'
                  const pnlPct = Math.abs(trade.pnl_pct) <= 1 ? trade.pnl_pct * 100 : trade.pnl_pct
                  const lev = trade.leverage ?? (trade as { ladder?: { leverage?: number } }).ladder?.leverage
                  return (
                  <tr key={i}
                    className="border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors cursor-pointer"
                    onClick={() => window.location.href = `/coin/${trade.symbol}`}>
                    <td className="px-4 py-2.5 font-bold text-white hover:text-orange-400 transition-colors">{trade.symbol}</td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs px-1.5 py-0.5 rounded font-bold border ${DIR_STYLE[trade.direction] ?? 'text-gray-400'}`}>
                        {trade.direction === 'long' ? '▲' : '▼'} {trade.direction?.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-violet-400 text-xs">{lev ? `${lev}x` : '—'}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-400">{fmtPrice(trade.entry_price)}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-300">{fmtPrice(trade.exit_price)}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-400 font-mono">${trade.size_usd?.toFixed(0) ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`font-mono text-xs font-bold ${pnlPct > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {pnlPct > 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 font-mono text-xs font-bold ${trade.pnl_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {trade.pnl_usdt >= 0 ? '+' : ''}${trade.pnl_usdt?.toFixed(2) ?? '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 font-mono">
                      {trade.hold_seconds ? `${Math.round(trade.hold_seconds / 60)}dk` : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 font-mono whitespace-nowrap">
                      {trade.closed_at ? fmtDateTime(trade.closed_at) : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-orange-300/90 max-w-[200px] truncate" title={exitR}>
                      {exitR}
                    </td>
                  </tr>
                )})}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
