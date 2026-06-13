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
        entry_time: p.entry_time,
        current_price: p.current_price,
        unrealized_pct: p.unrealized_pct,
        unrealized_usdt: p.unrealized_usdt,
        margin_usd: p.margin_usd ?? p.size_usd,
        notional_usd: p.notional_usd,
        leverage: p.leverage,
        guard: p.guard,
        verdict: p.verdict,
        current_signal: p.current_signal
          ? { direction: p.current_signal.direction }
          : undefined,
        ladder: p.ladder
          ? {
              stop_loss_pct: p.ladder.stop_loss_pct,
              take_profit_pct: p.ladder.take_profit_pct,
              breakeven_armed: p.ladder.breakeven_armed,
              peak_upnl_pct: p.ladder.peak_upnl_pct,
              trough_upnl_pct: p.ladder.trough_upnl_pct,
              bounce_from_trough_pct: p.ladder.bounce_from_trough_pct,
              recovery_armed: p.ladder.recovery_armed,
              trail_floor_pct: p.ladder.trail_floor_pct,
            }
          : undefined,
        peak_upnl_pct: p.peak_upnl_pct,
        breakeven_armed: p.breakeven_armed,
      })),
    })
  } finally {
    await redis.disconnect()
  }
}
