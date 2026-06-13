'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { PositionDecision } from '@/lib/positions'
import {
  computeExitEstimate,
  formatCountdown,
  pnlVelocityPctPerSec,
} from '@/lib/exit-estimate'

const URGENCY_STYLE: Record<string, string> = {
  now: 'text-red-400 font-black animate-pulse',
  imminent: 'text-orange-400 font-bold',
  normal: 'text-cyan-400 font-mono',
}

type PnlSample = { t: number; upnl: number }

export function ExitCountdownCell({ pos }: { pos: PositionDecision }) {
  const [tick, setTick] = useState(0)
  const samplesRef = useRef<PnlSample[]>([])

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const upnl = pos.unrealized_pct ?? 0

  useEffect(() => {
    const now = Date.now() / 1000
    const arr = samplesRef.current
    arr.push({ t: now, upnl })
    if (arr.length > 120) arr.splice(0, arr.length - 120)
  }, [tick, upnl])

  const est = useMemo(() => {
    void tick
    const now = Date.now() / 1000
    const velocity = pnlVelocityPctPerSec(samplesRef.current)

    const fresh = computeExitEstimate({
      entry_time: pos.entry_time,
      direction: pos.direction,
      unrealized_pct: upnl,
      ladder: {
        ...pos.ladder,
        breakeven_armed: pos.ladder?.breakeven_armed ?? pos.breakeven_armed,
        peak_upnl_pct: pos.peak_upnl_pct ?? pos.ladder?.peak_upnl_pct,
      },
      guard: pos.guard,
      current_signal_direction: String(pos.current_signal?.direction ?? 'flat'),
      current_signal_confidence: Number(pos.current_signal?.confidence ?? 0),
      agent_verdict_direction: String(pos.verdict?.direction ?? 'flat'),
      agent_verdict_confidence: Number(pos.verdict?.confidence ?? 0),
      pnl_velocity_pct_per_sec: velocity,
      now,
    })

    if (fresh.countdown_sec <= 0) return fresh

    const remain = Math.max(0, fresh.estimated_close_at - now)
    return {
      ...fresh,
      countdown_sec: remain,
      urgency:
        remain <= 0
          ? ('now' as const)
          : remain < 60
            ? ('imminent' as const)
            : fresh.urgency,
    }
  }, [
    tick,
    upnl,
    pos.entry_time,
    pos.direction,
    pos.ladder,
    pos.guard,
    pos.current_signal,
    pos.verdict,
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

  const closeClock = est.countdown_sec > 0
    ? new Date((est.estimated_close_at) * 1000).toLocaleTimeString('tr-TR', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : null

  return (
    <div className="min-w-[140px]">
      <div className={`text-sm tabular-nums ${URGENCY_STYLE[est.urgency] ?? URGENCY_STYLE.normal}`}>
        {formatCountdown(est.countdown_sec)}
      </div>
      <div className="text-[10px] text-gray-500 leading-tight mt-0.5" title={est.detail}>
        {est.label}
      </div>
      <div className="text-[10px] text-gray-600 truncate max-w-[160px]" title={est.detail}>
        {est.detail}
      </div>
      {closeClock && est.urgency !== 'now' && (
        <div className="text-[9px] text-gray-500 font-mono">~{closeClock}</div>
      )}
      {est.secondary && (
        <div className="text-[9px] text-gray-700">alt: {est.secondary}</div>
      )}
      {holdLabel && (
        <div className="text-[9px] text-gray-700 font-mono">açık {holdLabel}</div>
      )}
    </div>
  )
}
