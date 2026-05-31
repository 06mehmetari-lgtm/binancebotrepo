import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

const QDRANT_URL = process.env.QDRANT_URL || 'http://qdrant:6333'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

async function getTradeMemories(limit = 30) {
  try {
    const res = await fetch(`${QDRANT_URL}/collections/trade_memories/points/scroll`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit, with_payload: true, with_vector: false }),
      signal: AbortSignal.timeout(3000),
    })
    if (!res.ok) return []
    const data = await res.json() as { result?: { points?: unknown[] } }
    return data.result?.points ?? []
  } catch { return [] }
}

async function getCollectionInfo() {
  try {
    const res = await fetch(`${QDRANT_URL}/collections/trade_memories`, {
      signal: AbortSignal.timeout(2000),
    })
    if (!res.ok) return null
    const data = await res.json() as { result?: { points_count?: number; status?: string } }
    return data.result ?? null
  } catch { return null }
}

export async function GET() {
  const redis = createRedis()
  try {
    // Fetch Qdrant memories + collection info in parallel
    const [memories, collectionInfo] = await Promise.all([
      getTradeMemories(30),
      getCollectionInfo(),
    ])

    // Redis: best genomes + recent signals
    const genomeKeys = await redis.keys('neat:best_genome:*')
    const signalKeys = await redis.keys('signal:latest:*')

    const pipeline = redis.pipeline()
    for (const k of genomeKeys.slice(0, 20)) pipeline.get(k)
    for (const k of signalKeys.slice(0, 50)) pipeline.get(k)
    pipeline.get('context:regime')
    pipeline.get('context:crisis_level')
    pipeline.get('macro:vix')
    const results = await pipeline.exec()

    const genomeOffset = 0
    const signalOffset = genomeKeys.slice(0, 20).length
    const staticOffset = signalOffset + signalKeys.slice(0, 50).length

    // Parse genomes
    const genomes: Record<string, unknown>[] = []
    for (let i = 0; i < genomeKeys.slice(0, 20).length; i++) {
      const g = safeJson(results?.[genomeOffset + i]?.[1] as string | null) as Record<string, unknown> | null
      if (g) genomes.push(g)
    }

    // Parse signals to summarize direction distribution
    const directionCounts = { long: 0, short: 0, flat: 0 }
    const regimeCounts: Record<string, number> = {}
    for (let i = 0; i < signalKeys.slice(0, 50).length; i++) {
      const s = safeJson(results?.[signalOffset + i]?.[1] as string | null) as Record<string, unknown> | null
      if (!s) continue
      const dir = (s.direction as string) || 'flat'
      directionCounts[dir as keyof typeof directionCounts] = (directionCounts[dir as keyof typeof directionCounts] ?? 0) + 1
      const regime = s.regime as string
      if (regime) regimeCounts[regime] = (regimeCounts[regime] ?? 0) + 1
    }

    const regime = safeJson(results?.[staticOffset]?.[1] as string | null)
    const crisisLevel = safeJson(results?.[staticOffset + 1]?.[1] as string | null)
    const vixRaw = safeJson(results?.[staticOffset + 2]?.[1] as string | null) as Record<string, unknown> | null

    // Analyze memories for stats
    const wins = (memories as { payload?: { was_winner?: boolean; pnl_pct?: number; symbol?: string; regime?: string; error_category?: string } }[])
      .filter(m => m.payload?.was_winner === true)
    const losses = (memories as { payload?: { was_winner?: boolean; pnl_pct?: number; symbol?: string; regime?: string; error_category?: string } }[])
      .filter(m => m.payload?.was_winner === false)
    const totalMemories = (collectionInfo as { points_count?: number } | null)?.points_count ?? memories.length

    const errorCategories: Record<string, number> = {}
    const winRegimes: Record<string, number> = {}
    const topSymbols: Record<string, { wins: number; losses: number }> = {}

    for (const m of memories as { payload?: { was_winner?: boolean; symbol?: string; regime?: string; error_category?: string } }[]) {
      const p = m.payload ?? {}
      if (p.error_category) errorCategories[p.error_category] = (errorCategories[p.error_category] ?? 0) + 1
      if (p.was_winner && p.regime) winRegimes[p.regime] = (winRegimes[p.regime] ?? 0) + 1
      if (p.symbol) {
        if (!topSymbols[p.symbol]) topSymbols[p.symbol] = { wins: 0, losses: 0 }
        if (p.was_winner) topSymbols[p.symbol].wins++
        else topSymbols[p.symbol].losses++
      }
    }

    // Best genomes summary
    const bestFitness = genomes.reduce((best, g) => {
      const f = typeof g.fitness === 'number' ? g.fitness : 0
      return f > best ? f : best
    }, 0)
    const avgFitness = genomes.length
      ? genomes.reduce((s, g) => s + (typeof g.fitness === 'number' ? g.fitness : 0), 0) / genomes.length
      : 0

    return NextResponse.json({
      memories: (memories as { id?: unknown; payload?: Record<string, unknown> }[]).map(m => m.payload ?? {}),
      total_memories: totalMemories,
      win_count: wins.length,
      loss_count: losses.length,
      error_categories: errorCategories,
      win_regimes: winRegimes,
      top_symbols: Object.entries(topSymbols)
        .sort((a, b) => (b[1].wins + b[1].losses) - (a[1].wins + a[1].losses))
        .slice(0, 10)
        .map(([sym, stats]) => ({ symbol: sym, ...stats })),
      genomes: {
        count: genomes.length,
        best_fitness: bestFitness,
        avg_fitness: avgFitness,
        sample: genomes.slice(0, 5),
      },
      current_state: {
        direction_dist: directionCounts,
        regime_dist: regimeCounts,
        regime: typeof regime === 'string' ? regime : null,
        crisis_level: typeof crisisLevel === 'number' ? crisisLevel : 0,
        vix: typeof vixRaw?.value === 'number' ? vixRaw.value : null,
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
