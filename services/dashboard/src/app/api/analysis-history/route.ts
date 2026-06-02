import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const symbol = (searchParams.get('symbol') ?? '').toUpperCase()
  if (!symbol) return NextResponse.json({ error: 'symbol gerekli' }, { status: 400 })

  const redis = createRedis()
  try {
    const raw = await redis.lrange(`ai:analysis:history:${symbol}`, 0, 29)
    const history = raw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
    return NextResponse.json({ symbol, history })
  } finally {
    redis.disconnect()
  }
}
