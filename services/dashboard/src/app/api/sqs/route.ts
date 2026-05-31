import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

function safeJson(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

function computeSQS(p: {
  confidence: number
  direction: string
  sharpe: number | null
  winRate: number | null
  regime: string | null
  drift: string
  shadowSharpe?: number
  shadowWr?: number
}): number {
  if (p.direction === 'flat') return 0

  // Confidence: 0–30 pts
  const confScore = Math.min(1, p.confidence) * 30

  // Backtest quality: 0–35 pts
  let btScore = 0
  if (p.sharpe !== null && p.winRate !== null) {
    const sn = Math.min(1, Math.max(0, p.sharpe / 3.0))
    const wn = Math.min(1, Math.max(0, p.winRate / 100))
    btScore = (sn * 0.7 + wn * 0.3) * 35
  }

  // Shadow: 0–15 pts
  let shadowScore = 0
  if (p.shadowSharpe !== undefined && p.shadowWr !== undefined) {
    const ss = Math.min(1, Math.max(0, p.shadowSharpe / 2.0))
    const sw = Math.min(1, Math.max(0, p.shadowWr / 100))
    shadowScore = (ss * 0.6 + sw * 0.4) * 15
  }

  // Regime: −5 to +5 pts
  const regAdj = (p.regime === 'trending_up' || p.regime === 'trending_down') ? 5
    : p.regime === 'ranging' ? 0
    : p.regime === 'volatile' ? -5 : 0

  // Drift: −30 to 0 pts
  const driftAdj = p.drift === 'WARNING' ? -5
    : p.drift === 'DRIFTING' ? -15
    : p.drift === 'SHOCK' ? -30 : 0

  return Math.round(Math.max(0, Math.min(100, confScore + btScore + shadowScore + regAdj + driftAdj)))
}

export async function GET() {
  const redis = createRedis()
  try {
    const [sigKeys, btRaw, shadowRaw] = await Promise.all([
      redis.keys('signal:latest:*'),
      redis.get('backtest:results'),
      redis.get('shadow:leaderboard'),
    ])

    if (!sigKeys.length) {
      return NextResponse.json([])
    }

    const symbols = sigKeys.map((k: string | Buffer) =>
      (k as string).replace('signal:latest:', '')
    )

    const pipeline = redis.pipeline()
    for (const sym of symbols) pipeline.get(`signal:latest:${sym}`)
    for (const sym of symbols) pipeline.get(`features:latest:${sym}`)
    const results = await pipeline.exec()

    const half = symbols.length
    const backtest = btRaw ? safeJson(btRaw) : null
    const btResults = (backtest?.results as Record<string, Record<string, unknown>>) ?? {}

    const shadowList: { shadow_id: string; sharpe: number; win_rate: number; trades: number }[] =
      shadowRaw ? JSON.parse(shadowRaw) : []
    const bestShadow = shadowList.length > 0
      ? shadowList.reduce((a, b) => (a.sharpe > b.sharpe ? a : b))
      : null

    const sqsList: {
      symbol: string; sqs: number; direction: string; confidence: number;
      sharpe: number | null; win_rate: number | null; regime: string | null; drift: string
    }[] = []

    for (let i = 0; i < symbols.length; i++) {
      const sig = safeJson(results?.[i]?.[1] as string | null) ?? {}
      const feat = safeJson(results?.[half + i]?.[1] as string | null) ?? {}

      const direction = (sig.direction as string) || 'flat'
      const confidence = typeof sig.confidence === 'number' ? sig.confidence : 0
      const regime = (sig.regime as string) || (feat.regime as string) || null
      const drift = (feat.drift_status as string) || 'STABLE'

      const bt = btResults[symbols[i]] ?? null
      const sharpe = bt ? (typeof bt.sharpe_ratio === 'number' ? bt.sharpe_ratio : null) : null
      const winRate = bt ? (typeof bt.win_rate_pct === 'number' ? bt.win_rate_pct : null) : null

      const sqs = computeSQS({
        confidence,
        direction,
        sharpe,
        winRate,
        regime,
        drift,
        shadowSharpe: bestShadow?.sharpe,
        shadowWr: bestShadow?.win_rate,
      })

      sqsList.push({ symbol: symbols[i], sqs, direction, confidence, sharpe, win_rate: winRate, regime, drift })
    }

    sqsList.sort((a, b) => b.sqs - a.sqs)

    return NextResponse.json(sqsList)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
