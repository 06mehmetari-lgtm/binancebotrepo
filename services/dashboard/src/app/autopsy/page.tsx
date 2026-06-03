'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'

type TradeRow = {
  symbol: string
  direction?: string
  entry_price?: number
  exit_price?: number
  pnl_pct?: number
  pnl_usdt?: number
  closed_at?: number
  error_category?: string | null
  autopsy_summary?: string | null
  lessons?: unknown[]
}

export default function AutopsyPage() {
  const [trades, setTrades] = useState<TradeRow[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    fetch('/api/autopsy?limit=50')
      .then(r => r.json())
      .then(d => setTrades(d.trades ?? []))
      .catch(() => setTrades([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  if (loading) {
    return <p className="text-gray-500 text-center mt-20">Otopsi verisi yükleniyor…</p>
  }

  return (
    <div className="space-y-5 max-w-5xl">
      <header>
        <h1 className="text-2xl font-black text-white">🔬 Trade Otopsi</h1>
        <p className="text-gray-500 text-sm mt-1">
          Kapanan işlemler · autopsy servisi · <code className="text-orange-400">oms:trade_history</code> + dersler
        </p>
      </header>

      {trades.length === 0 ? (
        <p className="text-gray-500 text-sm">Henüz kapanan işlem kaydı yok.</p>
      ) : (
        <div className="space-y-2">
          {trades.map((t, i) => {
            const key = `${t.symbol}-${t.closed_at ?? i}`
            const open = expanded === key
            const pnl = (t.pnl_pct ?? 0) * (Math.abs(t.pnl_pct ?? 0) < 2 ? 100 : 1)
            return (
              <div key={key} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                <button
                  type="button"
                  className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-800/50"
                  onClick={() => setExpanded(open ? null : key)}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-white font-bold">{t.symbol}</span>
                    <span className="text-xs text-gray-500">{t.direction ?? '—'}</span>
                    {t.error_category && (
                      <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-yellow-400">
                        {t.error_category}
                      </span>
                    )}
                  </div>
                  <span className={`font-mono text-sm ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                  </span>
                </button>
                {open && (
                  <div className="px-4 pb-4 border-t border-gray-800 text-xs space-y-2">
                    <p className="text-gray-400">
                      Giriş {t.entry_price ?? '—'} → Çıkış {t.exit_price ?? '—'}
                      {t.closed_at
                        ? ` · ${new Date(t.closed_at * 1000).toLocaleString('tr-TR')}`
                        : ''}
                    </p>
                    {t.autopsy_summary && (
                      <p className="text-gray-300 leading-relaxed">{t.autopsy_summary}</p>
                    )}
                    {Array.isArray(t.lessons) && t.lessons.length > 0 && (
                      <ul className="list-disc list-inside text-gray-500 space-y-1">
                        {t.lessons.map((l, j) => (
                          <li key={j}>
                            {typeof l === 'string' ? l : JSON.stringify(l)}
                          </li>
                        ))}
                      </ul>
                    )}
                    <Link
                      href={`/agents?symbol=${t.symbol}`}
                      className="inline-block text-orange-400 hover:text-orange-300 mt-2"
                    >
                      9 ajan oyları →
                    </Link>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
