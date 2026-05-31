import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

function safeJson(raw: string | null | undefined): unknown {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

export async function GET() {
  const redis = createRedis()
  try {
    const pipeline = redis.pipeline()
    pipeline.get('immunity:status')
    pipeline.get('immunity:daily_loss')
    pipeline.get('immunity:daily_trades')
    pipeline.get('context:crisis_level')
    pipeline.get('context:regime')
    pipeline.get('macro:vix')
    pipeline.lrange('alerts:funding', 0, 9)
    pipeline.lrange('liquidations:large', 0, 9)
    pipeline.get('ws:status')
    // Aggregate daily loss across signals
    const featureKeys = await redis.keys('features:latest:*')
    for (const k of featureKeys.slice(0, 10)) {
      pipeline.get(k)
    }
    const results = await pipeline.exec()

    const immunityStatus = safeJson(results?.[0]?.[1] as string | null) as Record<string, unknown> | null
    const dailyLoss = safeJson(results?.[1]?.[1] as string | null)
    const dailyTrades = safeJson(results?.[2]?.[1] as string | null)
    const crisisLevel = safeJson(results?.[3]?.[1] as string | null)
    const regime = safeJson(results?.[4]?.[1] as string | null)
    const vixRaw = safeJson(results?.[5]?.[1] as string | null) as Record<string, unknown> | null
    const fundingAlertsRaw = (results?.[6]?.[1] as string[] | null) ?? []
    const liquidationsRaw = (results?.[7]?.[1] as string[] | null) ?? []
    const wsStatus = safeJson(results?.[8]?.[1] as string | null) as Record<string, unknown> | null

    // Parse funding alerts
    const fundingAlerts = fundingAlertsRaw
      .map(s => safeJson(s))
      .filter(Boolean)

    // Parse liquidations
    const recentLiquidations = liquidationsRaw
      .map(s => safeJson(s))
      .filter(Boolean)

    // Extract drift status from features
    const driftCounts: Record<string, number> = { STABLE: 0, WARNING: 0, DRIFTING: 0, SHOCK: 0 }
    for (let i = 9; i < 9 + featureKeys.slice(0, 10).length; i++) {
      const feat = safeJson(results?.[i]?.[1] as string | null) as Record<string, unknown> | null
      if (feat?.drift_status && typeof feat.drift_status === 'string') {
        driftCounts[feat.drift_status] = (driftCounts[feat.drift_status] ?? 0) + 1
      }
    }

    const vixValue = typeof vixRaw?.value === 'number' ? vixRaw.value : null

    return NextResponse.json({
      immunity_halted: immunityStatus?.halted ?? false,
      daily_loss_pct: typeof dailyLoss === 'number' ? dailyLoss : 0,
      daily_trades: typeof dailyTrades === 'number' ? dailyTrades : 0,
      crisis_level: typeof crisisLevel === 'number' ? crisisLevel : 0,
      regime: typeof regime === 'string' ? regime : null,
      vix: vixValue,
      ws_status: wsStatus?.status ?? 'UNKNOWN',
      funding_alerts: fundingAlerts,
      recent_liquidations: recentLiquidations,
      drift_summary: driftCounts,
      // Hard-coded limits from immunity.py
      limits: {
        max_drawdown: 0.10,
        max_daily_loss: 0.02,
        max_position_pct: 0.07,
        min_confidence: 0.52,
        max_trades_per_day: 50,
        max_leverage: 3.0,
        max_open_positions: 3,
      },
      crisis_scale: {
        0: { label: 'Normal', multiplier: 1.0, color: 'green' },
        1: { label: 'Caution', multiplier: 0.65, color: 'yellow' },
        2: { label: 'Warning', multiplier: 0.35, color: 'orange' },
        3: { label: 'Alarm', multiplier: 0.10, color: 'red' },
        4: { label: 'Crisis', multiplier: 0.0, color: 'red' },
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
