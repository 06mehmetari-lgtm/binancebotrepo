import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const HISTORY_KEY = 'alert:history:v1'
const SEEN_PREFIX = 'alert:seen:'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.lrange(HISTORY_KEY, 0, 99)
    const alerts = raw
      .map(r => {
        try {
          return JSON.parse(r)
        } catch {
          return null
        }
      })
      .filter(Boolean)
    return NextResponse.json(alerts)
  } finally {
    redis.disconnect()
  }
}

export async function POST(req: Request) {
  const redis = createRedis()
  try {
    const body = await req.json().catch(() => ({}))
    const symbol = (body.symbol as string | undefined)?.toUpperCase()
    if (symbol) {
      const seen = await redis.set(
        `${SEEN_PREFIX}${symbol}`,
        '1',
        'EX',
        300,
        'NX',
      )
      if (seen === null) {
        return NextResponse.json({ ok: true, skipped: true, reason: 'debounced' })
      }
    }
    const entry = {
      ...body,
      ts: body.ts ?? Date.now() / 1000,
    }
    await redis.lpush(HISTORY_KEY, JSON.stringify(entry))
    await redis.ltrim(HISTORY_KEY, 0, 499)
    await redis.expire(HISTORY_KEY, 86400)
    return NextResponse.json({ ok: true })
  } finally {
    redis.disconnect()
  }
}
