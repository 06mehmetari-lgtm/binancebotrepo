import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.lrange('activity:feed', 0, 49)
    const events = raw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
    return NextResponse.json(events)
  } catch (e) {
    return NextResponse.json([], { status: 500 })
  } finally {
    redis.disconnect()
  }
}
