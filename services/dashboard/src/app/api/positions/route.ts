import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    // OMS paper positions
    const posKeys = await redis.keys('oms:position:*')
    const [posRaws, dailyPnlRaw, tradeHistRaw] = await Promise.all([
      Promise.all(posKeys.map(k => redis.get(k))),
      redis.get('oms:daily_pnl'),
      redis.lrange('oms:trade_history', 0, 19),
    ])

    const seenSymbols = new Set<string>()
    const positions = posRaws
      .map((raw, i) => {
        if (!raw) return null
        try {
          const pos = JSON.parse(raw)
          const key = typeof posKeys[i] === 'string' ? posKeys[i] : (posKeys[i] as Buffer).toString()
          const symbol = (key.split(':').pop() ?? pos.symbol ?? '').toUpperCase()
          return { ...pos, symbol, key }
        } catch {
          return null
        }
      })
      .filter(Boolean)
      .filter(pos => {
        // Aynı symbol'ün mükerrer pozisyonlarını filtrele
        const sym = (pos as { symbol: string }).symbol
        if (seenSymbols.has(sym)) return false
        seenSymbols.add(sym)
        return true
      })

    // Get current prices for P&L calculation
    const priceRaws = await Promise.all(
      positions.map(p => redis.get(`binance:ticker:${(p!.symbol as string).toLowerCase()}`))
    )

    const enriched = positions.map((pos, i) => {
      const tickerRaw = priceRaws[i]
      let currentPrice = 0
      if (tickerRaw) {
        try {
          const t = JSON.parse(tickerRaw)
          const d = t.data ?? t
          const bid = parseFloat(d.b ?? 0)
          const ask = parseFloat(d.a ?? bid)
          currentPrice = bid > 0 && ask > 0 ? (bid + ask) / 2 : bid || ask
        } catch { /* ignore */ }
      }

      const entryPrice = pos!.entry_price ?? 0
      const direction = pos!.direction ?? 'long'
      const sizeUsd = pos!.size_usd ?? 0

      let unrealizedPct = 0
      let unrealizedUsdt = 0
      if (currentPrice > 0 && entryPrice > 0 && sizeUsd > 0) {
        unrealizedPct = direction === 'long'
          ? (currentPrice - entryPrice) / entryPrice
          : (entryPrice - currentPrice) / entryPrice
        unrealizedUsdt = sizeUsd * unrealizedPct
      }

      const ageSeconds = pos!.entry_time ? Date.now() / 1000 - pos!.entry_time : 0

      return {
        ...pos,
        current_price: currentPrice > 0 ? currentPrice : null,
        unrealized_pct: +(unrealizedPct * 100).toFixed(3),
        unrealized_usdt: +unrealizedUsdt.toFixed(4),
        age_hours: +(ageSeconds / 3600).toFixed(1),
      }
    })

    const tradeHistory = tradeHistRaw.map(r => {
      try { return JSON.parse(r) } catch { return null }
    }).filter(Boolean)

    return NextResponse.json({
      positions: enriched,
      daily_pnl: dailyPnlRaw ? parseFloat(dailyPnlRaw) : 0,
      trade_history: tradeHistory,
      position_count: enriched.length,
    })
  } finally {
    await redis.quit()
  }
}
