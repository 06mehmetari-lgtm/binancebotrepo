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
    const results = await pipeline.exec()

    const votesRaw = (safeJson(results?.[0]?.[1] as string | null) ?? []) as Array<Record<string, unknown>>
    const verdictRaw = safeJson(results?.[1]?.[1] as string | null) as Record<string, unknown> | null
    const genome = safeJson(results?.[2]?.[1] as string | null) ?? null

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

    return NextResponse.json({ symbol, votes, verdict, genome })
  } catch (e) {
    return NextResponse.json({ symbol: 'BTCUSDT', votes: [], verdict: null, genome: null }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
