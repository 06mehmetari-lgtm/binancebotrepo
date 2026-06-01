import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

function safeJson(raw: unknown): unknown {
  if (!raw || typeof raw !== 'string') return null
  try { return JSON.parse(raw) } catch { return null }
}

function secAgo(ts: number | null | undefined): number | null {
  if (!ts) return null
  const t = ts > 1e12 ? ts / 1000 : ts
  return Math.floor(Date.now() / 1000 - t)
}

type SvcStatus = 'ok' | 'warn' | 'error' | 'unknown'
interface SvcInfo { name: string; label: string; status: SvcStatus; detail: string }

export async function GET() {
  const redis = createRedis()
  try {
    const [featureKeys, signalKeys, agentKeys, contextKeys, genomeKeys, posKeys] = await Promise.all([
      redis.keys('features:latest:*'),
      redis.keys('signal:latest:*'),
      redis.keys('agents:verdicts:*'),
      redis.keys('context:latest:*'),
      redis.keys('neat:best_genome:*'),
      redis.keys('oms:position:*'),
    ])

    const pipeline = redis.pipeline()
    pipeline.get('ws:status')            // 0
    pipeline.get('neat:stats')           // 1
    pipeline.get('agents:last_run')      // 2
    pipeline.get('shadow:leaderboard')   // 3
    pipeline.get('sentiment:fear_greed') // 4
    pipeline.get('macro:vix')            // 5
    pipeline.get('immunity:status')      // 6
    pipeline.get('immunity:daily_loss')  // 7
    pipeline.get('context:regime')       // 8
    pipeline.get('context:crisis_level') // 9
    pipeline.lrange('activity:feed', 0, 19) // 10
    pipeline.lrange('oms:trade_history', 0, 4) // 11
    pipeline.get('oms:daily_pnl')        // 12
    pipeline.get('rl:model_ready')       // 13 — RL agent status
    pipeline.get('ml:learner:stats')     // 14 — ML model version + accuracy
    pipeline.get('ml:model:version')     // 15 — current model version number
    if (signalKeys.length > 0) pipeline.get(signalKeys[0])   // 16
    if (featureKeys.length > 0) pipeline.get(featureKeys[0]) // 17
    if (genomeKeys.length > 0) pipeline.get(genomeKeys[0])   // 18
    const results = await pipeline.exec()

    const wsRaw       = safeJson(results?.[0]?.[1]) as Record<string, unknown> | null
    const neatRaw     = safeJson(results?.[1]?.[1]) as Record<string, unknown> | null
    const agentsLast = results?.[2]?.[1] as string | null
    const shadowRaw  = safeJson(results?.[3]?.[1])
    const fearGreed  = safeJson(results?.[4]?.[1]) as Record<string, unknown> | null
    const vixRaw     = safeJson(results?.[5]?.[1]) as Record<string, unknown> | null
    const immunity   = safeJson(results?.[6]?.[1]) as Record<string, unknown> | null
    const dailyLoss  = parseFloat((results?.[7]?.[1] as string | null) ?? '0') || 0
    const regime     = results?.[8]?.[1] as string | null
    const crisisLvl  = parseInt((results?.[9]?.[1] as string | null) ?? '0') || 0
    const actRaw     = (results?.[10]?.[1] as string[] | null) ?? []
    const tradesRaw  = (results?.[11]?.[1] as string[] | null) ?? []
    const dailyPnl    = parseFloat((results?.[12]?.[1] as string | null) ?? '0') || 0
    const rlReady     = results?.[13]?.[1] as string | null
    const mlStatsRaw  = safeJson(results?.[14]?.[1]) as Record<string, unknown> | null
    const mlVersion   = parseInt((results?.[15]?.[1] as string | null) ?? '0') || 0

    let sigFresh: number | null = null
    let featFresh: number | null = null
    let bestGenome: Record<string, unknown> | null = null
    let idx = 16
    if (signalKeys.length > 0) {
      const s = safeJson(results?.[idx++]?.[1]) as Record<string, unknown> | null
      sigFresh = secAgo(s?.timestamp as number | undefined)
    }
    if (featureKeys.length > 0) {
      const f = safeJson(results?.[idx++]?.[1]) as Record<string, unknown> | null
      featFresh = secAgo(f?.timestamp as number | undefined)
    }
    if (genomeKeys.length > 0) {
      bestGenome = safeJson(results?.[idx++]?.[1]) as Record<string, unknown> | null
    }

    const agentLastSec = agentsLast ? secAgo(parseFloat(agentsLast)) : null
    const activity = actRaw.map(r => { try { return JSON.parse(r) } catch { return null } }).filter(Boolean)
    const recentTrades = tradesRaw.map(r => { try { return JSON.parse(r) } catch { return null } }).filter(Boolean)
    const shadowList = Array.isArray(shadowRaw) ? shadowRaw as Record<string, unknown>[] : []
    const bestShadow = shadowList.length > 0
      ? shadowList.reduce((a, b) => (a.sharpe as number) > (b.sharpe as number) ? a : b)
      : null

    const isStale = (sec: number | null, thr = 300) => sec != null && sec > thr

    const services: Record<string, SvcInfo> = {
      data_ingestion: {
        name: 'data_ingestion', label: 'Data Ingestion',
        status: wsRaw?.status === 'CONNECTED' ? 'ok' : wsRaw ? 'warn' : 'unknown',
        detail: wsRaw ? `WS ${wsRaw.status} · ${wsRaw.symbols ?? 0} coin` : 'Bağlantı bilgisi yok',
      },
      feature_engine: {
        name: 'feature_engine', label: 'Feature Engine',
        status: featureKeys.length > 0 ? (isStale(featFresh) ? 'warn' : 'ok') : 'error',
        detail: `${featureKeys.length} özellik${featFresh != null ? ` · ${featFresh}s önce` : ''}`,
      },
      signal_engine: {
        name: 'signal_engine', label: 'Signal Engine',
        status: signalKeys.length > 0 ? (isStale(sigFresh) ? 'warn' : 'ok') : 'error',
        detail: `${signalKeys.length} sinyal${sigFresh != null ? ` · ${sigFresh}s önce` : ''}`,
      },
      context_engine: {
        name: 'context_engine', label: 'Context Engine',
        status: contextKeys.length > 0 ? 'ok' : 'error',
        detail: `${contextKeys.length} bağlam · ${regime ?? '—'}`,
      },
      agent_system: {
        name: 'agent_system', label: 'Agent System (AI)',
        status: agentLastSec != null ? (agentLastSec < 300 ? 'ok' : 'warn') : agentKeys.length > 0 ? 'warn' : 'unknown',
        detail: agentLastSec != null
          ? `${agentKeys.length} verdict · ${agentLastSec}s önce çalıştı`
          : `${agentKeys.length} verdict · son çalışma bilinmiyor`,
      },
      immunity_system: {
        name: 'immunity_system', label: 'Immunity System',
        status: immunity?.halted ? 'warn' : 'ok',
        detail: immunity?.halted ? '⚠ TRADING DURDU' : `Aktif · kayıp: $${dailyLoss.toFixed(2)}`,
      },
      oms: {
        name: 'oms', label: 'OMS (Order Manager)',
        status: 'ok',
        detail: `${posKeys.length} pozisyon · P&L: ${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`,
      },
      shadow_system: {
        name: 'shadow_system', label: 'Shadow System',
        status: shadowList.length > 0 ? 'ok' : 'warn',
        detail: shadowList.length > 0
          ? `${shadowList.length} strateji · Sharpe ${((bestShadow?.sharpe as number) ?? 0).toFixed(2)}`
          : '100 işlem tamamlanana kadar bekleniyor',
      },
      neat_evolution: {
        name: 'neat_evolution', label: 'NEAT Evolution',
        status: neatRaw ? 'ok' : genomeKeys.length > 0 ? 'ok' : 'warn',
        detail: neatRaw
          ? `Nesil ${neatRaw.generation ?? 0} · Fitness ${((neatRaw.best_fitness as number) ?? 0).toFixed(4)}`
          : genomeKeys.length > 0 ? `${genomeKeys.length} genom` : 'Evrim henüz başlamadı',
      },
      sentiment: {
        name: 'sentiment', label: 'Sentiment',
        status: fearGreed ? 'ok' : 'warn',
        detail: fearGreed
          ? `F&G: ${fearGreed.value} — ${fearGreed.classification}`
          : 'Sentiment verisi yok',
      },
      macro: {
        name: 'macro', label: 'Macro',
        status: vixRaw ? 'ok' : 'warn',
        detail: vixRaw
          ? `VIX: ${((vixRaw.value as number) ?? 0).toFixed(1)}${(vixRaw.value as number) > 40 ? ' ⚠ YÜKSEK' : ''}`
          : 'VIX verisi yok',
      },
      rl_agent: {
        name: 'rl_agent', label: 'RL Agent (PPO)',
        status: rlReady ? 'ok' : 'warn' as SvcStatus,
        detail: rlReady ? 'PPO modeli aktif · tahmin üretiyor' : 'Model eğitimi bekleniyor (5 dk)',
      },
    }

    const counts = Object.values(services).reduce(
      (a, s) => { a[s.status] = (a[s.status] ?? 0) + 1; return a },
      {} as Record<string, number>
    )
    const overall = (counts.error ?? 0) > 0 ? 'critical'
      : (counts.warn ?? 0) > 3 ? 'degraded'
      : 'healthy'

    return NextResponse.json({
      overall_status: overall,
      status_counts: counts,
      services,
      pipeline: {
        feature_count: featureKeys.length,
        signal_count:  signalKeys.length,
        agent_count:   agentKeys.length,
        context_count: contextKeys.length,
        signal_freshness_sec:  sigFresh,
        feature_freshness_sec: featFresh,
        ws_status: wsRaw,
      },
      ai_learning: {
        neat: neatRaw ? {
          generation:   (neatRaw.generation as number) ?? 0,
          best_fitness: (neatRaw.best_fitness as number) ?? 0,
          genome_count: (neatRaw.genome_count as number) ?? 0,
          species_count: (neatRaw.species_count as number) ?? 0,
        } : null,
        genome_count:       genomeKeys.length,
        best_genome:        bestGenome,
        agent_last_run_sec: agentLastSec,
        agent_verdict_count: agentKeys.length,
        shadow_best:  bestShadow,
        shadow_total: shadowList.length,
        ml_model: mlStatsRaw ? {
          version:      (mlStatsRaw.version as number) ?? mlVersion,
          n_samples:    (mlStatsRaw.n_samples as number) ?? 0,
          val_accuracy: (mlStatsRaw.val_accuracy as number) ?? 0,
          top_features: (mlStatsRaw.top_features as [string, number][] | null) ?? [],
        } : mlVersion > 0 ? { version: mlVersion, n_samples: 0, val_accuracy: 0, top_features: [] } : null,
        rl_active: !!rlReady,
      },
      market: {
        regime: regime ?? null,
        crisis_level: crisisLvl,
        fear_greed: fearGreed,
        vix: typeof vixRaw?.value === 'number' ? vixRaw.value : null,
      },
      positions: {
        open_count:       posKeys.length,
        daily_pnl:        dailyPnl,
        immunity_halted:  !!(immunity?.halted),
        recent_trades:    recentTrades,
      },
      activity: activity.slice(0, 20),
      server_time: Date.now(),
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
