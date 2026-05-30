import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

function safeJson(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export async function GET() {
  const redis = createRedis()
  try {
    const featureKeys = await redis.keys('features:latest:*')
    if (featureKeys.length === 0) return NextResponse.json([])

    const symbols = featureKeys.map(k => k.replace('features:latest:', ''))

    // Fetch all feature and signal values in parallel using a pipeline
    const pipeline = redis.pipeline()
    for (const sym of symbols) {
      pipeline.get(`features:latest:${sym}`)
    }
    for (const sym of symbols) {
      pipeline.get(`signal:latest:${sym}`)
    }
    const results = await pipeline.exec()

    const markets = []
    const half = symbols.length

    for (let i = 0; i < symbols.length; i++) {
      const featRaw = results?.[i]?.[1] as string | null
      const sigRaw = results?.[half + i]?.[1] as string | null

      const features = safeJson(featRaw)
      if (!features) continue

      const signal = safeJson(sigRaw)

      markets.push({
        symbol: symbols[i],
        ...features,
        signal: signal ?? null,
      })
    }

    // Sort by volume_ratio descending; treat missing/non-numeric as 0
    markets.sort((a, b) => {
      const av = typeof a.volume_ratio === 'number' ? a.volume_ratio : 0
      const bv = typeof b.volume_ratio === 'number' ? b.volume_ratio : 0
      return bv - av
    })

    return NextResponse.json(markets)
  } catch (e) {
    return NextResponse.json([], { status: 500 })
  } finally {
    redis.disconnect()
  }
}
