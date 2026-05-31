'use client'
import { useEffect, useState } from 'react'

interface SymbolResult {
  symbol: string
  total_trades: number
  win_rate_pct: number
  avg_win_pct: number
  avg_loss_pct: number
  profit_factor: number
  total_return_pct: number
  sharpe_ratio: number
  max_drawdown_pct: number
  final_capital: number
  long_trades: number
  short_trades: number
  long_win_rate_pct: number
  short_win_rate_pct: number
  avg_bars_held: number
  exit_reasons: Record<string, number>
  monthly_returns: { month: string; return_pct: number; capital: number }[]
}

interface BacktestSummary {
  symbols_tested: number
  total_trades: number
  avg_win_rate_pct: number
  portfolio_sharpe: number
  avg_return_pct: number
  avg_max_drawdown_pct: number
  avg_profit_factor: number
  top5_symbols: string[]
  bottom5_symbols: string[]
  days_tested: number
  completed_at: number
  elapsed_seconds: number
  avg_monthly_returns: Record<string, number>
}

interface BacktestConfig {
  atr_sl_mult: number
  atr_tp_mult: number
  rr_ratio: number
  max_position_pct: number
  confidence_threshold_pct: number
  max_hold_bars: number
  fee_round_trip_pct: number
  interval: string
}

interface BacktestData {
  summary: BacktestSummary
  symbols: SymbolResult[]
  config: BacktestConfig
}

interface BacktestStatus {
  status: 'idle' | 'running' | 'complete' | 'error'
  progress?: number
  completed?: number
  total?: number
  last_symbol?: string
  started_at?: number
  completed_at?: number
  elapsed_seconds?: number
  msg?: string
}

type SortKey = 'win_rate_pct' | 'sharpe_ratio' | 'total_return_pct' | 'max_drawdown_pct' | 'total_trades' | 'profit_factor'

