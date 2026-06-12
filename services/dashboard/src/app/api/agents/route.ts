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

export async function GET(req: Request) {
  const redis = createRedis()
  try {
    const { searchParams } = new URL(req.url)
    const symbol = searchParams.get('symbol') || 'BTCUSDT'

    const pipeline = redis.pipeline()
    pipeline.get(`agents:verdicts:${symbol}`)
    pipeline.get(`agents:verdict:${symbol}`)
    pipeline.get(`neat:best_genome:${symbol}`)
    pipeline.get(`oms:position:${symbol}`)
    pipeline.get('portfolio:state:v1')
    pipeline.get(`signal:latest:${symbol}`)
    pipeline.get(`learn:profile:${symbol}`)
    pipeline.get('learn:global:v1')
    pipeline.get('system:risk_limits:v1')
    const results = await pipeline.exec()

    const votesRaw = (safeJson(results?.[0]?.[1] as string | null) ?? []) as Array<Record<string, unknown>>
    const verdictRaw = safeJson(results?.[1]?.[1] as string | null) as Record<string, unknown> | null
    const genome = safeJson(results?.[2]?.[1] as string | null) ?? null
    const openPosition = safeJson(results?.[3]?.[1] as string | null)
    const portfolioState = safeJson(results?.[4]?.[1] as string | null) as Record<string, unknown> | null
    const liveSignal = safeJson(results?.[5]?.[1] as string | null) as Record<string, unknown> | null
    const learnProfile = safeJson(results?.[6]?.[1] as string | null)
    const learnGlobal = safeJson(results?.[7]?.[1] as string | null)
    const riskLimitsRaw = safeJson(results?.[8]?.[1] as string | null) as Record<string, unknown> | null

    const votes = Array.isArray(votesRaw)
      ? votesRaw.map(v => ({
          ...v,
          agent: String(v.agent ?? '').endsWith('_agent') ? v.agent : `${v.agent}_agent`,
          reasoning: v.reasoning ?? '',
        }))
      : []

    const verdict = verdictRaw
      ? {
          ...verdictRaw,
          direction: verdictRaw.direction ?? verdictRaw.final_signal ?? 'flat',
          consensus_reasoning: verdictRaw.consensus_reasoning ?? verdictRaw.reasoning ?? '',
          dissent_risk: verdictRaw.dissent_risk ?? '',
        }
      : null

    return NextResponse.json({
      symbol,
      votes,
      verdict,
      genome,
      open_position: openPosition,
      portfolio: portfolioState
        ? {
            total_open: portfolioState.total_open,
            long_positions: portfolioState.long_positions,
            short_positions: portfolioState.short_positions,
          }
        : null,
      live_signal: liveSignal
        ? {
            direction: liveSignal.direction,
            confidence: liveSignal.confidence,
            trade_action: liveSignal.trade_action,
            has_position: liveSignal.has_position,
            crisis_level: Number(liveSignal.crisis_level ?? 0),
            drift_status: String(liveSignal.drift_status ?? 'STABLE'),
            kelly_fraction: Number(liveSignal.kelly_fraction ?? 0),
            regime: liveSignal.regime,
          }
        : null,
      risk_context: {
        crisis_level: Number(liveSignal?.crisis_level ?? 0),
        drift_status: String(liveSignal?.drift_status ?? 'STABLE'),
        kelly_fraction: Number(liveSignal?.kelly_fraction ?? 0),
        max_position_pct: Number(riskLimitsRaw?.max_position_pct ?? 0.05),
      },
      learn_profile: learnProfile,
      learn_global: learnGlobal,
    })
  } catch (e) {
    return NextResponse.json({ symbol: 'BTCUSDT', votes: [], verdict: null, genome: null }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
