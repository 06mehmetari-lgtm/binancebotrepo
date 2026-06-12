import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols, scanKeys } from '@/lib/universe'
import { PROMETHEUS_CONTAINERS } from '@/lib/system-health'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

const HB_SERVICES: { name: string; key: string }[] = [
  { name: 'data_ingestion', key: 'system:heartbeat:data_ingestion' },
  { name: 'feature_engine', key: 'system:heartbeat:feature_engine' },
  { name: 'context_engine', key: 'system:heartbeat:context_engine' },
  { name: 'learning_engine', key: 'system:heartbeat:learning_engine' },
  { name: 'agent_system', key: 'system:heartbeat:agent_system' },
  { name: 'signal_engine', key: 'system:heartbeat:signal_engine' },
  { name: 'shadow_system', key: 'system:heartbeat:shadow_system' },
  { name: 'immunity_system', key: 'system:heartbeat:immunity_system' },
  { name: 'oms', key: 'system:heartbeat:oms' },
]

const HB_ALIVE_SEC = 120
const HB_BOOTSTRAP_SEC = 300 // feature_engine ilk bootstrap

export async function GET() {
  const redis = createRedis()
  const now = Date.now() / 1000
  try {
    const symbols = await discoverSymbols(redis)
    const featCount = (await scanKeys(redis, 'features:latest:*')).length
    const sigCount = (await scanKeys(redis, 'signal:latest:*')).length
    const agtCount = (await scanKeys(redis, 'agents:verdict:*')).length
    const learnCount = (await scanKeys(redis, 'learn:profile:*')).length

    const [
      wsRaw,
      hbLearn,
      hbAgents,
      hbSignal,
      hbFeatures,
      immunityRaw,
      promotionRaw,
      haltedRaw,
      activityLen,
    ] = await Promise.all([
      redis.get('ws:status'),
      redis.get('system:heartbeat:learning_engine'),
      redis.get('system:heartbeat:agent_system'),
      redis.get('system:heartbeat:signal_engine'),
      redis.get('system:heartbeat:feature_engine'),
      redis.get('immunity:status'),
      redis.get('system:promotion:status'),
      redis.get('system:trading:halted'),
      redis.llen('activity:feed'),
    ])

    const hbChecks: Record<string, string | null> = {}
    for (const s of HB_SERVICES) {
      hbChecks[s.name] = await redis.get(s.key)
    }

    const services = HB_SERVICES.map(s => {
      const raw = hbChecks[s.name]
      let alive = false
      let age_sec: number | null = null
      if (raw) {
        const ts = parseFloat(raw)
        if (Number.isFinite(ts) && ts > 0) {
          age_sec = Math.round(now - ts)
          const limit = s.name === 'feature_engine' ? HB_BOOTSTRAP_SEC : HB_ALIVE_SEC
          alive = now - ts < limit
        }
      }
      if (!alive && s.name === 'feature_engine' && featCount > 50) {
        alive = true
        age_sec = age_sec ?? null
      }
      return { name: s.name, alive, age_sec, critical: true }
    })

    const containers = PROMETHEUS_CONTAINERS.map(c => ({
      ...c,
      status: services.find(s => s.name.replace('_', ' ') === c.label.toLowerCase())
        ? 'inferred'
        : 'check_host',
      running: services.some(s => s.name.includes(c.id.replace('prometheus_', '')) && s.alive),
      restarts: 0,
    }))

    const problems = services.filter(s => s.critical && !s.alive)

    let halted = false
    if (haltedRaw) {
      try {
        halted = Boolean((JSON.parse(haltedRaw) as { halted?: boolean }).halted)
      } catch {
        halted = true
      }
    }

    const pipeline_ok =
      featCount > 0 &&
      sigCount > 0 &&
      hbLearn &&
      now - parseFloat(hbLearn) < 60

    return NextResponse.json({
      server_time: now,
      services,
      problems: problems.map(p => ({ name: p.name, alive: p.alive })),
      containers,
      data_pipeline: {
        features: featCount,
        signals: sigCount,
        agent_verdicts: agtCount,
        learn_profiles: learnCount,
        symbols: symbols.length,
        activity_events: activityLen,
        ws: safeJson(wsRaw),
        heartbeats: {
          learning_engine: hbLearn ? parseFloat(hbLearn) : null,
          agent_system: hbAgents ? parseFloat(hbAgents) : null,
          signal_engine: hbSignal ? parseFloat(hbSignal) : null,
          feature_engine: hbFeatures ? parseFloat(hbFeatures) : null,
        },
        healthy: pipeline_ok,
      },
      immunity: safeJson(immunityRaw),
      promotion: safeJson(promotionRaw),
      trading_halted: halted,
      score: pipeline_ok && problems.length === 0 ? 100 : Math.max(0, 100 - problems.length * 8),
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
