import { NextResponse } from 'next/server'
import { Redis } from 'ioredis'

const redis = new Redis({ host: process.env.REDIS_HOST || 'redis', port: 6379, password: process.env.REDIS_PASSWORD || undefined, lazyConnect: true })

export async function GET() {
  try {
    await redis.ping()
    const symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
    const services = ['ws:status', 'shadow:leaderboard', 'scenarios:latest_summary']
    const data: Record<string, unknown> = { redis: 'connected' }

    for (const svc of services) {
      const val = await redis.get(svc)
      data[svc] = val ? JSON.parse(val) : null
    }

    for (const sym of symbols) {
      const feat = await redis.get(`features:latest:${sym}`)
      const ctx = await redis.get(`context:latest:${sym}`)
      const sig = await redis.get(`signal:latest:${sym}`)
      data[`symbol:${sym}`] = {
        has_features: !!feat,
        has_context: !!ctx,
        signal: sig ? JSON.parse(sig) : null,
      }
    }

    return NextResponse.json(data)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
