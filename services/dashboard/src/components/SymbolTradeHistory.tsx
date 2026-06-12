'use client'

import { useEffect, useState } from 'react'

interface TradeRow {
  action?: string
  direction?: string
  entry_price?: number
  exit_price?: number
  pnl_pct?: number
  pnl_usdt?: number
  gross_pnl_usd?: number
  fee_entry_usd?: number
  fee_exit_usd?: number
  fee_total_usd?: number
  fee_total_pct?: number
  net_pnl_usd?: number
  size_usd?: number
  dca_tier?: number
  exit_reason?: string
  entry_reason?: string
  timestamp?: number
  closed_at?: number
  ladder?: {
    tier?: number
    take_profit_pct?: number
    stop_loss_pct?: number
    entry_confidence?: number
    entry_reason?: string
    last_dca_reason?: string
  }
  fills?: { tier?: number; reason?: string; size_usd?: number }[]
  entry_signal?: { consensus_reasoning?: string; source?: string }
}

function fmtPrice(p: number) {
  if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (p >= 1) return p.toFixed(4)
  return p.toFixed(6)
}

export function SymbolTradeHistory({ symbol }: { symbol: string }) {
  const [trades, setTrades] = useState<TradeRow[]>([])
  const [position, setPosition] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetch(`/api/coin/${symbol}/trades`)
        const data = await res.json()
        if (!cancelled && res.ok) {
          setTrades(Array.isArray(data.trades) ? data.trades : [])
          setPosition(data.position ?? null)
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const t = setInterval(load, 15_000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [symbol])

  if (loading) {
    return <p className="text-gray-500 text-xs py-2">İşlem geçmişi yükleniyor…</p>
  }

  const pos = position as TradeRow | null
  const ladder = pos?.ladder

  return (
    <div className="space-y-3">
      {ladder && (
        <div className="bg-gray-900/60 border border-cyan-800/40 rounded-lg p-3">
          <p className="text-cyan-400 text-[10px] uppercase tracking-wider font-bold mb-2">
            Açık pozisyon — kademe {ladder.tier ?? 1}
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
            <div>
              <p className="text-gray-500">Giriş fiyatı</p>
              <p className="text-white font-mono">{fmtPrice(Number(pos?.entry_price ?? 0))}</p>
            </div>
            <div>
              <p className="text-gray-500">Kâr hedefi</p>
              <p className="text-green-400 font-mono">%{ladder.take_profit_pct ?? '—'}</p>
            </div>
            <div>
              <p className="text-gray-500">Stop</p>
              <p className="text-red-400 font-mono">%{ladder.stop_loss_pct ?? '—'}</p>
            </div>
            <div>
              <p className="text-gray-500">Giriş güveni</p>
              <p className="text-white font-mono">
                {ladder.entry_confidence != null
                  ? `${Math.round(ladder.entry_confidence * 100)}%`
                  : '—'}
              </p>
            </div>
          </div>
          {ladder.entry_reason && (
            <p className="text-gray-400 mt-2 leading-relaxed">{ladder.entry_reason}</p>
          )}
        </div>
      )}

      {trades.length === 0 ? (
        <p className="text-gray-500 text-xs">Bu coin için henüz kapanmış işlem yok.</p>
      ) : (
        <div className="overflow-x-auto max-h-56 overflow-y-auto">
          <table className="w-full text-[11px]">
            <thead className="text-gray-500 sticky top-0 bg-gray-950">
              <tr>
                <th className="text-left py-1 pr-2">Yön</th>
                <th className="text-left py-1 pr-2">Giriş</th>
                <th className="text-left py-1 pr-2">Çıkış</th>
                <th className="text-right py-1 pr-2">Net PnL</th>
                <th className="text-right py-1 pr-2">Komisyon</th>
                <th className="text-left py-1">Giriş / Çıkış</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 30).map((t, i) => {
                const pnl = Number(t.pnl_pct ?? 0) * 100
                const entryWhy =
                  t.entry_reason ||
                  t.ladder?.entry_reason ||
                  t.entry_signal?.consensus_reasoning ||
                  ''
                const exitWhy = t.exit_reason || '—'
                const fee = Number(t.fee_total_usd ?? 0)
                const tier = t.dca_tier ?? t.ladder?.tier
                return (
                  <tr key={i} className="border-t border-gray-800/50">
                    <td className={`py-1.5 pr-2 font-bold ${t.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                      {String(t.direction ?? '').toUpperCase()}
                      {tier != null && tier > 1 ? (
                        <span className="text-violet-400 text-[9px] ml-1">DCA{tier}</span>
                      ) : null}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-gray-300">{fmtPrice(Number(t.entry_price ?? 0))}</td>
                    <td className="py-1.5 pr-2 font-mono text-gray-300">{fmtPrice(Number(t.exit_price ?? 0))}</td>
                    <td className={`py-1.5 pr-2 text-right font-mono ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-gray-500">
                      {fee > 0 ? `$${fee.toFixed(2)}` : '—'}
                    </td>
                    <td className="py-1.5 text-gray-500 max-w-[240px]">
                      {entryWhy && (
                        <p className="line-clamp-1 text-cyan-600/80" title={entryWhy}>
                          Al: {entryWhy}
                        </p>
                      )}
                      <p className="line-clamp-1" title={exitWhy}>
                        Sat: {exitWhy}
                      </p>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
