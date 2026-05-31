import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET(req: Request) {
  const redis = createRedis()
  try {
    const { searchParams } = new URL(req.url)
    const symbol = searchParams.get('symbol')

    if (symbol) {
      const [profileRaw, globalRaw, hb] = await Promise.all([
        redis.get(`learn:profile:${symbol}`),
        redis.get('learn:global:v1'),
        redis.get('system:heartbeat:learning_engine'),
      ])
      return NextResponse.json({
        symbol,
        profile: profileRaw ? JSON.parse(profileRaw) : null,
        global: globalRaw ? JSON.parse(globalRaw) : null,
        learning_active: !!hb,
        heartbeat: hb ? parseFloat(hb) : null,
      })
    }

    const [globalRaw, hb] = await Promise.all([
      redis.get('learn:global:v1'),
      redis.get('system:heartbeat:learning_engine'),
    ])
    return NextResponse.json({
      global: globalRaw ? JSON.parse(globalRaw) : null,
      learning_active: !!hb,
      heartbeat: hb ? parseFloat(hb) : null,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
