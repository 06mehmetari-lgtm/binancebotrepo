import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const MAX_POSITIONS = parseInt(process.env.MAX_OPEN_POSITIONS ?? '20', 10)

async function resolvePrice(
  tickerRaw: string | null,
  marketRaw: string | null,
  featRaw: string | null,
): Promise<number> {
  if (tickerRaw) {
    try {
      const t = JSON.parse(tickerRaw)
      const d = t.data ?? t
      const bid = parseFloat(d.b ?? d.bid ?? 0)
      const ask = parseFloat(d.a ?? d.ask ?? bid)
      if (bid > 0) return (bid + ask) / 2
    } catch { /* fall through */ }
  }
  if (marketRaw) {
    const p = parseFloat(marketRaw)
    if (p > 0) return p
  }
  if (featRaw) {
    try {
      const f = JSON.parse(featRaw)
      if (f.close && f.close > 0) return f.close
    } catch { /* fall through */ }
  }
  return 0
}

export async function GET() {
  const redis = createRedis()
  try {
    const posKeys = await redis.keys('oms:position:*')
    const [posRaws, dailyPnlRaw, tradeHistRaw] = await Promise.all([
      Promise.all(posKeys.map(k => redis.get(k))),
      redis.get('oms:daily_pnl'),
      redis.lrange('oms:trade_history', 0, 49),
    ])

    const seenSymbols = new Set<string>()
    const positions = posRaws
      .map((raw, i) => {
        if (!raw) return null
        try {
          const pos = JSON.parse(raw)
          const key = typeof posKeys[i] === 'string' ? posKeys[i] : (posKeys[i] as Buffer).toString()
          const symbol = (key.split(':').pop() ?? pos.symbol ?? '').toUpperCase()
          return { ...pos, symbol }
        } catch { return null }
      })
      .filter(Boolean)
      .filter(pos => {
        const sym = (pos as { symbol: string }).symbol
        if (seenSymbols.has(sym)) return false
        seenSymbols.add(sym)
        return true
      })

    const symbols = positions.map(p => (p!.symbol as string).toUpperCase())

    // Fetch all price sources in parallel
    const [tickerRaws, marketRaws, featRaws] = await Promise.all([
      Promise.all(symbols.map(s => redis.get(`binance:ticker:${s.toLowerCase()}`))),
      Promise.all(symbols.map(s => redis.get(`market:price:${s}`))),
      Promise.all(symbols.map(s => redis.get(`features:latest:${s}`))),
    ])

    const enriched = await Promise.all(positions.map(async (pos, i) => {
      const currentPrice = await resolvePrice(tickerRaws[i], marketRaws[i], featRaws[i])

      const entryPrice  = Number(pos!.entry_price ?? 0)
      const direction   = (pos!.direction ?? 'long') as string
      const sizeUsd     = Number(pos!.size_usd ?? 0)
      const stopPct     = pos!.stop_pct != null ? Number(pos!.stop_pct) : null
      const tpPct       = pos!.tp_pct   != null ? Number(pos!.tp_pct)   : null

      let unrealizedPct = 0
      let unrealizedUsdt = 0
      if (currentPrice > 0 && entryPrice > 0 && sizeUsd > 0) {
        unrealizedPct = direction === 'long'
          ? (currentPrice - entryPrice) / entryPrice
          : (entryPrice - currentPrice) / entryPrice
        unrealizedUsdt = sizeUsd * unrealizedPct
      }

      // TP / SL absolute price levels (stop_pct/tp_pct stored as % values, e.g. -2.5, +4.0)
      const slPrice = entryPrice > 0 && stopPct != null
        ? entryPrice * (1 + stopPct / 100)
        : null
      const tpPrice = entryPrice > 0 && tpPct != null
        ? entryPrice * (1 + tpPct / 100)
        : null

      const ageSeconds = pos!.entry_time ? Date.now() / 1000 - Number(pos!.entry_time) : 0

      return {
        ...pos,
        current_price:    currentPrice > 0 ? currentPrice : null,
        price_live:       currentPrice > 0,
        unrealized_pct:   +(unrealizedPct * 100).toFixed(3),
        unrealized_usdt:  +unrealizedUsdt.toFixed(4),
        age_hours:        +(ageSeconds / 3600).toFixed(2),
        sl_price:         slPrice != null ? +slPrice.toFixed(6) : null,
        tp_price:         tpPrice != null ? +tpPrice.toFixed(6) : null,
      }
    }))

    const tradeHistory = tradeHistRaw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)

    return NextResponse.json({
      positions: enriched,
      daily_pnl: dailyPnlRaw ? parseFloat(dailyPnlRaw) : 0,
      trade_history: tradeHistory,
      position_count: enriched.length,
      max_positions: MAX_POSITIONS,
    })
  } finally {
    await redis.quit()
  }
}
