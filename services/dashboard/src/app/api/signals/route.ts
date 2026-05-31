import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols } from '@/lib/universe'

export async function GET() {
  const redis = createRedis()
  try {
    const symbols = await discoverSymbols(redis)
    if (symbols.length === 0) return NextResponse.json([])

    const snapRaw = await redis.get('snapshot:universe:v1')

    const pipeline = redis.pipeline()
    for (const sym of symbols) {
      pipeline.get(`signal:latest:${sym}`)
      pipeline.get(`features:latest:${sym}`)
    }
    const results = await pipeline.exec()

    const signals = []
    const half = symbols.length
    for (let i = 0; i < symbols.length; i++) {
      const sigRaw = results?.[i]?.[1] as string | null
      const featRaw = results?.[half + i]?.[1] as string | null
      if (sigRaw) {
        try {
          signals.push(JSON.parse(sigRaw))
          continue
        } catch { /* fall through */ }
      }
      if (featRaw) {
        try {
          const f = JSON.parse(featRaw)
          signals.push({
            symbol: symbols[i],
            direction: 'flat',
            confidence: 0,
            regime: 'unknown',
            drift_status: f.drift_status ?? 'STABLE',
            kelly_fraction: 0,
            crisis_level: 0,
            source: 'pending',
            rsi: f.rsi_14,
          })
        } catch { /* skip */ }
      }
    }

    return NextResponse.json(signals)
  } catch (e) {
    return NextResponse.json([], { status: 500 })
  } finally {
    redis.disconnect()
  }
}
