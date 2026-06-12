'use client'

import { useEffect, useState } from 'react'

interface TradeRow {
  action?: string
  direction?: string
  entry_price?: number
  exit_price?: number
  pnl_pct?: number
  pnl_usdt?: number
  size_usd?: number
  timestamp?: number
  closed_at?: number
  ladder?: {
    tier?: number
    take_profit_pct?: number
    stop_loss_pct?: number
    entry_confidence?: number
    entry_reason?: string
  }
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
                <th className="text-right py-1 pr-2">PnL</th>
                <th className="text-left py-1">Dayanak</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 30).map((t, i) => {
                const pnl = Number(t.pnl_pct ?? 0) * 100
                const reason =
                  t.ladder?.entry_reason ||
                  t.entry_signal?.consensus_reasoning ||
                  t.entry_signal?.source ||
                  '—'
                return (
                  <tr key={i} className="border-t border-gray-800/50">
                    <td className={`py-1.5 pr-2 font-bold ${t.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                      {String(t.direction ?? '').toUpperCase()}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-gray-300">{fmtPrice(Number(t.entry_price ?? 0))}</td>
                    <td className="py-1.5 pr-2 font-mono text-gray-300">{fmtPrice(Number(t.exit_price ?? 0))}</td>
                    <td className={`py-1.5 pr-2 text-right font-mono ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                    </td>
                    <td className="py-1.5 text-gray-500 line-clamp-2 max-w-[200px]">{reason}</td>
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
