import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.lrange('training:lessons', 0, 49)
    const lessons = raw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
    return NextResponse.json(lessons)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
