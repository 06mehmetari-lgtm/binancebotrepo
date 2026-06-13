export function computeUnrealizedPnL(params: {
  direction: string
  entryPrice: number
  currentPrice: number
  marginUsd?: number
  leverage?: number
  notionalUsd?: number
}): { pct: number; usdt: number } {
  const { direction, entryPrice, currentPrice } = params
  if (currentPrice <= 0 || entryPrice <= 0) {
    return { pct: 0, usdt: 0 }
  }

  const pct =
    direction === 'long'
      ? ((currentPrice - entryPrice) / entryPrice) * 100
      : ((entryPrice - currentPrice) / entryPrice) * 100

  const margin = Math.max(0, params.marginUsd ?? 0)
  const lev = Math.max(1, params.leverage ?? 1)
  const notional = params.notionalUsd ?? 0
  const exposure = notional > 0 ? notional : margin > 0 ? margin * lev : 0
  const usdt = exposure > 0 ? exposure * (pct / 100) : 0

  return { pct, usdt }
}
