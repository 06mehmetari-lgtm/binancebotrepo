import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.get('shadow:leaderboard')
    if (!raw) return NextResponse.json([])
    try {
      const parsed = JSON.parse(raw)
      return NextResponse.json(Array.isArray(parsed) ? parsed : [])
    } catch {
      return NextResponse.json([])
    }
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
