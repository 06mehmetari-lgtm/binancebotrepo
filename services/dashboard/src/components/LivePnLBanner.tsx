'use client'

type LivePnLBannerProps = {
  totalUsdt: number
  dailyPnl: number
  positionCount: number
  liveAt?: number
  isLive?: boolean
}

export function LivePnLBanner({
  totalUsdt,
  dailyPnl,
  positionCount,
  liveAt,
  isLive,
}: LivePnLBannerProps) {
  const up = totalUsdt >= 0
  const liveLabel =
    liveAt && liveAt > 0
      ? new Date(liveAt).toLocaleTimeString('tr-TR', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      : '—'

  return (
    <div
      className={`rounded-2xl border-2 px-5 py-4 shadow-lg ${
        up
          ? 'border-green-500/50 bg-gradient-to-r from-green-950/50 to-gray-900'
          : 'border-red-500/50 bg-gradient-to-r from-red-950/50 to-gray-900'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.2em] text-gray-400 mb-1 flex items-center gap-2">
            <span
              className={`inline-block w-2.5 h-2.5 rounded-full ${
                isLive ? 'bg-green-400 animate-pulse shadow shadow-green-400/50' : 'bg-gray-600'
              }`}
            />
            Anlık kar / zarar — açık pozisyonlar
          </p>
          <p
            className={`text-4xl sm:text-5xl font-black font-mono tabular-nums leading-none ${
              up ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {up ? '+' : '−'}${Math.abs(totalUsdt).toFixed(2)}
          </p>
          <p className="text-xs text-gray-500 mt-2">
            {positionCount} açık pozisyon · güncelleme{' '}
            <span className="text-green-400/90 font-mono">{isLive ? '1sn' : '2sn'}</span>
            {isLive ? ` · ${liveLabel}` : ''}
          </p>
        </div>
        <div className="flex gap-3 flex-wrap">
          <div className="bg-gray-900/80 border border-gray-700 rounded-xl px-4 py-3 min-w-[120px] text-center">
            <p className="text-[10px] text-gray-500 uppercase">Bugün kapanan</p>
            <p
              className={`text-xl font-black font-mono ${
                dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {dailyPnl >= 0 ? '+' : '−'}${Math.abs(dailyPnl).toFixed(2)}
            </p>
          </div>
          <div className="bg-gray-900/80 border border-gray-700 rounded-xl px-4 py-3 min-w-[120px] text-center">
            <p className="text-[10px] text-gray-500 uppercase">Durum</p>
            <p className={`text-xl font-black ${up ? 'text-green-400' : 'text-red-400'}`}>
              {up ? 'KARDA' : 'ZARARDA'}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
