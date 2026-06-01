'use client'
import { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Area, AreaChart,
} from 'recharts'

interface Position {
  symbol: string; direction: string; size_usd: number
  entry_price: number; current_price: number | null; price_live: boolean
  entry_time: number; unrealized_pct: number; unrealized_usdt: number
  age_hours: number; sl_price: number | null; tp_price: number | null
  entry_signal?: { confidence: number; regime: string; drift_status: string }
}

interface Trade {
  trade_id?: string; symbol: string; direction: string; entry_price: number; exit_price: number
  pnl_pct: number; pnl_usdt: number; size_usd: number; closed_at: number; entry_time?: number
}

interface PositionData {
  positions: Position[]
  daily_pnl: number
  trade_history: Trade[]
  position_count: number
  max_positions: number
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
  long:  'text-green-400 bg-green-900/30 border border-green-800/50',
  short: 'text-red-400 bg-red-900/30 border border-red-800/50',
}

function fmtPrice(p: number | null) {
  if (!p) return '—'
  if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (p >= 1)    return p.toFixed(4)
  return p.toFixed(6)
}

function timeAgo(ts: number) {
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s < 60)    return `${s}s önce`
  if (s < 3600)  return `${Math.floor(s / 60)}dk önce`
  if (s < 86400) return `${Math.floor(s / 3600)}sa önce`
  return `${Math.floor(s / 86400)}g önce`
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

function LiveDot({ live }: { live: boolean }) {
  if (!live) return <span className="text-gray-700 text-[10px]">○</span>
  return (
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
    </span>
  )
}

function TpSlBar({ entry, current, tp, sl, direction }: {
  entry: number; current: number | null; tp: number | null; sl: number | null; direction: string
}) {
  if (!tp || !sl || !entry) return null
  const low  = direction === 'long' ? sl : tp
  const high = direction === 'long' ? tp : sl
  const range = high - low
  if (range <= 0) return null

  const entryPct   = ((entry   - low) / range) * 100
  const currentPct = current ? Math.min(100, Math.max(0, ((current - low) / range) * 100)) : null

  return (
    <div className="mt-1.5">
      <div className="relative h-1.5 bg-gray-700 rounded-full w-full">
        <div className="absolute left-0 h-full bg-red-800/60 rounded-l-full" style={{ width: `${entryPct}%` }} />
        <div className="absolute left-0 h-full bg-green-800/60 rounded-r-full" style={{ left: `${entryPct}%`, right: 0 }} />
        {/* Entry marker */}
        <div className="absolute top-1/2 -translate-y-1/2 w-0.5 h-3 bg-orange-400 rounded-full" style={{ left: `${entryPct}%` }} />
        {/* Current price marker */}
        {currentPct != null && (
          <div className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 bg-white rounded-full border border-gray-900" style={{ left: `${currentPct}%`, transform: 'translate(-50%, -50%)' }} />
        )}
      </div>
      <div className="flex justify-between text-[9px] text-gray-600 mt-0.5">
        <span className="text-red-500">{fmtPrice(sl)}</span>
        <span className="text-green-500">{fmtPrice(tp)}</span>
      </div>
    </div>
  )
}

function EmptyState({ maxPositions }: { maxPositions: number }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center space-y-3">
      <div className="text-4xl">📭</div>
      <p className="text-white font-semibold">Açık Pozisyon Yok</p>
      <p className="text-gray-500 text-sm max-w-sm mx-auto">
        OMS kağıt işlem modunda çalışıyor. Güven ≥ %60 olan geçerli sinyaller geldiğinde pozisyon açılır.
      </p>
      <div className="flex flex-wrap justify-center gap-2 mt-4 text-xs text-gray-600">
        <span className="bg-gray-800 px-2 py-1 rounded">Min güven: %60</span>
        <span className="bg-gray-800 px-2 py-1 rounded">Maks {maxPositions} eş zamanlı pozisyon</span>
        <span className="bg-gray-800 px-2 py-1 rounded">Trade başına maks %5 portföy</span>
      </div>
    </div>
  )
}

