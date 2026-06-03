import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols } from '@/lib/universe'
import { computeSQS, depthLabel } from '@/lib/sqs'

function safe(raw: string | null): Record<string, unknown> | null {
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
    const limit = Math.min(100, parseInt(searchParams.get('limit') ?? '50', 10))
    const minSqs = parseInt(searchParams.get('min_sqs') ?? '0', 10)

    const [symbols, shadowRaw, btRaw] = await Promise.all([
      discoverSymbols(redis),
      redis.get('shadow:leaderboard'),
      redis.get('backtest:results'),
    ])

    const pipeline = redis.pipeline()
    for (const sym of symbols) {
      pipeline.get(`features:latest:${sym}`)
      pipeline.get(`signal:latest:${sym}`)
      pipeline.get(`agents:verdict:${sym}`)
      pipeline.get(`learn:profile:${sym}`)
      pipeline.get(`context:latest:${sym}`)
    }
    const exec = await pipeline.exec()
    const n = symbols.length

    const shadowList = shadowRaw ? (JSON.parse(shadowRaw) as { sharpe: number; win_rate: number }[]) : []
    const bestShadow = shadowList.length
      ? shadowList.reduce((a, b) => (a.sharpe > b.sharpe ? a : b))
      : null

    const bt = btRaw ? safe(btRaw) : null
    const btMap = (bt?.results as Record<string, Record<string, unknown>>) ?? {}

    type Row = Record<string, unknown>
    const rows: Row[] = []

    for (let i = 0; i < n; i++) {
      const sym = symbols[i]
      const f = safe(exec?.[i]?.[1] as string | null)
      if (!f) continue
      const s = safe(exec?.[n + i]?.[1] as string | null) ?? {}
      const v = safe(exec?.[2 * n + i]?.[1] as string | null) ?? {}
      const learn = safe(exec?.[3 * n + i]?.[1] as string | null) ?? {}
      const ctx = safe(exec?.[4 * n + i]?.[1] as string | null) ?? {}

      const direction = (s.direction as string) || 'flat'
      const confidence = typeof s.confidence === 'number' ? s.confidence : 0
      const imb = typeof f.imbalance_5 === 'number' ? f.imbalance_5 : null
      const funding = typeof f.funding_rate === 'number' ? f.funding_rate : null
      const regime = (ctx.regime as string) || (s.regime as string) || null
      const drift = (f.drift_status as string) || 'STABLE'
      const btRow = btMap[sym]
      const sharpe = btRow ? Number(btRow.sharpe_ratio ?? 0) : null
      const winRate = btRow ? Number(btRow.win_rate_pct ?? 0) : null

      const sqs = computeSQS({
        confidence,
        direction,
        sharpe,
        winRate,
        regime,
        drift,
        shadowSharpe: bestShadow?.sharpe,
        shadowWr: bestShadow ? bestShadow.win_rate * 100 : undefined,
        imbalance5: imb,
        learnStage: learn.learning_stage as string | undefined,
      })

      if (sqs < minSqs) continue

      rows.push({
        symbol: sym,
        direction,
        confidence,
        sqs,
        regime,
        drift,
        rsi: f.rsi_14,
        macd_hist: f.macd_hist,
        volume_ratio: f.volume_ratio,
        imbalance_5: imb,
        depth_label: depthLabel(imb),
        funding_rate: funding,
        adx: f.adx,
        ai_verdict: v.direction,
        ai_confidence: v.confidence,
        learn_stage: learn.learning_stage,
        depth_score: learn.depth_score,
        best_entry: learn.best_entry_hint,
        avoid_hint: learn.avoid_hint,
        trade_action: s.trade_action,
        is_valid: s.is_valid,
        sharpe,
        win_rate: winRate,
      })
    }

    rows.sort((a, b) => Number(b.sqs) - Number(a.sqs))

    const longTop = rows.filter(r => r.direction === 'long').slice(0, 15)
    const shortTop = rows.filter(r => r.direction === 'short').slice(0, 15)
    const closeSignals = rows.filter(r => r.trade_action === 'close').slice(0, 20)

    return NextResponse.json({
      total: rows.length,
      top: rows.slice(0, limit),
      long_opportunities: longTop,
      short_opportunities: shortTop,
      close_signals: closeSignals,
      updated_at: Date.now() / 1000,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
