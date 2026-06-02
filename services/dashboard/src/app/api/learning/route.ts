import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.lrange('training:lessons', 0, 99)
    const lessons = raw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(l => l && (l.outcome === 'WIN' || l.outcome === 'LOSS') && l.side && l.symbol)
    return NextResponse.json(lessons)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