function StatCard({ label, value, sub, color, highlight }: { label: string; value: string; sub?: string; color: string; highlight?: boolean }) {
  return (
    <div className={`rounded-xl border p-4 ${highlight ? 'bg-orange-900/20 border-orange-700/50' : 'bg-gray-900 border-gray-800'}`}>
      <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-black font-mono ${color}`}>{value}</p>
      {sub && <p className="text-gray-600 text-xs mt-1">{sub}</p>}
    </div>
  )
}

function ProgressBar({ pct, color = 'bg-orange-500' }: { pct: number; color?: string }) {
  return (
    <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
      <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  )
}

function MonthlyHeatmap({ data }: { data: Record<string, number> }) {
  const months = Object.entries(data).sort(([a], [b]) => a.localeCompare(b))
  if (!months.length) return null
  const max = Math.max(...months.map(([, v]) => Math.abs(v)))

  return (
    <div className="flex flex-wrap gap-1.5">
      {months.map(([month, ret]) => {
        const intensity = max > 0 ? Math.abs(ret) / max : 0
        const isPos = ret >= 0
        const bg = isPos
          ? `rgba(34,197,94,${0.15 + intensity * 0.7})`
          : `rgba(239,68,68,${0.15 + intensity * 0.7})`
        const border = isPos ? 'border-green-700/50' : 'border-red-700/50'
        return (
          <div key={month} className={`rounded p-2 text-center border ${border} min-w-[52px]`} style={{ background: bg }}>
            <p className="text-[9px] text-gray-400">{month.slice(2)}</p>
            <p className={`text-xs font-bold font-mono ${isPos ? 'text-green-300' : 'text-red-300'}`}>
              {ret >= 0 ? '+' : ''}{ret.toFixed(1)}%
            </p>
          </div>
        )
      })}
    </div>
  )
}

export default function BacktestPage() {
  const [data, setData] = useState<{ results: BacktestData | null; status: BacktestStatus | null }>({ results: null, status: null })
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('sharpe_ratio')
  const [sortAsc, setSortAsc] = useState(false)
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = async () => {
    try {
      const d = await fetch('/api/backtest').then(r => r.json())
      setData(d)
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 10000)
    return () => clearInterval(t)
  }, [])

  const triggerBacktest = async () => {
    setTriggering(true)
    try {
      await fetch('/api/backtest', { method: 'POST' })
      setTimeout(fetchData, 2000)
    } finally { setTriggering(false) }
  }

  const status = data.status
  const results = data.results
  const summary = results?.summary
  const config = results?.config
  const isRunning = status?.status === 'running'
  const isComplete = status?.status === 'complete' || !!results

  const symbols = (results?.symbols ?? []).slice().sort((a, b) => {
    const av = a[sortKey] as number
    const bv = b[sortKey] as number
    return sortAsc ? av - bv : bv - av
  })

  const handleSort = (key: SortKey) => {
    if (key === sortKey) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  const SortTh = ({ k, label }: { k: SortKey; label: string }) => (
    <th className="text-left px-3 py-2.5 cursor-pointer hover:text-white select-none" onClick={() => handleSort(k)}>
      {label} {sortKey === k ? (sortAsc ? '↑' : '↓') : ''}
    </th>
  )

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">1 Yıllık Backtest — Binance USDM Futures</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            365 gün · 1h kline · ATR stop/TP · %60 güven eşiği · %0.10 komisyon
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate} · 10s` : ''}</span>
          <button
            onClick={triggerBacktest}
            disabled={triggering || isRunning}
            className={`px-4 py-2 rounded text-xs font-bold transition-colors border ${
              isRunning ? 'border-orange-700/50 text-orange-400 bg-orange-900/20 cursor-wait'
                : 'border-blue-700/50 text-blue-400 bg-blue-900/20 hover:bg-blue-900/40'
            }`}
          >
            {triggering ? 'Başlatılıyor...' : isRunning ? '⟳ Çalışıyor...' : '▶ Yeni Backtest'}
          </button>
        </div>
      </div>

      {/* Running progress */}
      {isRunning && status && (
        <div className="bg-orange-900/20 border border-orange-700/40 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-orange-400 animate-spin text-base">⟳</span>
              <p className="text-orange-300 font-semibold text-sm">Backtest çalışıyor...</p>
            </div>
            <span className="text-orange-400 font-mono text-sm font-bold">
              {status.completed ?? 0} / {status.total ?? '?'}
            </span>
          </div>
          <ProgressBar pct={(status.progress ?? 0) * 100} color="bg-orange-500" />
          {status.last_symbol && (
            <p className="text-gray-500 text-xs mt-2">Son: <span className="text-white">{status.last_symbol}</span> — Binance API&apos;den veriler çekiliyor, hesaplanıyor...</p>
          )}
        </div>
      )}

      {/* No results yet */}
      {!loading && !isRunning && !results && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
          <p className="text-gray-400 text-sm font-semibold">Backtest henüz çalışmadı</p>
          <p className="text-gray-600 text-xs mt-2 max-w-sm mx-auto">
            &quot;Yeni Backtest&quot; butonuna tıkla — sistem 25 coin için 1 yıllık Binance Futures verisini çekip simülasyon yapacak.
            Tahminen 5-10 dakika sürer.
          </p>
          <button onClick={triggerBacktest} disabled={triggering}
            className="mt-4 px-6 py-2.5 rounded text-sm font-bold text-white bg-orange-600 hover:bg-orange-500 transition-colors">
            {triggering ? 'Başlatılıyor...' : '▶ Backtest Başlat'}
          </button>
        </div>
      )}

      {/* Results */}
      {summary && config && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              label="Ort. Kazanma Oranı"
              value={`${summary.avg_win_rate_pct.toFixed(1)}%`}
              sub="Tüm coinlerin ortalaması"
              color={summary.avg_win_rate_pct >= 60 ? 'text-green-400' : summary.avg_win_rate_pct >= 52 ? 'text-orange-400' : 'text-red-400'}
              highlight
            />
            <StatCard
              label="Portfolio Sharpe"
              value={summary.portfolio_sharpe.toFixed(2)}
              sub="Ağırlıklı ortalama"
              color={summary.portfolio_sharpe >= 2.0 ? 'text-green-400' : summary.portfolio_sharpe >= 1.0 ? 'text-orange-400' : 'text-red-400'}
            />
            <StatCard
              label="Ort. Getiri"
              value={`${summary.avg_return_pct >= 0 ? '+' : ''}${summary.avg_return_pct.toFixed(1)}%`}
              sub={`${summary.days_tested} günde (1 yıl)`}
              color={summary.avg_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}
            />
            <StatCard
              label="Ort. Max Drawdown"
              value={`${summary.avg_max_drawdown_pct.toFixed(1)}%`}
              sub="Portföy risk seviyesi"
              color={summary.avg_max_drawdown_pct < 10 ? 'text-green-400' : summary.avg_max_drawdown_pct < 20 ? 'text-yellow-400' : 'text-red-400'}
            />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Test Edilen" value={String(summary.symbols_tested)} sub="coin / sembol" color="text-blue-400" />
            <StatCard label="Toplam İşlem" value={String(summary.total_trades)} sub="simüle edilen" color="text-purple-400" />
            <StatCard label="Profit Factor" value={summary.avg_profit_factor.toFixed(2)} sub="kazanç/kayıp oranı" color={summary.avg_profit_factor >= 1.5 ? 'text-green-400' : 'text-orange-400'} />
            <StatCard label="Test Süresi" value={`${Math.round(summary.elapsed_seconds / 60)}dk`} sub="fetch + simülasyon" color="text-gray-400" />
          </div>

          {/* Config + monthly heatmap */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <h2 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">Backtest Parametreleri</h2>
              <div className="space-y-2 text-xs">
                {[
                  { label: 'Stop Loss', value: `${config.atr_sl_mult}× ATR` },
                  { label: 'Take Profit', value: `${config.atr_tp_mult}× ATR` },
                  { label: 'Risk/Ödül', value: `1 : ${config.rr_ratio}` },
                  { label: 'Maks Pozisyon', value: `%${config.max_position_pct}` },
                  { label: 'Güven Eşiği', value: `%${config.confidence_threshold_pct}` },
                  { label: 'Maks Tutma', value: `${config.max_hold_bars} bar (${config.max_hold_bars}sa)` },
                  { label: 'Komisyon', value: `%${config.fee_round_trip_pct} (r/t)` },
                  { label: 'Zaman Dilimi', value: config.interval },
                ].map(item => (
                  <div key={item.label} className="flex justify-between">
                    <span className="text-gray-500">{item.label}</span>
                    <span className="text-white font-mono">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-xl p-4">
              <h2 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">
                Aylık Portföy Getirisi — {Object.keys(summary.avg_monthly_returns).length} Ay
              </h2>
              <MonthlyHeatmap data={summary.avg_monthly_returns} />
              <p className="text-gray-700 text-[10px] mt-2">Her kutucuk = tüm coinlerin o ay ortalama getirisi</p>
            </div>
          </div>

          {/* Top / Bottom */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-gray-900 border border-green-900/40 rounded-xl p-4">
              <h2 className="text-green-400 font-semibold text-xs uppercase tracking-wider mb-3">En İyi 5 Sembol (Sharpe)</h2>
              <div className="space-y-1">
                {summary.top5_symbols.map((sym, i) => {
                  const r = symbols.find(s => s.symbol === sym)
                  return (
                    <div key={sym} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className={`font-bold w-4 ${i === 0 ? 'text-yellow-400' : 'text-gray-500'}`}>{i === 0 ? '★' : `${i + 1}`}</span>
                        <span className="text-white font-semibold">{sym}</span>
                      </div>
                      {r && (
                        <div className="flex gap-3 text-right">
                          <span className="text-green-400 font-mono">WR {r.win_rate_pct.toFixed(1)}%</span>
                          <span className="text-blue-400 font-mono">SR {r.sharpe_ratio.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
            <div className="bg-gray-900 border border-red-900/40 rounded-xl p-4">
              <h2 className="text-red-400 font-semibold text-xs uppercase tracking-wider mb-3">En Düşük 5 Sembol (Sharpe)</h2>
              <div className="space-y-1">
                {summary.bottom5_symbols.map((sym, i) => {
                  const r = symbols.find(s => s.symbol === sym)
                  return (
                    <div key={sym} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="text-gray-600 w-4">{i + 1}</span>
                        <span className="text-gray-300 font-semibold">{sym}</span>
                      </div>
                      {r && (
                        <div className="flex gap-3 text-right">
                          <span className={`font-mono ${r.win_rate_pct >= 52 ? 'text-green-400' : 'text-red-400'}`}>WR {r.win_rate_pct.toFixed(1)}%</span>
                          <span className={`font-mono ${r.sharpe_ratio >= 1 ? 'text-blue-400' : 'text-red-400'}`}>SR {r.sharpe_ratio.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Symbol results table */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-white font-semibold text-sm">Sembol Detayları — {symbols.length} coin</h2>
              <span className="text-gray-600 text-xs">Sıralamak için başlığa tıkla</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs min-w-[900px]">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-800 bg-gray-900/80">
                    <th className="text-left px-3 py-2.5">Sembol</th>
                    <SortTh k="win_rate_pct" label="Kazanma %" />
                    <SortTh k="sharpe_ratio" label="Sharpe" />
                    <SortTh k="total_return_pct" label="Getiri %" />
                    <SortTh k="max_drawdown_pct" label="Max DD %" />
                    <SortTh k="profit_factor" label="PF" />
                    <SortTh k="total_trades" label="İşlem" />
                    <th className="text-left px-3 py-2.5">L/S WR</th>
                    <th className="text-left px-3 py-2.5">Çıkış Sebepleri</th>
                    <th className="text-left px-3 py-2.5">Aylık</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.map((r, idx) => {
                    const isExp = expandedSymbol === r.symbol
                    const tpPct = r.exit_reasons.take_profit ?? 0
                    const slPct = r.exit_reasons.stop_loss ?? 0
                    const timePct = r.exit_reasons.time_exit ?? 0
                    const total = tpPct + slPct + timePct || 1
                    return (
                      <>
                        <tr
                          key={r.symbol}
                          className={`border-b border-gray-800/40 hover:bg-gray-800/25 cursor-pointer transition-colors ${idx === 0 ? 'bg-green-950/15' : ''}`}
                          onClick={() => setExpandedSymbol(isExp ? null : r.symbol)}
                        >
                          <td className="px-3 py-2.5">
                            <span className="font-bold text-white">{r.symbol}</span>
                            {idx === 0 && <span className="ml-1 text-yellow-400 text-[10px]">★</span>}
                          </td>
                          <td className={`px-3 py-2.5 font-mono font-bold ${r.win_rate_pct >= 60 ? 'text-green-400' : r.win_rate_pct >= 52 ? 'text-orange-400' : 'text-red-400'}`}>
                            {r.win_rate_pct.toFixed(1)}%
                          </td>
                          <td className={`px-3 py-2.5 font-mono font-bold ${r.sharpe_ratio >= 2 ? 'text-green-400' : r.sharpe_ratio >= 1 ? 'text-blue-400' : 'text-gray-400'}`}>
                            {r.sharpe_ratio.toFixed(2)}
                          </td>
                          <td className={`px-3 py-2.5 font-mono font-bold ${r.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {r.total_return_pct >= 0 ? '+' : ''}{r.total_return_pct.toFixed(1)}%
                          </td>
                          <td className={`px-3 py-2.5 font-mono ${r.max_drawdown_pct < 10 ? 'text-green-400' : r.max_drawdown_pct < 20 ? 'text-yellow-400' : 'text-red-400'}`}>
                            {r.max_drawdown_pct.toFixed(1)}%
                          </td>
                          <td className={`px-3 py-2.5 font-mono ${r.profit_factor >= 1.5 ? 'text-green-400' : r.profit_factor >= 1 ? 'text-yellow-400' : 'text-red-400'}`}>
                            {r.profit_factor.toFixed(2)}
                          </td>
                          <td className="px-3 py-2.5 text-gray-300">{r.total_trades}</td>
                          <td className="px-3 py-2.5">
                            <span className="text-green-400">{r.long_win_rate_pct.toFixed(0)}%</span>
                            <span className="text-gray-600 mx-1">/</span>
                            <span className="text-red-400">{r.short_win_rate_pct.toFixed(0)}%</span>
                          </td>
                          <td className="px-3 py-2.5">
                            <div className="flex gap-1">
                              {tpPct > 0 && <span className="text-green-400 text-[10px]">TP:{Math.round(tpPct / total * 100)}%</span>}
                              {slPct > 0 && <span className="text-red-400 text-[10px]">SL:{Math.round(slPct / total * 100)}%</span>}
                              {timePct > 0 && <span className="text-gray-500 text-[10px]">T:{Math.round(timePct / total * 100)}%</span>}
                            </div>
                          </td>
                          <td className="px-3 py-2.5 text-gray-600 text-[10px]">{isExp ? '▲ kapat' : '▼ detay'}</td>
                        </tr>
                        {isExp && (
                          <tr key={`${r.symbol}-exp`} className="bg-gray-900/60">
                            <td colSpan={10} className="px-4 py-4 border-b border-gray-800/40">
                              <div className="space-y-3">
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                                  <div className="bg-gray-800/50 rounded p-2">
                                    <p className="text-gray-500 mb-0.5">Long İşlemler</p>
                                    <p className="text-green-400 font-mono font-bold">{r.long_trades} ({r.long_win_rate_pct.toFixed(1)}% WR)</p>
                                  </div>
                                  <div className="bg-gray-800/50 rounded p-2">
                                    <p className="text-gray-500 mb-0.5">Short İşlemler</p>
                                    <p className="text-red-400 font-mono font-bold">{r.short_trades} ({r.short_win_rate_pct.toFixed(1)}% WR)</p>
                                  </div>
                                  <div className="bg-gray-800/50 rounded p-2">
                                    <p className="text-gray-500 mb-0.5">Ort. Kazanç / Kayıp</p>
                                    <p className="text-white font-mono">{r.avg_win_pct.toFixed(2)}% / {r.avg_loss_pct.toFixed(2)}%</p>
                                  </div>
                                  <div className="bg-gray-800/50 rounded p-2">
                                    <p className="text-gray-500 mb-0.5">Ort. Tutma Süresi</p>
                                    <p className="text-white font-mono">{r.avg_bars_held.toFixed(1)} bar ({r.avg_bars_held.toFixed(0)}sa)</p>
                                  </div>
                                </div>
                                {r.monthly_returns.length > 0 && (
                                  <div>
                                    <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-2">{r.symbol} Aylık Getiriler</p>
                                    <div className="flex flex-wrap gap-1">
                                      {r.monthly_returns.map(m => (
                                        <div key={m.month} className={`rounded px-1.5 py-1 text-center text-[10px] border ${m.return_pct >= 0 ? 'border-green-800/50 bg-green-900/20' : 'border-red-800/50 bg-red-900/20'}`}>
                                          <p className="text-gray-500">{m.month.slice(2)}</p>
                                          <p className={`font-mono font-bold ${m.return_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {m.return_pct >= 0 ? '+' : ''}{m.return_pct.toFixed(1)}%
                                          </p>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="bg-gray-900/60 border border-gray-800/60 rounded-lg p-4 text-xs text-gray-500 space-y-1">
            <p className="text-gray-400 font-semibold text-xs mb-2">Backtest Uyarıları</p>
            <p>• Geçmiş performans gelecekteki sonuçları garanti etmez. Backtest gerçek slippage ve likidite kısıtlarını tam yansıtmaz.</p>
            <p>• Stop/TP fiyatlar bar içinde kontrol edilir (bar-level resolution) — gerçekte anlık çalışır, dolayısıyla gerçek WR biraz daha düşük olabilir.</p>
            <p>• Komisyon: %0.05 × 2 = %0.10 round-trip dahil. Funding rate ve borrowing cost dahil değil.</p>
            <p>• Sistem canlıya geçmeden önce shadow sistem %52 WR + Sharpe ≥1.5 + DD &lt;%10 kriterlerini 100 gerçek işlemde geçmek zorundadır.</p>
          </div>
        </>
      )}
    </div>
  )
}
