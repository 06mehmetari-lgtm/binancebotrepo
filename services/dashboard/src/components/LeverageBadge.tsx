'use client'

type Props = {
  entryLeverage: number
  reasons?: string[]
  notionalUsd?: number
  marginUsd?: number
}

export function LeverageBadge({ entryLeverage, reasons, notionalUsd, marginUsd }: Props) {
  const lev = Math.max(1, Math.round(entryLeverage))
  const title = [
    `Alım kaldıracı: ${lev}x`,
    reasons?.length ? `Neden: ${reasons.join(', ')}` : null,
    notionalUsd != null && marginUsd != null
      ? `Notional $${notionalUsd.toFixed(0)} = margin $${marginUsd.toFixed(0)} × ${lev}`
      : null,
  ].filter(Boolean).join('\n')

  return (
    <div title={title} className="leading-tight">
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-violet-950/60 border border-violet-700/50">
        <span className="text-[10px] text-violet-300/80 uppercase">Alım</span>
        <span className="text-violet-300 font-black font-mono text-sm">{lev}x</span>
      </span>
      {reasons?.[0] && (
        <span className="block text-[9px] text-gray-600 mt-0.5 truncate max-w-[90px]">
          {reasons[0]}
        </span>
      )}
    </div>
  )
}
