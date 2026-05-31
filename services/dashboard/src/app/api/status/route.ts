import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function macroVixNumber(raw: unknown): number | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (raw && typeof raw === 'object' && 'value' in raw) {
    const v = (raw as { value?: unknown }).value
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }
  return null
}

export async function GET() {
  const redis = createRedis()
  try {
    await redis.ping()

    // Discover active symbols from feature keys
    const featureKeys = await redis.keys('features:latest:*')
    const symbols = featureKeys.map(k => k.replace('features:latest:', ''))
    const activeSymbolCount = symbols.length

    // Discover all NEAT genome keys for best fitness calculation
    const genomeKeys = await redis.keys('neat:best_genome:*')

    // Batch fetch static keys + per-symbol signal keys + genome keys
    const pipeline = redis.pipeline()
    pipeline.get('ws:status')
    pipeline.get('shadow:leaderboard')
    pipeline.get('sentiment:fear_greed')
    pipeline.get('macro:vix')
    for (const sym of symbols) {
      pipeline.get(`signal:latest:${sym}`)
    }
    for (const key of genomeKeys) {
      pipeline.get(key)
    }
    const results = await pipeline.exec()

    const wsStatus = safeJson(results?.[0]?.[1] as string | null)
    const shadowLeaderboard = safeJson(results?.[1]?.[1] as string | null) ?? []
    const fearGreed = safeJson(results?.[2]?.[1] as string | null)
    const macroVix = safeJson(results?.[3]?.[1] as string | null)

    const staticOffset = 4

    // Aggregate signal stats
    let totalSignals = 0
    let confidenceSum = 0
    let confidenceCount = 0
    for (let i = 0; i < symbols.length; i++) {
      const raw = results?.[staticOffset + i]?.[1] as string | null
      const sig = safeJson(raw) as Record<string, unknown> | null
      if (!sig) continue
      totalSignals++
      if (typeof sig.confidence === 'number') {
        confidenceSum += sig.confidence
        confidenceCount++
      }
    }
    const avgConfidence = confidenceCount > 0 ? confidenceSum / confidenceCount : null

    // Find best genome fitness across all NEAT keys
    const genomeOffset = staticOffset + symbols.length
    let bestGenomeFitness: number | null = null
    for (let i = 0; i < genomeKeys.length; i++) {
      const raw = results?.[genomeOffset + i]?.[1] as string | null
      const genome = safeJson(raw) as Record<string, unknown> | null
      if (!genome) continue
      if (typeof genome.fitness === 'number') {
        if (bestGenomeFitness === null || genome.fitness > bestGenomeFitness) {
          bestGenomeFitness = genome.fitness
        }
      }
    }

    return NextResponse.json({
      redis: 'connected',
      ws_status: wsStatus,
      shadow_leaderboard: shadowLeaderboard,
      fear_greed: fearGreed,
      macro_vix: macroVixNumber(macroVix),
      active_symbol_count: activeSymbolCount,
      total_signals: totalSignals,
      avg_confidence: avgConfidence,
      best_genome_fitness: bestGenomeFitness,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
