'use client'

import { useEffect, useMemo, useState } from 'react'
import type { PositionDecision } from '@/lib/positions'
import { computeExitEstimate, formatCountdown } from '@/lib/exit-estimate'

const URGENCY_STYLE: Record<string, string> = {
  now: 'text-red-400 font-black animate-pulse',
  imminent: 'text-orange-400 font-bold',
  normal: 'text-cyan-400 font-mono',
}

export function ExitCountdownCell({ pos }: { pos: PositionDecision }) {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const est = useMemo(() => {
    void tick
    const liveSec = pos.entry_time
      ? Math.floor(Date.now() / 1000 - pos.entry_time)
      : 0
    const base = pos.exit_estimate
    if (!base || !pos.entry_time) {
      return computeExitEstimate({
        entry_time: pos.entry_time,
        direction: pos.direction,
        unrealized_pct: pos.unrealized_pct ?? 0,
        ladder: {
          ...pos.ladder,
          breakeven_armed: pos.ladder?.breakeven_armed ?? pos.breakeven_armed,
          peak_upnl_pct: pos.peak_upnl_pct,
        },
        guard: pos.guard,
        current_signal_direction: String(pos.current_signal?.direction ?? 'flat'),
      })
    }
    if (base.countdown_sec <= 0) return base
    const remain = Math.max(0, base.estimated_close_at - Date.now() / 1000)
    return {
      ...base,
      countdown_sec: remain,
      urgency: remain < 60 ? 'imminent' as const : base.urgency,
    }
  }, [
    tick,
    pos.entry_time,
    pos.direction,
    pos.unrealized_pct,
    pos.ladder,
    pos.guard,
    pos.current_signal,
    pos.exit_estimate,
    pos.breakeven_armed,
    pos.peak_upnl_pct,
  ])

  const holdSec = pos.entry_time
    ? Math.floor(Date.now() / 1000 - pos.entry_time)
    : 0
  const holdLabel = holdSec > 0
    ? (() => {
        const h = Math.floor(holdSec / 3600)
        const m = Math.floor((holdSec % 3600) / 60)
        const s = holdSec % 60
        if (h > 0) return `${h}sa ${m}dk`
        if (m > 0) return `${m}dk ${s}sn`
        return `${s}sn`
      })()
    : null

  return (
    <div className="min-w-[130px]">
      <div className={`text-sm tabular-nums ${URGENCY_STYLE[est.urgency] ?? URGENCY_STYLE.normal}`}>
        {formatCountdown(est.countdown_sec)}
      </div>
      <div className="text-[10px] text-gray-500 leading-tight mt-0.5" title={est.detail}>
        {est.label}
      </div>
      <div className="text-[10px] text-gray-600 truncate max-w-[140px]" title={est.detail}>
        {est.detail}
      </div>
      {est.secondary && (
        <div className="text-[9px] text-gray-700">{est.secondary}</div>
      )}
      {holdLabel && (
        <div className="text-[9px] text-gray-700 font-mono">açık {holdLabel}</div>
      )}
    </div>
  )
}
