import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols, getUniverseSnapshot, scanKeys } from '@/lib/universe'
import { fetchOpenPositions } from '@/lib/positions'

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

type LessonRow = {
  symbol: string
  text: string
  source: string
  ts: number
  category?: string
  was_winner?: boolean
}

export async function GET() {
  const redis = createRedis()
  try {
    const symbols = await discoverSymbols(redis)
    const snap = await getUniverseSnapshot<{
      counts?: Record<string, number>
      updated_at?: number
    }>(redis)

    const [
      memories,
      collectionInfo,
      activityRaw,
      learnGlobalRaw,
      portfolioRaw,
      backtestLogRaw,
    ] = await Promise.all([
      getTradeMemories(30),
      getCollectionInfo(),
      redis.lrange('activity:feed', 0, 79),
      redis.get('learn:global:v1'),
      redis.get('portfolio:state:v1'),
      redis.lrange('backtest:log', 0, 49),
    ])

    const learnProfileKeys = await scanKeys(redis, 'learn:profile:*')

    const pipeline = redis.pipeline()
    const symBatch = symbols.slice(0, 200)
    for (const sym of symBatch) {
      pipeline.get(`signal:latest:${sym}`)
    }
    for (const key of learnProfileKeys.slice(0, 40)) {
      pipeline.get(key)
    }
    for (const sym of symBatch.slice(0, 40)) {
      pipeline.lrange(`trade:lessons:${sym}`, 0, 4)
    }
    pipeline.get('ws:status')
    pipeline.get('macro:vix')
    pipeline.get('shadow:leaderboard')
    pipeline.get('sentiment:fear_greed')
    pipeline.get('system:heartbeat:signal_engine')
    pipeline.get('system:heartbeat:learning_engine')
    pipeline.get('snapshot:universe:v1')
    pipeline.get('ingestion:symbols')

    const results = await pipeline.exec()
    const sigEnd = symBatch.length
    const profEnd = sigEnd + Math.min(learnProfileKeys.length, 40)
    const lessonsEnd = profEnd + Math.min(symBatch.length, 40)
    let off = lessonsEnd

    const allSignals: Record<string, unknown>[] = []
    const directionCounts = { long: 0, short: 0, flat: 0 }
    let closeActions = 0
    let holdActions = 0
    const regimeCounts: Record<string, number> = {}
    const driftCounts: Record<string, number> = {}

    for (let i = 0; i < symBatch.length; i++) {
      const s = safeJson(results?.[i]?.[1] as string | null) as Record<string, unknown> | null
      if (!s) continue
      allSignals.push({ ...s, symbol: s.symbol ?? symBatch[i] })
      const dir = (s.direction as string) || 'flat'
      if (dir === 'long') directionCounts.long++
      else if (dir === 'short') directionCounts.short++
      else directionCounts.flat++
      if (s.trade_action === 'close') closeActions++
      if (s.trade_action === 'hold') holdActions++
      const regime = s.regime as string
      if (regime) regimeCounts[regime] = (regimeCounts[regime] ?? 0) + 1
      const drift = s.drift_status as string
      if (drift) driftCounts[drift] = (driftCounts[drift] ?? 0) + 1
    }

    if (snap?.counts) {
      directionCounts.long = snap.counts.long ?? directionCounts.long
      directionCounts.short = snap.counts.short ?? directionCounts.short
      directionCounts.flat = snap.counts.flat ?? directionCounts.flat
      closeActions = snap.counts.close_actions ?? closeActions
      holdActions = snap.counts.hold_actions ?? holdActions
    }

    const learnProfiles: Record<string, unknown>[] = []
    for (let i = 0; i < Math.min(learnProfileKeys.length, 40); i++) {
      const p = safeJson(results?.[sigEnd + i]?.[1] as string | null) as Record<string, unknown> | null
      if (p) {
        const sym = (learnProfileKeys[i] as string).replace('learn:profile:', '')
        learnProfiles.push({ symbol: sym, ...p })
      }
    }
    learnProfiles.sort((a, b) => {
      const stageOrder: Record<string, number> = { L3: 4, L2: 3, L1: 2, L0: 1 }
      const sa = stageOrder[String(a.learning_stage ?? 'L0')] ?? 0
      const sb = stageOrder[String(b.learning_stage ?? 'L0')] ?? 0
      if (sb !== sa) return sb - sa
      return (b.depth_score as number) - (a.depth_score as number)
    })

    const learningLessons: LessonRow[] = []
    for (let i = 0; i < Math.min(symBatch.length, 40); i++) {
      const sym = symBatch[i]
      const rows = (results?.[profEnd + i]?.[1] as string[] | null) ?? []
      for (const r of rows) {
        const d = safeJson(r) as Record<string, unknown> | null
        if (!d) continue
        learningLessons.push({
          symbol: sym,
          text: String(d.text ?? d.error_category ?? ''),
          source: String(d.source ?? 'unknown'),
          ts: Number(d.ts ?? d.time ?? 0),
          category: String(d.error_category ?? ''),
          was_winner: Boolean(d.was_winner),
        })
      }
    }
    learningLessons.sort((a, b) => b.ts - a.ts)
    const seenLesson = new Set<string>()
    const uniqueLessons = learningLessons.filter(l => {
      const key = `${l.symbol}:${l.text.slice(0, 80)}`
      if (seenLesson.has(key)) return false
      seenLesson.add(key)
      return true
    })

    const activeSignals = allSignals
      .filter(s => s.direction !== 'flat' || s.trade_action === 'close' || s.trade_action === 'hold')
      .sort((a, b) => (b.confidence as number) - (a.confidence as number))
      .slice(0, 20)
      .map(s => ({
        symbol: s.symbol,
        direction: s.direction,
        confidence: s.confidence,
        regime: s.regime,
        drift_status: s.drift_status,
        rsi: s.rsi,
        crisis_level: s.crisis_level,
        source: s.source,
        trade_action: s.trade_action,
        timestamp: s.timestamp,
      }))

    const avgConf = allSignals.length
      ? allSignals.reduce((sum, s) => sum + (typeof s.confidence === 'number' ? s.confidence : 0), 0) / allSignals.length
      : 0

    const activity = activityRaw
      .map(r => { try { return JSON.parse(r as string) } catch { return null } })
      .filter(Boolean)

    const wsStatus = safeJson(results?.[off]?.[1] as string | null); off++
    const vixRaw = safeJson(results?.[off]?.[1] as string | null) as Record<string, unknown> | null; off++
    const shadowRaw = safeJson(results?.[off]?.[1] as string | null); off++
    const fearGreedRaw = safeJson(results?.[off]?.[1] as string | null); off++
    const hbSignal = results?.[off]?.[1] as string | null; off++
    const hbLearn = results?.[off]?.[1] as string | null; off++
    const snapRaw = safeJson(results?.[off]?.[1] as string | null); off++
    const ingestionRaw = safeJson(results?.[off]?.[1] as string | null) as { count?: number; symbols?: string[] } | null

    const learnGlobal = safeJson(learnGlobalRaw) as Record<string, unknown> | null

    const { positions: openPositions, portfolio: portfolioState } = await fetchOpenPositions(redis)

    const backtestLogs = backtestLogRaw
      .map(r => { try { return JSON.parse(r as string) } catch { return null } })
      .filter(Boolean)

    const now = Date.now() / 1000
    const services = [
      { name: 'signal_engine', hb: hbSignal, ok: hbSignal && now - parseFloat(hbSignal) < 30 },
      { name: 'learning_engine', hb: hbLearn, ok: hbLearn && now - parseFloat(hbLearn) < 30 },
      { name: 'data_ingestion', ok: wsStatus && (wsStatus as { status?: string }).status === 'CONNECTED' },
    ]

    type MemPoint = { payload?: Record<string, unknown> }
    const memPoints = memories as MemPoint[]
    const wins = memPoints.filter(m => m.payload?.was_winner === true)
    const losses = memPoints.filter(m => m.payload?.was_winner === false)
    const totalMemories = (collectionInfo as { points_count?: number } | null)?.points_count ?? memories.length

    const errorCategories: Record<string, number> = {}
    const winRegimes: Record<string, number> = {}
    const topSymbols: Record<string, { wins: number; losses: number }> = {}

    for (const m of memPoints) {
      const p = m.payload ?? {}
      if (p.error_category) errorCategories[String(p.error_category)] = (errorCategories[String(p.error_category)] ?? 0) + 1
      if (p.was_winner && p.regime) winRegimes[String(p.regime)] = (winRegimes[String(p.regime)] ?? 0) + 1
      if (p.symbol) {
        const sym = String(p.symbol)
        if (!topSymbols[sym]) topSymbols[sym] = { wins: 0, losses: 0 }
        if (p.was_winner) topSymbols[sym].wins++
        else topSymbols[sym].losses++
      }
    }

    const topRegime = Object.entries(regimeCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
    const tracked = ingestionRaw?.count ?? symbols.length

    type ActiveRow = Record<string, unknown>
    const activeBySymbol = new Map<string, ActiveRow>(
      activeSignals.map(s => [String(s.symbol), s as ActiveRow])
    )
    for (const pos of openPositions) {
      if (!activeBySymbol.has(pos.symbol)) {
        const entry = pos.entry_signal ?? {}
        activeBySymbol.set(pos.symbol, {
          symbol: pos.symbol,
          direction: pos.direction,
          confidence: Number(entry.confidence ?? pos.verdict?.confidence ?? 0),
          regime: entry.regime,
          drift_status: entry.drift_status ?? pos.current_signal?.drift_status,
          crisis_level: entry.crisis_level,
          source: String(entry.source ?? 'open_position'),
          trade_action: pos.trade_action ?? 'hold',
          open_reason: pos.open_reason,
        })
      }
    }
    const mergedActive = Array.from(activeBySymbol.values()).sort(
      (a, b) => (b.confidence as number) - (a.confidence as number)
    )

    const positionLong = portfolioState.long_positions
    const positionShort = portfolioState.short_positions

    const neatKeys = await scanKeys(redis, 'neat:best_genome:*')
    const neatSample: { symbol: string; fitness: number }[] = []
    let bestFitness = 0
    let fitnessSum = 0
    let fitnessCount = 0
    if (neatKeys.length) {
      const neatPipe = redis.pipeline()
      for (const k of neatKeys.slice(0, 50)) neatPipe.get(k)
      const neatRes = await neatPipe.exec()
      for (let i = 0; i < neatKeys.length && i < 50; i++) {
        const g = safeJson(neatRes?.[i]?.[1] as string | null) as { fitness?: number; symbol?: string } | null
        if (!g) continue
        const fit = Number(g.fitness ?? 0)
        const sym = String(g.symbol ?? neatKeys[i].split(':').pop() ?? '')
        if (fit > 0) {
          fitnessSum += fit
          fitnessCount++
          if (fit > bestFitness) bestFitness = fit
        }
        neatSample.push({ symbol: sym, fitness: fit })
      }
      neatSample.sort((a, b) => b.fitness - a.fitness)
    }

    return NextResponse.json({
      activity,
      active_signals: mergedActive.slice(0, 25),
      open_positions: openPositions,
      signal_summary: {
        total: allSignals.length,
        long: directionCounts.long,
        short: directionCounts.short,
        flat: directionCounts.flat,
        close_actions: closeActions,
        hold_actions: holdActions,
        avg_confidence: avgConf,
        tracked_symbols: tracked,
        context_symbols: symbols.length,
        agent_symbols: learnProfileKeys.length,
        open_positions: portfolioState.total_open,
        position_long: positionLong,
        position_short: positionShort,
        snapshot_at: snap?.updated_at ?? (snapRaw as { updated_at?: number })?.updated_at ?? null,
      },
      drift_summary: driftCounts,
      ws_status: wsStatus,
      shadow_leaderboard: Array.isArray(shadowRaw) ? shadowRaw : [],
      fear_greed: fearGreedRaw,
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
      genomes: {
        count: neatKeys.length,
        learn_profiles: learnProfileKeys.length,
        best_fitness: +bestFitness.toFixed(4),
        avg_fitness: fitnessCount ? +(fitnessSum / fitnessCount).toFixed(4) : 0,
        sample: neatSample.slice(0, 12),
      },
      current_state: {
        direction_dist: directionCounts,
        regime_dist: regimeCounts,
        regime: topRegime,
        crisis_level: 0,
        vix: typeof vixRaw?.value === 'number' ? vixRaw.value : null,
      },
      learning: {
        global: learnGlobal,
        profiles: learnProfiles.slice(0, 25),
        profiles_count: learnProfileKeys.length,
        recent_lessons: uniqueLessons.slice(0, 40),
        backtest_log: backtestLogs.slice(0, 20),
        engine_active: Boolean(hbLearn && now - parseFloat(hbLearn) < 60),
        last_heartbeat: hbLearn ? parseFloat(hbLearn) : null,
      },
      portfolio: portfolioState,
      services,
      scanning: {
        active: Boolean(hbSignal && now - parseFloat(hbSignal) < 15),
        last_scan: hbSignal ? parseFloat(hbSignal) : snap?.updated_at ?? null,
        universe_size: tracked,
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
