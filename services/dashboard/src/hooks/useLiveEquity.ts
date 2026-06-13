'use client'

import { useEffect, useMemo, useState } from 'react'
import type { CurvePoint } from '@/components/LiveEquityChart'

/** Sunucu eğrisine 2sn'de bir canlı nokta ekler — equity anlık akar. */
export function useLiveEquity(
  curve: CurvePoint[],
  currentEquity: number | undefined,
  intervalMs = 2000,
): CurvePoint[] {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (currentEquity == null) return
    const t = setInterval(() => setTick(n => n + 1), intervalMs)
    return () => clearInterval(t)
  }, [currentEquity, intervalMs])

  return useMemo(() => {
    if (!curve.length || currentEquity == null) return curve
    const now = Math.floor(Date.now() / 1000)
    const base = curve.filter(p => p.kind !== 'live')
    const last = base[base.length - 1]
    if (last && Math.abs(last.equity - currentEquity) < 0.005 && now - last.ts < 3) {
      return [...base, { ts: now, equity: currentEquity, kind: 'live' as const }]
    }
    return [
      ...base,
      { ts: now, equity: +currentEquity.toFixed(2), kind: 'live' as const },
    ]
  }, [curve, currentEquity, tick])
}
