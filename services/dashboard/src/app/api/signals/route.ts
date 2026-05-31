import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const featureKeys = await redis.keys('features:latest:*')
    if (featureKeys.length === 0) return NextResponse.json([])

    const symbols = featureKeys.map(k => k.replace('features:latest:', ''))

    const pipeline = redis.pipeline()
    for (const sym of symbols) {
      pipeline.get(`signal:latest:${sym}`)
    }
    const results = await pipeline.exec()

    const signals = []
    for (let i = 0; i < symbols.length; i++) {
      const raw = results?.[i]?.[1] as string | null
      if (!raw) continue
      try {
        signals.push(JSON.parse(raw))
      } catch {
        // skip malformed entries
      }
    }

    return NextResponse.json(signals)
  } catch (e) {
    return NextResponse.json([], { status: 500 })
  } finally {
    redis.disconnect()
  }
}