function EquityCurve({ curve }: { curve: CurvePoint[] }) {
  if (curve.length < 2) {
    return (
      <div className="h-40 flex items-center justify-center text-gray-600 text-sm">
        İlk trade kapandıktan sonra eşitlik eğrisi görünür
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
            <stop offset="5%"  stopColor={isPositive ? '#16a34a' : '#dc2626'} stopOpacity={0.25} />
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
        <Area type="monotone" dataKey="equity" stroke={isPositive ? '#16a34a' : '#dc2626'}
          strokeWidth={2} fill={`url(#${gradId})`} dot={false}
          activeDot={{ r: 4, fill: isPositive ? '#16a34a' : '#dc2626' }} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export default function PositionsPage() {
  const [data,      setData]      = useState<PositionData | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null)
  const [loading,   setLoading]   = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = async () => {
    try {
      const [posRes, portRes] = await Promise.all([
        fetch('/api/positions'),
        fetch('/api/portfolio'),
      ])
      if (posRes.ok)  setData(await posRes.json())
      if (portRes.ok) setPortfolio(await portRes.json())
      setLastUpdate(new Date().toLocaleTimeString('tr-TR'))
    } catch { /* retry */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 5000)
    return () => clearInterval(t)
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400">⚡</span>
      <span>Pozisyonlar yükleniyor...</span>
    </div>
  )

  const positions: Position[]  = Array.isArray(data?.positions)     ? data!.positions     : []
  const daily_pnl: number      = typeof data?.daily_pnl === 'number' ? data!.daily_pnl     : 0
  const trade_history: Trade[] = Array.isArray(data?.trade_history) ? data!.trade_history : []
  const maxPositions: number   = data?.max_positions ?? 20

  const totalUnrealized = positions.reduce((s, p) => s + (p.unrealized_usdt ?? 0), 0)
  const totalExposed    = positions.reduce((s, p) => s + (p.size_usd ?? 0), 0)
  const winTrades       = trade_history.filter(t => (t.pnl_pct ?? 0) > 0).length
  const winRate         = trade_history.length > 0 ? (winTrades / trade_history.length * 100) : 0
  const stats           = portfolio?.stats
  const curve: CurvePoint[] = Array.isArray(portfolio?.curve) ? portfolio!.curve : []

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-white font-bold text-base">Portföy — Kağıt İşlem</h1>
          <p className="text-gray-500 text-xs mt-0.5">OMS pozisyonları · DRY_RUN modu · 5s yenileme</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs text-green-400">
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-500" />
            </span>
            CANLI
          </span>
          <span className="text-xs text-gray-600">{lastUpdate}</span>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Açık Pozisyonlar</p>
          <p className={`text-2xl font-black ${positions.length > 0 ? 'text-white' : 'text-gray-600'}`}>
            {positions.length}
            <span className="text-sm font-normal text-gray-500"> / {maxPositions} maks</span>
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Gerçekleşmemiş K/Z</p>
          <p className={`text-2xl font-black ${totalUnrealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {totalUnrealized >= 0 ? '+' : ''}${totalUnrealized.toFixed(2)}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Günlük Gerçekleşen K/Z</p>
          <p className={`text-2xl font-black ${daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {daily_pnl >= 0 ? '+' : ''}${daily_pnl.toFixed(2)}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Bugünkü Kazanma Oranı</p>
          <p className={`text-2xl font-black ${winRate >= 52 ? 'text-green-400' : winRate > 0 ? 'text-yellow-400' : 'text-gray-600'}`}>
            {trade_history.length > 0 ? `%${winRate.toFixed(0)}` : '—'}
          </p>
          <p className="text-xs text-gray-600">{winTrades}/{trade_history.length} trade</p>
        </div>
      </div>

      {/* Equity Curve */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">📈 Eşitlik Eğrisi</h2>
          {stats && typeof stats.total_pnl === 'number' && (
            <div className="flex items-center gap-4 text-xs">
              <span className="text-gray-500">
                Başlangıç: <span className="text-gray-300 font-mono">${(stats.start_equity ?? 10000).toLocaleString()}</span>
              </span>
              <span className="text-gray-500">
                Şimdi: <span className="text-white font-bold font-mono">${(stats.current_equity ?? 10000).toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
              </span>
              <span className={stats.total_pnl >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
                {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)} (%{(stats.total_pnl_pct ?? 0).toFixed(2)})
              </span>
            </div>
          )}
        </div>
        <div className="p-4">
          <EquityCurve curve={curve} />
        </div>
        {stats && stats.total_trades > 0 && (
          <div className="px-4 pb-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Toplam Trade', val: String(stats.total_trades), color: 'text-white' },
              { label: 'Kazanma Oranı', val: `%${stats.win_rate.toFixed(1)}`, color: stats.win_rate >= 52 ? 'text-green-400' : 'text-yellow-400' },
              { label: 'Kâr Faktörü', val: stats.profit_factor != null ? stats.profit_factor.toFixed(2) : '—', color: (stats.profit_factor ?? 0) >= 1.5 ? 'text-green-400' : 'text-yellow-400' },
              { label: 'Maks Düşüş', val: `%${stats.max_drawdown_pct.toFixed(2)}`, color: stats.max_drawdown_pct < 5 ? 'text-green-400' : stats.max_drawdown_pct < 10 ? 'text-yellow-400' : 'text-red-400' },
            ].map(s => (
              <div key={s.label} className="bg-gray-800/50 rounded-lg p-2.5 text-center">
                <p className="text-gray-500 text-xs">{s.label}</p>
                <p className={`font-bold ${s.color}`}>{s.val}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Exposure bar */}
      {totalExposed > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex justify-between text-xs text-gray-400">
            <span>Açık Sermaye</span>
            <span>${totalExposed.toFixed(0)} / $10.000 portföy (maks $500/pozisyon)</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div className="h-full bg-orange-500 rounded-full transition-all"
              style={{ width: `${Math.min(totalExposed / 500 * 100, 100)}%` }} />
          </div>
          <p className="text-xs text-gray-600">%{(totalExposed / 10000 * 100).toFixed(2)} portföy · Pozisyon başına maks %5</p>
        </div>
      )}

      {/* Open Positions */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">⚡ Açık Pozisyonlar</h2>
          <span className="text-xs text-gray-600">{positions.length} aktif</span>
        </div>

        {positions.length === 0 ? (
          <EmptyState maxPositions={maxPositions} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2.5">Sembol</th>
                  <th className="text-left px-4 py-2.5">Yön</th>
                  <th className="text-left px-4 py-2.5">Giriş</th>
                  <th className="text-left px-4 py-2.5">Anlık</th>
                  <th className="text-left px-4 py-2.5">Stop / TP</th>
                  <th className="text-left px-4 py-2.5">Boyut</th>
                  <th className="text-left px-4 py-2.5">Gerçekleşmemiş</th>
                  <th className="text-left px-4 py-2.5">Süre</th>
                  <th className="text-left px-4 py-2.5">Güven</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => (
                  <tr key={pos.symbol}
                    className={`border-b border-gray-800/40 hover:bg-gray-800/20 transition-colors cursor-pointer ${
                      pos.unrealized_pct > 0.5  ? 'bg-green-950/10' :
                      pos.unrealized_pct < -0.5 ? 'bg-red-950/10'   : ''
                    }`}
                    onClick={() => window.location.href = `/coin/${pos.symbol}`}>

                    {/* Symbol */}
                    <td className="px-4 py-3 font-bold text-white hover:text-orange-400 transition-colors">
                      {pos.symbol.replace('USDT', '')}
                      <span className="text-gray-600 text-[10px] font-normal">USDT</span>
                    </td>

                    {/* Direction */}
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-bold border ${DIR_STYLE[pos.direction] ?? ''}`}>
                        {pos.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
                      </span>
                    </td>

                    {/* Entry price */}
                    <td className="px-4 py-3 font-mono text-xs text-gray-300">{fmtPrice(pos.entry_price)}</td>

                    {/* Current price + live indicator */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <LiveDot live={pos.price_live} />
                        <span className={`font-mono text-xs font-bold ${
                          pos.current_price
                            ? pos.unrealized_pct >= 0 ? 'text-green-400' : 'text-red-400'
                            : 'text-gray-500'
                        }`}>
                          {fmtPrice(pos.current_price)}
                        </span>
                      </div>
                    </td>

                    {/* Stop / TP levels with visual bar */}
                    <td className="px-4 py-3 min-w-[140px]">
                      <div className="space-y-0.5">
                        <div className="flex gap-2 text-[10px]">
                          <span className="text-red-400">SL {fmtPrice(pos.sl_price)}</span>
                          <span className="text-gray-700">|</span>
                          <span className="text-green-400">TP {fmtPrice(pos.tp_price)}</span>
                        </div>
                        <TpSlBar
                          entry={pos.entry_price}
                          current={pos.current_price}
                          sl={pos.sl_price}
                          tp={pos.tp_price}
                          direction={pos.direction}
                        />
                      </div>
                    </td>

                    {/* Size */}
                    <td className="px-4 py-3 text-xs text-gray-300">${pos.size_usd.toFixed(0)}</td>

                    {/* Unrealized P&L */}
                    <td className="px-4 py-3">
                      <PnLBar pct={pos.unrealized_pct} />
                      <div className={`text-[10px] font-mono mt-0.5 ${pos.unrealized_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {pos.unrealized_usdt >= 0 ? '+' : ''}${pos.unrealized_usdt.toFixed(2)}
                      </div>
                    </td>

                    {/* Age */}
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {pos.age_hours < 1
                        ? `${Math.round(pos.age_hours * 60)}dk`
                        : `${pos.age_hours.toFixed(1)}sa`}
                    </td>

                    {/* Confidence */}
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {pos.entry_signal ? `%${Math.round(pos.entry_signal.confidence * 100)}` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Trade History */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">📋 Son Tradeler</h2>
          <span className="text-xs text-gray-600">Son {trade_history.length} kapalı trade</span>
        </div>

        {trade_history.length === 0 ? (
          <p className="text-gray-500 text-sm p-6 text-center">Henüz kapalı trade yok — pozisyonların kapanması bekleniyor</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800/60 text-xs bg-gray-900/60">
                  <th className="text-left px-4 py-2.5">Sembol</th>
                  <th className="text-left px-4 py-2.5">Yön</th>
                  <th className="text-left px-4 py-2.5">Giriş</th>
                  <th className="text-left px-4 py-2.5">Çıkış</th>
                  <th className="text-left px-4 py-2.5">Boyut</th>
                  <th className="text-left px-4 py-2.5">K/Z %</th>
                  <th className="text-left px-4 py-2.5">K/Z $</th>
                  <th className="text-left px-4 py-2.5">Kapandı</th>
                </tr>
              </thead>
              <tbody>
                {trade_history.map((trade, i) => (
                  <tr key={trade.trade_id ?? `${trade.symbol}-${trade.closed_at}-${i}`}
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
