/** Build cumulative equity curves per shadow from closed trade list */

export type ShadowTrade = {
  pnl_usdt?: number
  pnl_pct?: number
  closed_at?: number
  symbol?: string
  direction?: string
}

export type ShadowEquityPoint = {
  ts: number
  equity: number
  pnl: number
  symbol?: string
  direction?: string
}

const SHADOW_START = 10000

export function buildShadowEquityCurve(
  trades: ShadowTrade[],
  startEquity = SHADOW_START,
): ShadowEquityPoint[] {
  const sorted = [...trades].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0))
  const curve: ShadowEquityPoint[] = [
    { ts: sorted[0]?.closed_at ? sorted[0].closed_at - 1 : Math.floor(Date.now() / 1000) - 3600, equity: startEquity, pnl: 0 },
  ]
  let equity = startEquity
  for (const t of sorted) {
    const pnl = t.pnl_usdt ?? 0
    equity += pnl
    curve.push({
      ts: Math.round(t.closed_at ?? Date.now() / 1000),
      equity: +equity.toFixed(2),
      pnl: +pnl.toFixed(4),
      symbol: t.symbol,
      direction: t.direction,
    })
  }
  return curve
}
