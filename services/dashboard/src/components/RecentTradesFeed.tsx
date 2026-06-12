'use client'

type Trade = {
  symbol: string
  direction: string
  pnl_pct: number
  pnl_usdt: number
  closed_at: number
  hold_seconds?: number
  exit_reason?: string
  entry_reason?: string
  peak_upnl_pct?: number
  entry_price?: number
  exit_price?: number
  fee_total_usd?: number
  gross_pnl_usd?: number
  dca_tier?: number
}

function timeAgo(ts: number) {
  const s = Math.floor(Date.now() / 1000 - ts)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}dk`
  return `${Math.floor(s / 3600)}sa`
}

function fmtPct(ratio: number) {
  const pct = Math.abs(ratio) < 2 ? ratio * 100 : ratio
  return pct.toFixed(2)
}

function exitLabel(reason?: string) {
  if (!reason) return null
  if (reason.includes('Kâr kademesi') || reason.includes('Kâr hedefi')) return { text: 'Kâr alındı', cls: 'text-green-400' }
  if (reason.includes('Trailing') || reason.includes('Kâr koruma')) return { text: 'Trailing / koruma', cls: 'text-cyan-400' }
  if (reason.includes('Sat sinyali') || reason.includes('Kârda sat')) return { text: 'Sat sinyali', cls: 'text-orange-400' }
  if (reason.includes('AI FLAT') || reason.includes('FLAT')) return { text: 'AI çıkış', cls: 'text-yellow-500' }
  if (reason.includes('zarar')) return { text: 'Zarar kes', cls: 'text-red-400' }
  return { text: reason.slice(0, 40), cls: 'text-gray-500' }
}

export function RecentTradesFeed({ trades, max = 8 }: { trades: Trade[]; max?: number }) {
  const rows = trades.slice(0, max)
  if (!rows.length) {
    return <p className="text-gray-600 text-xs py-4 text-center">Henüz kapanan işlem yok</p>
  }
  return (
    <div className="divide-y divide-gray-800/60">
      {rows.map((t, i) => {
        const pnlPct = fmtPct(t.pnl_pct ?? 0)
        const label = exitLabel(t.exit_reason)
        return (
          <div key={`${t.symbol}-${t.closed_at}-${i}`} className="px-3 py-2.5 text-xs hover:bg-gray-800/30 space-y-1">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className={`font-bold uppercase ${t.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                  {t.direction === 'long' ? '▲' : '▼'}
                </span>
                <a href={`/coin/${t.symbol}`} className="text-white font-mono font-bold hover:text-orange-400 truncate">
                  {t.symbol.replace('USDT', '')}
                </a>
                <span className="text-gray-600">{timeAgo(t.closed_at)}</span>
                {t.hold_seconds != null && t.hold_seconds > 0 && (
                  <span className="text-gray-600">· {Math.round(t.hold_seconds)}sn</span>
                )}
              </div>
              <div className="text-right shrink-0">
                <span className={`font-mono font-bold ${t.pnl_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {t.pnl_usdt >= 0 ? '+' : ''}${t.pnl_usdt.toFixed(2)}
                </span>
                <span className={`ml-2 font-mono ${Number(pnlPct) >= 0 ? 'text-green-500/70' : 'text-red-500/70'}`}>
                  {Number(pnlPct) >= 0 ? '+' : ''}{pnlPct}%
                </span>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pl-6 text-[10px]">
              {label && <span className={label.cls}>{label.text}</span>}
              {t.fee_total_usd != null && t.fee_total_usd > 0 && (
                <span className="text-gray-500">komisyon ${t.fee_total_usd.toFixed(2)}</span>
              )}
              {t.dca_tier != null && t.dca_tier > 1 && (
                <span className="text-purple-400">DCA kademe {t.dca_tier}</span>
              )}
              {t.peak_upnl_pct != null && Number(t.peak_upnl_pct) > 0 && (
                <span className="text-gray-500">zirve +{Number(t.peak_upnl_pct).toFixed(2)}%</span>
              )}
              {t.entry_reason && (
                <span className="text-gray-600 line-clamp-1" title={t.entry_reason}>
                  giriş: {t.entry_reason.slice(0, 48)}…
                </span>
              )}
              {t.exit_reason && !label && (
                <span className="text-gray-500 line-clamp-1">{t.exit_reason}</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
