import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

function safe(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

function computeSQS(p: {
  confidence: number; direction: string; sharpe: number | null
  winRate: number | null; regime: string | null; drift: string
  shadowSharpe?: number; shadowWr?: number
}): number {
  if (p.direction === 'flat') return 0
  const confScore = Math.min(1, p.confidence) * 30
  let btScore = 0
  if (p.sharpe !== null && p.winRate !== null) {
    const sn = Math.min(1, Math.max(0, p.sharpe / 3.0))
    const wn = Math.min(1, Math.max(0, p.winRate / 100))
    btScore = (sn * 0.7 + wn * 0.3) * 35
  }
  let shadowScore = 0
  if (p.shadowSharpe !== undefined && p.shadowWr !== undefined) {
    const ss = Math.min(1, Math.max(0, p.shadowSharpe / 2.0))
    const sw = Math.min(1, Math.max(0, p.shadowWr / 100))
    shadowScore = (ss * 0.6 + sw * 0.4) * 15
  }
  const regAdj = (p.regime === 'trending_up' || p.regime === 'trending_down') ? 5
    : p.regime === 'volatile' ? -5 : 0
  const driftAdj = p.drift === 'WARNING' ? -5 : p.drift === 'DRIFTING' ? -15 : p.drift === 'SHOCK' ? -30 : 0
  return Math.round(Math.max(0, Math.min(100, confScore + btScore + shadowScore + regAdj + driftAdj)))
}

export async function GET() {
  const redis = createRedis()
  try {
    const [featKeys, wsRaw, btRaw, shadowRaw] = await Promise.all([
      redis.keys('features:latest:*'),
      redis.get('ws:status'),
      redis.get('backtest:results'),
      redis.get('shadow:leaderboard'),
    ])

    if (featKeys.length === 0) {
      return NextResponse.json({ coins: [], total: 0, long_count: 0, short_count: 0, flat_count: 0, ws_status: null })
    }

    const symbols = featKeys.map(k => (k as string).replace('features:latest:', ''))

    const pipeline = redis.pipeline()
    for (const sym of symbols) pipeline.get(`features:latest:${sym}`)
    for (const sym of symbols) pipeline.get(`signal:latest:${sym}`)
    const results = await pipeline.exec()

    const half = symbols.length

    const backtest = btRaw ? safe(btRaw) : null
    const btResults = (backtest?.results as Record<string, Record<string, unknown>>) ?? {}

    const shadowList: { sharpe: number; win_rate: number }[] = shadowRaw ? JSON.parse(shadowRaw) : []
    const bestShadow = shadowList.length > 0
      ? shadowList.reduce((a, b) => (a.sharpe > b.sharpe ? a : b))
      : null

    const coins: Record<string, unknown>[] = []

    for (let i = 0; i < symbols.length; i++) {
      const f = safe(results?.[i]?.[1] as string | null)
      if (!f) continue
      const s = safe(results?.[half + i]?.[1] as string | null) ?? {}

      const direction = (s.direction as string) || 'flat'
      const confidence = typeof s.confidence === 'number' ? s.confidence : 0
      const rsi = typeof f.rsi_14 === 'number' ? f.rsi_14 : null
      const macdHist = typeof f.macd_hist === 'number' ? f.macd_hist : null
      const bbPos = typeof f.bb_position === 'number' ? f.bb_position : null
      const atrPct = typeof f.atr_pct === 'number' ? f.atr_pct : null
      const volRatio = typeof f.volume_ratio === 'number' ? f.volume_ratio : null
      const drift = typeof f.drift_status === 'string' ? f.drift_status : 'STABLE'
      const regime = (s.regime as string) || (f.regime as string) || null
      const ts = typeof f.timestamp === 'number' ? f.timestamp : null

      const bt = btResults[symbols[i]] ?? null
      const sharpe = bt ? (typeof bt.sharpe_ratio === 'number' ? bt.sharpe_ratio : null) : null
      const winRate = bt ? (typeof bt.win_rate_pct === 'number' ? bt.win_rate_pct : null) : null

      const sqs = computeSQS({
        confidence, direction, sharpe, winRate, regime, drift,
        shadowSharpe: bestShadow?.sharpe, shadowWr: bestShadow?.win_rate,
      })

      coins.push({
        symbol: symbols[i], direction, confidence, rsi, macd_hist: macdHist,
        bb_position: bbPos, atr_pct: atrPct, volume_ratio: volRatio,
        drift, regime, timestamp: ts, sqs,
        sharpe, win_rate: winRate,
      })
    }

    coins.sort((a, b) => {
      const ad = a.direction as string; const bd = b.direction as string
      if (ad !== 'flat' && bd === 'flat') return -1
      if (ad === 'flat' && bd !== 'flat') return 1
      return (b.sqs as number) - (a.sqs as number)
    })

    return NextResponse.json({
      coins,
      total: coins.length,
      long_count: coins.filter(c => c.direction === 'long').length,
      short_count: coins.filter(c => c.direction === 'short').length,
      flat_count: coins.filter(c => c.direction === 'flat').length,
      ws_status: safe(wsRaw),
      server_time: Date.now(),
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
