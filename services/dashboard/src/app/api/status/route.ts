import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols, scanKeys } from '@/lib/universe'

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

    const symbols = await discoverSymbols(redis)
    const activeSymbolCount = symbols.length
    const genomeKeys = await scanKeys(redis, 'neat:best_genome:*')

    // Batch fetch static keys + per-symbol signal keys + genome keys
    const pipeline = redis.pipeline()
    pipeline.get('ws:status')
    pipeline.get('shadow:leaderboard')
    pipeline.get('sentiment:fear_greed')
    pipeline.get('macro:vix')
    pipeline.get('portfolio:state:v1')
    pipeline.get('snapshot:universe:v1')
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
    const portfolioState = safeJson(results?.[4]?.[1] as string | null) as Record<string, unknown> | null
    const universeSnap = safeJson(results?.[5]?.[1] as string | null) as { counts?: Record<string, number> } | null

    const staticOffset = 6

    let signalLong = universeSnap?.counts?.long ?? 0
    let signalShort = universeSnap?.counts?.short ?? 0
    let closeActions = universeSnap?.counts?.close_actions ?? 0
    let holdActions = universeSnap?.counts?.hold_actions ?? 0

    // Aggregate signal stats
    let totalSignals = 0
    let confidenceSum = 0
    let confidenceCount = 0
    for (let i = 0; i < symbols.length; i++) {
      const raw = results?.[staticOffset + i]?.[1] as string | null
      const sig = safeJson(raw) as Record<string, unknown> | null
      if (!sig) continue
      totalSignals++
      const dir = sig.direction as string
      if (!universeSnap?.counts) {
        if (dir === 'long' && sig.is_valid) signalLong++
        if (dir === 'short' && sig.is_valid) signalShort++
        if (sig.trade_action === 'close') closeActions++
        if (sig.trade_action === 'hold') holdActions++
      }
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
      signal_long: signalLong,
      signal_short: signalShort,
      close_actions: closeActions,
      hold_actions: holdActions,
      open_positions: Number(portfolioState?.total_open ?? universeSnap?.counts?.open_positions ?? 0),
      oms_open: Number(portfolioState?.oms_open ?? 0),
      avg_confidence: avgConfidence,
      best_genome_fitness: bestGenomeFitness,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
