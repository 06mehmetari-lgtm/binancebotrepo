/** Server-side equity curve: trade closes + hourly snapshots + live unrealized */

export type EquityPoint = {
  ts: number
  equity: number
  pnl?: number
  symbol?: string
  direction?: string
  kind: 'start' | 'trade' | 'snapshot' | 'live'
}

const PORTFOLIO_START = 10000

export function buildEquityCurve(input: {
  trades: { closed_at?: number; pnl_usdt?: number; symbol?: string; direction?: string }[]
  snapshots: { ts?: number; equity?: number }[]
  unrealizedUsdt: number
  nowTs?: number
  startEquity?: number
}): { curve: EquityPoint[]; realizedEquity: number; liveEquity: number } {
  const start = input.startEquity ?? PORTFOLIO_START
  const now = input.nowTs ?? Math.floor(Date.now() / 1000)
  const sortedTrades = [...input.trades].sort(
    (a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0)
  )

  const points: EquityPoint[] = [
    { ts: sortedTrades[0]?.closed_at ? sortedTrades[0].closed_at - 1 : now - 86400, equity: start, kind: 'start' },
  ]

  let realized = start
  let lastTradeTs = 0
  for (const t of sortedTrades) {
    realized += t.pnl_usdt ?? 0
    const ts = Math.round(t.closed_at ?? 0)
    if (ts > 0) lastTradeTs = ts
    points.push({
      ts: ts || now,
      equity: +realized.toFixed(2),
      pnl: +(t.pnl_usdt ?? 0).toFixed(2),
      symbol: t.symbol ?? '',
      direction: t.direction ?? '',
      kind: 'trade',
    })
  }

  const snapSorted = [...input.snapshots]
    .filter(s => (s.ts ?? 0) > 0 && (s.equity ?? 0) > 0)
    .sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0))

  for (const s of snapSorted) {
    const ts = Math.round(s.ts ?? 0)
    if (ts <= lastTradeTs && sortedTrades.length > 0) continue
    const dup = points.some(p => Math.abs(p.ts - ts) < 30 && p.kind !== 'trade')
    if (dup) continue
    points.push({
      ts,
      equity: +(s.equity ?? 0).toFixed(2),
      kind: 'snapshot',
    })
  }

  const liveEquity = +(realized + input.unrealizedUsdt).toFixed(2)
  const last = points[points.length - 1]
  if (!last || last.kind !== 'live' || Math.abs(last.equity - liveEquity) > 0.01 || now - last.ts > 3) {
    if (last?.kind === 'live') points.pop()
    points.push({ ts: now, equity: liveEquity, kind: 'live' })
  } else if (last.kind === 'live') {
    last.ts = now
    last.equity = liveEquity
  }

  points.sort((a, b) => a.ts - b.ts)
  return { curve: points, realizedEquity: +realized.toFixed(2), liveEquity }
}

export { PORTFOLIO_START }
