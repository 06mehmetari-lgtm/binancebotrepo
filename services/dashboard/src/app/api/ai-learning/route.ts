import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

function safeJson(raw: unknown): unknown {
  if (!raw || typeof raw !== 'string') return null
  try { return JSON.parse(raw) } catch { return null }
}

export async function GET() {
  const redis = createRedis()
  try {
    // Sample up to 50 signal keys for direction distribution
    const sigKeys = await redis.keys('signal:latest:*')
    const sampleKeys = sigKeys.slice(0, 50)

    const pipeline = redis.pipeline()
    pipeline.get('agents:weights')         // 0
    pipeline.get('agents:last_run')        // 1
    pipeline.lrange('neat:evolution_log', 0, 19)  // 2
    pipeline.lrange('activity:feed', 0, 99)        // 3
    pipeline.get('agents:verdicts:BTCUSDT')        // 4
    pipeline.get('agents:verdicts:ETHUSDT')        // 5
    pipeline.get('ml:learner:stats')               // 6
    pipeline.get('agents:learned_weights')         // 7
    pipeline.get('rl:model_ready')                 // 8
    sampleKeys.forEach(k => pipeline.get(k))       // 9+
    const res = await pipeline.exec()

    const weights = (safeJson(res?.[0]?.[1]) as Record<string, number> | null) ?? {
      technical: 1.0, onchain: 1.2, sentiment: 0.8,
      macro: 0.9, news: 0.8, bull: 1.0, bear: 1.0, neutral: 0.7, risk: 1.1,
    }

    const lastRunRaw = res?.[1]?.[1] as string | null
    const lastRunSec = lastRunRaw
      ? Math.floor(Date.now() / 1000 - parseFloat(lastRunRaw))
      : null

    const evoLog = ((res?.[2]?.[1] as string[] | null) ?? [])
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean) as Record<string, unknown>[]

    const actLog = ((res?.[3]?.[1] as string[] | null) ?? [])
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean) as Record<string, unknown>[]

    // Sample vote breakdown from BTC/ETH
    const btcVotes = (safeJson(res?.[4]?.[1]) as Record<string, unknown>[] | null) ?? []
    const ethVotes = (safeJson(res?.[5]?.[1]) as Record<string, unknown>[] | null) ?? []
    const sampleVotes = btcVotes.length > 0 ? btcVotes : ethVotes

    const mlStats   = safeJson(res?.[6]?.[1]) as Record<string, unknown> | null
    const learnedW  = safeJson(res?.[7]?.[1]) as Record<string, number> | null
    const rlActive  = !!(res?.[8]?.[1])

    // Direction distribution across sampled signals
    const dist = { long: 0, short: 0, flat: 0, total: 0 }
    const recentSignals: { symbol: string; direction: string; confidence: number; regime: string; ml_score?: number }[] = []

    for (let i = 0; i < sampleKeys.length; i++) {
      const raw = res?.[9 + i]?.[1]
      const sig = safeJson(raw) as Record<string, unknown> | null
      if (!sig) continue
      const dir = (sig.direction as string) || 'flat'
      dist.total++
      if (dir === 'long') dist.long++
      else if (dir === 'short') dist.short++
      else dist.flat++

      if (dir !== 'flat' && recentSignals.length < 20) {
        recentSignals.push({
          symbol: String(sig.symbol ?? sampleKeys[i].replace('signal:latest:', '')),
          direction: dir,
          confidence: Number(sig.confidence ?? 0),
          regime: String(sig.regime ?? 'unknown'),
          ml_score: Number(sig.ml_score ?? 0),
        })
      }
    }

    const longPct  = dist.total > 0 ? Math.round(dist.long  / dist.total * 100) : 0
    const shortPct = dist.total > 0 ? Math.round(dist.short / dist.total * 100) : 0
    const flatPct  = dist.total > 0 ? Math.round(dist.flat  / dist.total * 100) : 0

    // Agent name labels
    const agentLabels: Record<string, string> = {
      technical: '📊 Teknik', onchain: '⛓ Zincir', sentiment: '😨 Duygu',
      macro: '🌍 Makro', news: '📰 Haber', bull: '🐂 Boğa',
      bear: '🐻 Ayı', neutral: '⚖ Nötr', risk: '🛡 Risk', rl_ppo: '🤖 RL/PPO',
    }

    // Merge regime weights with learned accuracy weights for display
    const displayWeights = learnedW
      ? { ...weights, ...Object.fromEntries(Object.entries(learnedW).filter(([k]) => k in weights)) }
      : weights

    return NextResponse.json({
      signal_distribution: { long: longPct, short: shortPct, flat: flatPct, total: dist.total },
      recent_signals: recentSignals.sort((a, b) => b.confidence - a.confidence),
      agent_weights: Object.entries(displayWeights).map(([name, w]) => ({
        name, label: agentLabels[name] ?? name, weight: Number(w) || 1.0,
      })).sort((a, b) => b.weight - a.weight),
      sample_votes: sampleVotes.map((v: Record<string, unknown>) => ({
        agent: String(v.agent ?? v.agent_name ?? ''),
        signal: String(v.signal ?? v.direction ?? 'flat'),
        confidence: Number(v.confidence ?? 0),
      })),
      ml_model: mlStats ? {
        version:      Number(mlStats.version ?? 0),
        n_samples:    Number(mlStats.n_samples ?? 0),
        val_accuracy: Number(mlStats.val_accuracy ?? 0),
        top_features: (mlStats.top_features as [string, number][] | null) ?? [],
        label_dist:   (mlStats.label_dist as Record<string, number> | null) ?? {},
      } : null,
      rl_active:    rlActive,
      last_run_sec: lastRunSec,
      neat_log: evoLog.slice(0, 10),
      activity_log: actLog,
      sampled_symbols: dist.total,
      server_time: Date.now(),
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
