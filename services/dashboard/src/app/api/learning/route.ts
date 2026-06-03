import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols, scanKeys } from '@/lib/universe'
import { fetchOpenPositions } from '@/lib/positions'
import { buildStrategyDocument, CURRICULUM } from '@/lib/learning-hub'

const QDRANT_URL = process.env.QDRANT_URL || 'http://qdrant:6333'
const OLLAMA_URL = process.env.OLLAMA_URL || 'http://ollama:11434'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

async function ollamaStatus() {
  try {
    const res = await fetch(`${OLLAMA_URL}/api/tags`, {
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}`, models: [] as string[] }
    const data = (await res.json()) as { models?: { name?: string }[] }
    return {
      ok: true,
      url: OLLAMA_URL,
      models: (data.models ?? []).map(m => m.name ?? '').filter(Boolean),
    }
  } catch (e) {
    return { ok: false, error: String(e), models: [] as string[] }
  }
}

async function qdrantInfo() {
  try {
    const res = await fetch(`${QDRANT_URL}/collections/trade_memories`, {
      signal: AbortSignal.timeout(3000),
    })
    if (!res.ok) return null
    const data = (await res.json()) as { result?: { points_count?: number; status?: string } }
    return data.result ?? null
  } catch {
    return null
  }
}

export async function GET(req: Request) {
  const redis = createRedis()
  const now = Date.now() / 1000
  try {
    const { searchParams } = new URL(req.url)
    const focusSymbol = (searchParams.get('symbol') ?? 'BTCUSDT').toUpperCase()

    const symbols = await discoverSymbols(redis)
    const { positions, portfolio } = await fetchOpenPositions(redis)

    const [
      learnGlobalRaw,
      hbLearn,
      hbAgents,
      hbSignal,
      hbFeatures,
      promotionRaw,
      shadowLbRaw,
      activityRaw,
      haltedRaw,
      backtestStatusRaw,
      backtestResultsRaw,
      wsRaw,
      vixRaw,
      fearRaw,
      immunityRaw,
      ollama,
      qdrant,
    ] = await Promise.all([
      redis.get('learn:global:v1'),
      redis.get('system:heartbeat:learning_engine'),
      redis.get('system:heartbeat:agent_system'),
      redis.get('system:heartbeat:signal_engine'),
      redis.get('system:heartbeat:feature_engine'),
      redis.get('system:promotion:status'),
      redis.get('shadow:leaderboard'),
      redis.lrange('activity:feed', 0, 99),
      redis.get('system:trading:halted'),
      redis.get('backtest:status'),
      redis.get('backtest:results'),
      redis.get('ws:status'),
      redis.get('macro:vix'),
      redis.get('sentiment:fear_greed'),
      redis.get('immunity:status'),
      ollamaStatus(),
      qdrantInfo(),
    ])

    const learnGlobal = safeJson(learnGlobalRaw) as Record<string, unknown> | null
    const promotion = (safeJson(promotionRaw) as Record<string, unknown>) ?? {}
    type ShadowEntry = { trades?: number; promotion_ready?: boolean; shadow_id?: string }
    const shadowParsed = safeJson(shadowLbRaw)
    const shadowLb: ShadowEntry[] = Array.isArray(shadowParsed)
      ? (shadowParsed as ShadowEntry[])
      : []
    const firstShadow = shadowLb[0]
    const immunity = safeJson(immunityRaw) as Record<string, unknown> | null

    const profileKeys = await scanKeys(redis, 'learn:profile:*')
    const pipeline = redis.pipeline()
    for (const key of profileKeys.slice(0, 120)) pipeline.get(key)
    pipeline.get(`learn:profile:${focusSymbol}`)
    pipeline.get(`signal:latest:${focusSymbol}`)
    pipeline.get(`agents:verdict:${focusSymbol}`)
    pipeline.get(`features:latest:${focusSymbol}`)
    pipeline.get(`context:latest:${focusSymbol}`)
    pipeline.lrange(`trade:lessons:${focusSymbol}`, 0, 19)
    pipeline.get('backtest:log')
    const exec = await pipeline.exec()

    const profiles: Record<string, unknown>[] = []
    const nProf = Math.min(profileKeys.length, 120)
    for (let i = 0; i < nProf; i++) {
      const p = safeJson(exec?.[i]?.[1] as string | null) as Record<string, unknown> | null
      if (p?.symbol) profiles.push(p)
    }
    profiles.sort((a, b) => {
      const sa = String(a.learning_stage ?? 'L0')
      const sb = String(b.learning_stage ?? 'L0')
      if (sa !== sb) return sb.localeCompare(sa)
      return Number(b.updates ?? 0) - Number(a.updates ?? 0)
    })

    const off = nProf
    const focusProfile = safeJson(exec?.[off]?.[1] as string | null)
    const focusSignal = safeJson(exec?.[off + 1]?.[1] as string | null)
    const focusVerdict = safeJson(exec?.[off + 2]?.[1] as string | null)
    const focusFeatures = safeJson(exec?.[off + 3]?.[1] as string | null)
    const focusContext = safeJson(exec?.[off + 4]?.[1] as string | null)
    const focusLessonsRaw = (exec?.[off + 5]?.[1] as string[]) ?? []

    const allLessons: { symbol: string; text: string; ts: number; source?: string }[] = []
    for (const sym of symbols.slice(0, 60)) {
      const rows = await redis.lrange(`trade:lessons:${sym}`, 0, 2)
      for (const row of rows) {
        const les = safeJson(row) as { text?: string; ts?: number; source?: string } | null
        if (les?.text) {
          allLessons.push({
            symbol: sym,
            text: les.text,
            ts: Number(les.ts ?? 0),
            source: les.source,
          })
        }
      }
    }
    allLessons.sort((a, b) => b.ts - a.ts)

    const activity = activityRaw
      .map(r => safeJson(r))
      .filter(Boolean) as Record<string, unknown>[]

    const services = [
      { name: 'data_ingestion', key: 'ws:status', hb: null as string | null },
      { name: 'feature_engine', key: 'system:heartbeat:feature_engine', hb: hbFeatures },
      { name: 'learning_engine', key: 'system:heartbeat:learning_engine', hb: hbLearn },
      { name: 'agent_system', key: 'system:heartbeat:agent_system', hb: hbAgents },
      { name: 'signal_engine', key: 'system:heartbeat:signal_engine', hb: hbSignal },
    ].map(s => {
      const ts = s.hb ? parseFloat(s.hb) : 0
      const alive = s.name === 'data_ingestion'
        ? (wsRaw ? (safeJson(wsRaw) as { status?: string })?.status === 'CONNECTED' : false)
        : ts > 0 && now - ts < 45
      return { ...s, last_ts: ts || null, alive, age_sec: ts ? Math.round(now - ts) : null }
    })

    const dryRun = process.env.DRY_RUN !== 'false'
    const groqConfigured = Boolean(process.env.GROQ_API_KEY?.trim())
    const strategyDoc = buildStrategyDocument({
      symbols_tracked: symbols.length,
      profiles_count: profileKeys.length,
      promotion: {
        approved: Boolean(promotion.approved),
        reason: (promotion.reason as string) ?? null,
      },
      dry_run: dryRun,
    })

    let halted = false
    if (haltedRaw) {
      try {
        halted = Boolean((JSON.parse(haltedRaw) as { halted?: boolean }).halted)
      } catch {
        halted = true
      }
    }

    return NextResponse.json({
      server_time: now,
      focus_symbol: focusSymbol,
      curriculum: CURRICULUM,
      strategy_document: strategyDoc,
      universe: { symbols_count: symbols.length, sample: symbols.slice(0, 30) },
      portfolio,
      open_positions: positions,
      learning: {
        engine_active: hbLearn ? now - parseFloat(hbLearn) < 45 : false,
        heartbeat: hbLearn ? parseFloat(hbLearn) : null,
        global: learnGlobal,
        profiles_count: profileKeys.length,
        profiles: profiles.slice(0, 80),
        recent_lessons: allLessons.slice(0, 40),
        focus: {
          profile: focusProfile,
          signal: focusSignal,
          verdict: focusVerdict,
          features: focusFeatures,
          context: focusContext,
          lessons: focusLessonsRaw.map(r => safeJson(r)).filter(Boolean),
        },
      },
      promotion: {
        approved: Boolean(promotion.approved),
        reason: promotion.reason ?? null,
        best_shadow_id: promotion.best_shadow_id ?? null,
        ready_count: promotion.ready_count ?? 0,
        leaderboard: shadowLb,
        criteria: [
          { label: 'Min trades', value: 100 },
          { label: 'Sharpe', value: 1.5 },
          { label: 'Win rate', value: '52%' },
          { label: 'Max drawdown', value: '10%' },
        ],
        live_steps: [
          {
            step: 1,
            text: 'Shadow SHADOW_A kriterleri sağlasın (100+ işlem)',
            done: (firstShadow?.trades ?? 0) >= 100,
          },
          {
            step: 2,
            text: 'Sharpe ≥ 1.5 ve WR ≥ 52%',
            done: Boolean(firstShadow?.promotion_ready),
          },
          { step: 3, text: 'system:promotion:status approved=true', done: Boolean(promotion.approved) },
          { step: 4, text: '.env DRY_RUN=false + LIVE_TRADING_CONFIRMED=true', done: false },
        ],
      },
      llm: {
        groq: { configured: groqConfigured, model: process.env.GROQ_LEARN_MODEL ?? 'llama-3.1-70b-versatile' },
        ollama,
        agent_model: 'Groq/Ollama + kural ajanları (debate)',
        learn_llm_every_n: Number(process.env.LEARNING_LLM_EVERY_N ?? 90),
      },
      pipeline: {
        services,
        activity: activity.slice(0, 50),
        ws: safeJson(wsRaw),
        trading_halted: halted,
        immunity,
      },
      macro: {
        vix: safeJson(vixRaw),
        fear_greed: safeJson(fearRaw),
      },
      backtest: {
        status: safeJson(backtestStatusRaw),
        summary: (safeJson(backtestResultsRaw) as { summary?: unknown })?.summary ?? null,
      },
      qdrant: qdrant ?? { points_count: 0 },
      dry_run: dryRun,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
