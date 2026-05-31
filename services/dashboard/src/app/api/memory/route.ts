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
    // Parallel fetch: Qdrant + Redis key discovery
    const [memories, collectionInfo, signalKeys, genomeKeys, contextKeys, activityRaw, agentKeys] = await Promise.all([
      getTradeMemories(30),
      getCollectionInfo(),
      redis.keys('signal:latest:*'),
      redis.keys('neat:best_genome:*'),
      redis.keys('context:latest:*'),
      redis.lrange('activity:feed', 0, 49),
      redis.keys('agents:verdicts:*'),
    ])

    // Parse activity feed
    const activity = activityRaw
      .map(r => { try { return JSON.parse(r as string) } catch { return null } })
      .filter(Boolean)

    // Build big pipeline
    const pipeline = redis.pipeline()
    for (const k of signalKeys) pipeline.get(k as string)
    for (const k of genomeKeys.slice(0, 20)) pipeline.get(k as string)
    // Sample context for 5 coins
    for (const k of contextKeys.slice(0, 5)) pipeline.get(k as string)
    // Sample agent verdicts for 3 coins
    for (const k of agentKeys.slice(0, 3)) pipeline.get(k as string)
    pipeline.get('ws:status')
    pipeline.get('macro:vix')
    pipeline.get('shadow:leaderboard')
    pipeline.get('sentiment:fear_greed')
    const results = await pipeline.exec()

    const sigOffset = 0
    const genOffset = signalKeys.length
    const ctxOffset = genOffset + Math.min(genomeKeys.length, 20)
    const agentOffset = ctxOffset + Math.min(contextKeys.length, 5)
    const staticOffset = agentOffset + Math.min(agentKeys.length, 3)

    // Parse all signals
    const allSignals: Record<string, unknown>[] = []
    const directionCounts = { long: 0, short: 0, flat: 0 }
    const regimeCounts: Record<string, number> = {}
    const driftCounts: Record<string, number> = {}

    for (let i = 0; i < signalKeys.length; i++) {
      const s = safeJson(results?.[sigOffset + i]?.[1] as string | null) as Record<string, unknown> | null
      if (!s) continue
      allSignals.push(s)
      const dir = (s.direction as string) || 'flat'
      if (dir === 'long') directionCounts.long++
      else if (dir === 'short') directionCounts.short++
      else directionCounts.flat++
      const regime = s.regime as string
      if (regime) regimeCounts[regime] = (regimeCounts[regime] ?? 0) + 1
      const drift = s.drift_status as string
      if (drift) driftCounts[drift] = (driftCounts[drift] ?? 0) + 1
    }

    // Top 10 active signals by confidence
    const activeSignals = allSignals
      .filter(s => s.direction !== 'flat')
      .sort((a, b) => (b.confidence as number) - (a.confidence as number))
      .slice(0, 15)
      .map(s => ({
        symbol: s.symbol,
        direction: s.direction,
        confidence: s.confidence,
        regime: s.regime,
        drift_status: s.drift_status,
        rsi: s.rsi,
        crisis_level: s.crisis_level,
        source: s.source,
        timestamp: s.timestamp,
      }))

    const avgConf = allSignals.length
      ? allSignals.reduce((sum, s) => sum + (typeof s.confidence === 'number' ? s.confidence : 0), 0) / allSignals.length
      : 0

    // Parse genomes
    const genomes: Record<string, unknown>[] = []
    for (let i = 0; i < Math.min(genomeKeys.length, 20); i++) {
      const g = safeJson(results?.[genOffset + i]?.[1] as string | null) as Record<string, unknown> | null
      if (g) genomes.push(g)
    }

    // Sample context
    const sampleContexts: Record<string, unknown>[] = []
    for (let i = 0; i < Math.min(contextKeys.length, 5); i++) {
      const c = safeJson(results?.[ctxOffset + i]?.[1] as string | null) as Record<string, unknown> | null
      if (c) {
        const sym = (contextKeys[i] as string).replace('context:latest:', '')
        sampleContexts.push({ symbol: sym, ...c })
      }
    }

    // Sample agent verdicts
    const sampleVerdicts: Record<string, unknown>[] = []
    for (let i = 0; i < Math.min(agentKeys.length, 3); i++) {
      const raw = results?.[agentOffset + i]?.[1] as string | null
      const verdicts = safeJson(raw)
      if (verdicts) {
        const sym = (agentKeys[i] as string).replace('agents:verdicts:', '')
        sampleVerdicts.push({ symbol: sym, verdicts })
      }
    }

    const wsStatus = safeJson(results?.[staticOffset]?.[1] as string | null)
    const vixRaw = safeJson(results?.[staticOffset + 1]?.[1] as string | null) as Record<string, unknown> | null
    const shadowRaw = safeJson(results?.[staticOffset + 2]?.[1] as string | null)
    const fearGreedRaw = safeJson(results?.[staticOffset + 3]?.[1] as string | null) as Record<string, unknown> | null

    // Crisis level: get from most common in sample contexts
    const crisisFromCtx = sampleContexts.find(c => typeof c.crisis_level === 'number')?.crisis_level
    const crisisFromSig = allSignals.find(s => typeof s.crisis_level === 'number')?.crisis_level
    const crisis = (crisisFromCtx ?? crisisFromSig ?? 0) as number

    // Qdrant memory analysis
    type MemPoint = { payload?: { was_winner?: boolean; symbol?: string; regime?: string; error_category?: string; pnl_pct?: number; time?: number; drift_at_entry?: string; confidence?: number } }
    const memPoints = memories as MemPoint[]
    const wins = memPoints.filter(m => m.payload?.was_winner === true)
    const losses = memPoints.filter(m => m.payload?.was_winner === false)
    const totalMemories = (collectionInfo as { points_count?: number } | null)?.points_count ?? memories.length

    const errorCategories: Record<string, number> = {}
    const winRegimes: Record<string, number> = {}
    const topSymbols: Record<string, { wins: number; losses: number }> = {}

    for (const m of memPoints) {
      const p = m.payload ?? {}
      if (p.error_category) errorCategories[p.error_category] = (errorCategories[p.error_category] ?? 0) + 1
      if (p.was_winner && p.regime) winRegimes[p.regime] = (winRegimes[p.regime] ?? 0) + 1
      if (p.symbol) {
        if (!topSymbols[p.symbol]) topSymbols[p.symbol] = { wins: 0, losses: 0 }
        if (p.was_winner) topSymbols[p.symbol].wins++
        else topSymbols[p.symbol].losses++
      }
    }

    // Genome stats
    const bestFitness = genomes.reduce((b, g) => Math.max(b, typeof g.fitness === 'number' ? g.fitness : 0), 0)
    const avgFitness = genomes.length
      ? genomes.reduce((s, g) => s + (typeof g.fitness === 'number' ? g.fitness : 0), 0) / genomes.length
      : 0

    const topRegime = Object.entries(regimeCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null

    return NextResponse.json({
      // Live monitoring
      activity,
      active_signals: activeSignals,
      signal_summary: {
        total: allSignals.length,
        long: directionCounts.long,
        short: directionCounts.short,
        flat: directionCounts.flat,
        avg_confidence: avgConf,
        tracked_symbols: signalKeys.length,
        context_symbols: contextKeys.length,
        agent_symbols: agentKeys.length,
      },
      drift_summary: driftCounts,
      ws_status: wsStatus,
      shadow_leaderboard: Array.isArray(shadowRaw) ? shadowRaw : [],
      fear_greed: fearGreedRaw,
      // Memory
      memories: memPoints.map(m => m.payload ?? {}),
      total_memories: totalMemories,
      win_count: wins.length,
      loss_count: losses.length,
      error_categories: errorCategories,
      win_regimes: winRegimes,
      top_symbols: Object.entries(topSymbols)
        .sort((a, b) => (b[1].wins + b[1].losses) - (a[1].wins + a[1].losses))
        .slice(0, 10)
        .map(([sym, stats]) => ({ symbol: sym, ...stats })),
      genomes: { count: genomes.length, best_fitness: bestFitness, avg_fitness: avgFitness, sample: genomes.slice(0, 5) },
      current_state: {
        direction_dist: directionCounts,
        regime_dist: regimeCounts,
        regime: topRegime,
        crisis_level: crisis,
        vix: typeof vixRaw?.value === 'number' ? vixRaw.value : null,
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
