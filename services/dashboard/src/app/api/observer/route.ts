import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const limit = Math.min(parseInt(searchParams.get('limit') || '100'), 500)

  const redis = createRedis()
  try {
    const raw = await redis.lrange('observer:events', 0, limit - 1)
    const events = raw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
    return NextResponse.json(events)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
