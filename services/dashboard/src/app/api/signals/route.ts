import { NextResponse } from 'next/server'
import { Redis } from 'ioredis'

const redis = new Redis({ host: process.env.REDIS_HOST || 'redis', port: 6379, password: process.env.REDIS_PASSWORD || undefined, lazyConnect: true })

export async function GET() {
  try {
    const symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
    const signals = []
    for (const sym of symbols) {
      const raw = await redis.get(`signal:latest:${sym}`)
      if (raw) signals.push(JSON.parse(raw))
    }
    return NextResponse.json(signals)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
