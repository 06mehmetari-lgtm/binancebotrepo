import { NextResponse } from 'next/server'
import { Redis } from 'ioredis'

const redis = new Redis({ host: process.env.REDIS_HOST || 'redis', port: 6379, password: process.env.REDIS_PASSWORD || undefined, lazyConnect: true })

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url)
    const symbol = searchParams.get('symbol') || 'BTCUSDT'
    const raw = await redis.get(`agents:verdicts:${symbol}`)
    const verdict = await redis.get(`agents:verdict:${symbol}`)
    return NextResponse.json({ votes: raw ? JSON.parse(raw) : [], verdict: verdict ? JSON.parse(verdict) : null })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
