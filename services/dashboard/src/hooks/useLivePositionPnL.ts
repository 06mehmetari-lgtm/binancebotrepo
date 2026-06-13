'use client'

import { useEffect, useMemo, useState } from 'react'
import type { PositionDecision } from '@/lib/positions'

type LivePnLRow = {
  symbol: string
  direction: string
  current_price?: number | null
  unrealized_pct?: number
  unrealized_usdt?: number
}

type LivePnLPayload = {
  total_unrealized_usdt: number
  avg_unrealized_pct: number
  updated_at: number
  positions: LivePnLRow[]
}

export function useLivePositionPnL(basePositions: PositionDecision[], enabled = true) {
  const [live, setLive] = useState<LivePnLPayload | null>(null)

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch('/api/positions/live-pnl', { cache: 'no-store' })
        if (!res.ok || cancelled) return
        setLive(await res.json())
      } catch {
        /* ignore transient */
      }
    }

    poll()
    const t = setInterval(poll, 1000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [enabled])

  const positions = useMemo(() => {
    if (!live?.positions?.length) return basePositions
    const map = new Map(live.positions.map(p => [`${p.symbol}:${p.direction}`, p]))
    return basePositions.map(p => {
      const row = map.get(`${p.symbol}:${p.direction}`)
      if (!row) return p
      return {
        ...p,
        current_price: row.current_price ?? p.current_price,
        unrealized_pct: row.unrealized_pct ?? p.unrealized_pct,
        unrealized_usdt: row.unrealized_usdt ?? p.unrealized_usdt,
      }
    })
  }, [basePositions, live])

  const totalUnrealized =
    live?.total_unrealized_usdt ??
    basePositions.reduce((s, p) => s + (p.unrealized_usdt ?? 0), 0)

  return {
    positions,
    totalUnrealized,
    avgUnrealizedPct: live?.avg_unrealized_pct ?? 0,
    liveAt: live?.updated_at ?? 0,
    isLive: Boolean(live?.updated_at),
  }
}
