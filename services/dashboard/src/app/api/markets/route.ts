export const dynamic = 'force-dynamic'
import { discoverSymbols } from '@/lib/universe'
import { withRedisCache } from '@/lib/api-handler'

function contextCrisis(features: Record<string, unknown>): number {
  const v = features.crisis_level
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

function safeJson(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export async function GET() {
  return withRedisCache('api:cache:markets:v1', 5, async redis => {
    const symbols = await discoverSymbols(redis)
    if (symbols.length === 0) return []

    // Fetch all feature and signal values in parallel using a pipeline
    const pipeline = redis.pipeline()
    for (const sym of symbols) {
      pipeline.get(`features:latest:${sym}`)
    }
    for (const sym of symbols) {
      pipeline.get(`signal:latest:${sym}`)
    }
    const results = await pipeline.exec()

    const markets: Record<string, unknown>[] = []
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
        direction: signal?.direction ?? 'flat',
        confidence: typeof signal?.confidence === 'number' ? signal.confidence : 0,
        kelly_fraction: signal?.kelly_fraction ?? features.kelly_fraction,
        crisis_level: signal?.crisis_level ?? contextCrisis(features),
        signal: signal ?? null,
      })
    }

    // Sort by volume_ratio descending; treat missing/non-numeric as 0
    markets.sort((a, b) => {
      const av = typeof a.volume_ratio === 'number' ? a.volume_ratio : 0
      const bv = typeof b.volume_ratio === 'number' ? b.volume_ratio : 0
      return bv - av
    })

    return markets
  })
}
