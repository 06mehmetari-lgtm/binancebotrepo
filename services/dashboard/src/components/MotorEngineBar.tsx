'use client'

const STAGE_STYLE: Record<string, string> = {
  L0: 'bg-gray-700 text-gray-300',
  L1: 'bg-blue-900/50 text-blue-300 border-blue-700/50',
  L2: 'bg-violet-900/50 text-violet-300 border-violet-700/50',
  L3: 'bg-emerald-900/50 text-emerald-300 border-emerald-600/50',
}

type Props = {
  openCount: number
  maxOpen: number
  streamLive: boolean
  pollingActive?: boolean
  tradingHalted?: boolean
}

export function MotorEngineBar({ openCount, maxOpen, streamLive, pollingActive, tradingHalted }: Props) {
  const pct = maxOpen > 0 ? Math.round((openCount / maxOpen) * 100) : 0
  const motorOn = !tradingHalted && (streamLive || pollingActive !== false)

  return (
    <div className={`rounded-xl border p-4 ${
      motorOn
        ? 'bg-gradient-to-r from-orange-950/40 via-gray-900 to-cyan-950/30 border-orange-800/40'
        : 'bg-gray-900 border-gray-800'
    }`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={`text-2xl ${motorOn ? 'animate-pulse' : 'opacity-40'}`}>⚙️</span>
          <div>
            <p className="text-white font-bold text-sm">
              Trading Motoru {motorOn ? '— TAM GÜÇ' : tradingHalted ? '— DURAKLATILDI' : '— BEKLEMEDE'}
            </p>
            <p className="text-gray-500 text-xs mt-0.5">
              Shadow 3sn tarama · kapanışta ders · sonraki alımda öğrenme uygulanır
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="text-center">
            <p className="text-gray-500">Slot</p>
            <p className="text-white font-bold font-mono">{openCount}/{maxOpen}</p>
          </div>
          <div className="text-center">
            <p className="text-gray-500">Döngü</p>
            <p className={streamLive ? 'text-green-400 font-bold' : 'text-gray-600'}>
              {streamLive ? '2sn canlı' : '2sn'}
            </p>
          </div>
        </div>
      </div>
      <div className="mt-3 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${
            pct >= 90 ? 'bg-red-500' : pct >= 60 ? 'bg-orange-500' : 'bg-green-500'
          }`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <p className="text-[10px] text-gray-600 mt-2">
        Kâr → 5dk cooldown · Zarar → 30dk + learn veto · L2+ profil kötü yönü bloklar
      </p>
    </div>
  )
}

export function LearnStageBadge({ stage, winRate, trades }: {
  stage?: string
  winRate?: number
  trades?: number
}) {
  const s = stage ?? 'L0'
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-bold ${STAGE_STYLE[s] ?? STAGE_STYLE.L0}`}>
      {s}
      {trades != null && trades > 0 && winRate != null && (
        <span className="opacity-70 font-mono">
          {Math.round(winRate <= 1 ? winRate * 100 : winRate)}%
        </span>
      )}
    </span>
  )
}

export function LessonSnippet({ lesson, avoid, entryHint }: {
  lesson?: string
  avoid?: string
  entryHint?: string
}) {
  const text = lesson || avoid || entryHint
  if (!text) return <span className="text-gray-600 text-[10px]">Henüz ders yok</span>
  const isAvoid = !lesson && avoid
  return (
    <div className="max-w-[200px]">
      <p className={`text-[10px] leading-snug line-clamp-2 ${isAvoid ? 'text-red-400/90' : 'text-cyan-400/90'}`} title={text}>
        {isAvoid ? '⚠ ' : '📘 '}{text}
      </p>
    </div>
  )
}
