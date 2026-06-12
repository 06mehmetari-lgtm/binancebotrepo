import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
export const maxDuration = 25
import { createRedis } from '../_redis'
import { fetchOpenPositions } from '@/lib/positions'

export async function GET() {
  const redis = createRedis()
  try {
    const { positions, portfolio } = await fetchOpenPositions(redis)

    const [dailyPnlRaw, tradeHistRaw, haltRaw] = await Promise.all([
      redis.get('oms:daily_pnl'),
      redis.lrange('oms:trade_history', 0, 19),
      redis.get('system:trading:halted'),
    ])

    const tradeHistory = (tradeHistRaw as string[])
      .map(r => {
        try {
          return JSON.parse(r)
        } catch {
          return null
        }
      })
      .filter(Boolean)

    let trading_halted = false
    let halt_reason: string | null = null
    if (haltRaw) {
      try {
        const h = JSON.parse(haltRaw)
        trading_halted = Boolean(h.halted)
        halt_reason = typeof h.reason === 'string' ? h.reason : null
      } catch {
        trading_halted = true
      }
    }

    return NextResponse.json({
      positions,
      portfolio,
      daily_pnl: dailyPnlRaw ? parseFloat(dailyPnlRaw) : 0,
      trade_history: tradeHistory,
      position_count: positions.length,
      trading_halted,
      halt_reason,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
