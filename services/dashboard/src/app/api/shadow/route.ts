import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { buildShadowEquityCurve } from '@/lib/build-shadow-equity'

const SHADOW_IDS = ['SHADOW_A', 'SHADOW_B', 'SHADOW_C']
const START_EQUITY = 10000

export async function GET() {
  const redis = createRedis()
  try {
    const [lbRaw, ...tradeLists] = await Promise.all([
      redis.get('shadow:leaderboard'),
      ...SHADOW_IDS.map(id => redis.lrange(`shadow:trades:${id}`, 0, 499)),
    ])

    let leaderboard: unknown[] = []
    if (lbRaw) {
      try {
        const parsed = JSON.parse(lbRaw)
        leaderboard = Array.isArray(parsed) ? parsed : []
      } catch {
        leaderboard = []
      }
    }

    const equity_curves: Record<string, ReturnType<typeof buildShadowEquityCurve>> = {}
    for (let i = 0; i < SHADOW_IDS.length; i++) {
      const id = SHADOW_IDS[i]
      const trades = (tradeLists[i] as string[])
        .map(r => {
          try {
            const t = JSON.parse(r) as Record<string, unknown>
            return {
              pnl_usdt: Number(t.pnl_usdt ?? 0),
              pnl_pct: Number(t.pnl_pct ?? 0),
              closed_at: Number(t.closed_at ?? t.exit_time ?? 0) || undefined,
              symbol: String(t.symbol ?? ''),
              direction: String(t.direction ?? ''),
            }
          } catch {
            return null
          }
        })
        .filter(Boolean)

      // Redis LPUSH = newest first; assign synthetic ts for trades missing closed_at
      const withTs = trades.map((t, idx) => {
        if (t!.closed_at) return t!
        return { ...t!, closed_at: Math.floor(Date.now() / 1000) - idx * 60 }
      })

      equity_curves[id] = buildShadowEquityCurve(withTs, START_EQUITY)
    }

    return NextResponse.json({
      leaderboard,
      equity_curves,
      start_equity: START_EQUITY,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
