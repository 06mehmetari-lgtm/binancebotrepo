import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'
import { fetchOpenPositions } from '@/lib/positions'

/** Hafif uç nokta — açık pozisyonların anlık kar/zararı (1sn poll). */
export async function GET() {
  const redis = createRedis()
  try {
    const { positions } = await fetchOpenPositions(redis)
    const total = positions.reduce((s, p) => s + (p.unrealized_usdt ?? 0), 0)
    const totalPct =
      positions.length > 0
        ? positions.reduce((s, p) => s + (p.unrealized_pct ?? 0), 0) / positions.length
        : 0

    return NextResponse.json({
      total_unrealized_usdt: +total.toFixed(2),
      avg_unrealized_pct: +totalPct.toFixed(3),
      updated_at: Date.now(),
      positions: positions.map(p => ({
        symbol: p.symbol,
        direction: p.direction,
        source: p.source,
        entry_price: p.entry_price,
        current_price: p.current_price,
        unrealized_pct: p.unrealized_pct,
        unrealized_usdt: p.unrealized_usdt,
        margin_usd: p.margin_usd ?? p.size_usd,
        notional_usd: p.notional_usd,
        leverage: p.leverage,
      })),
    })
  } finally {
    await redis.disconnect()
  }
}
