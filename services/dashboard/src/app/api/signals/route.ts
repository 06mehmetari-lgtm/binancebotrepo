import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols } from '@/lib/universe'

export async function GET() {
  const redis = createRedis()
  try {
    const symbols = await discoverSymbols(redis)
    if (symbols.length === 0) return NextResponse.json([])

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
