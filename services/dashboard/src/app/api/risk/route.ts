import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols } from '@/lib/universe'

function safeJson(raw: string | null | undefined): unknown {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

function macroVixNumber(raw: unknown): number | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (raw && typeof raw === 'object' && 'value' in raw) {
    const v = (raw as { value?: unknown }).value
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  }
  return null
}

export async function GET() {
  const redis = createRedis()
  try {
    const symbols = await discoverSymbols(redis)
    const featureKeys = symbols.map(s => `features:latest:${s}`)

    const pipeline = redis.pipeline()
    pipeline.get('immunity:status')
    pipeline.get('macro:vix')
    pipeline.lrange('alerts:funding', 0, 9)
    pipeline.lrange('liquidations:large', 0, 9)
    pipeline.get('ws:status')
    pipeline.get('system:promotion:status')
    const featSample = featureKeys.slice(0, 80)
    for (const k of featSample) {
      pipeline.get(k)
    }
    const ctxSample = featureKeys.slice(0, 30)
    for (const k of ctxSample) {
      const sym = k.replace('features:latest:', '')
      pipeline.get(`context:latest:${sym}`)
    }
    const results = await pipeline.exec()

    const immunityStatus = safeJson(results?.[0]?.[1] as string | null) as Record<string, unknown> | null
    const vixRaw = safeJson(results?.[1]?.[1] as string | null)
    const fundingAlertsRaw = (results?.[2]?.[1] as string[] | null) ?? []
    const liquidationsRaw = (results?.[3]?.[1] as string[] | null) ?? []
    const wsStatus = safeJson(results?.[4]?.[1] as string | null) as Record<string, unknown> | null
    const promotionStatus = safeJson(results?.[5]?.[1] as string | null) as Record<string, unknown> | null

    const driftCounts: Record<string, number> = { STABLE: 0, WARNING: 0, DRIFTING: 0, SHOCK: 0 }
    const featOffset = 6
    for (let i = 0; i < featSample.length; i++) {
      const feat = safeJson(results?.[featOffset + i]?.[1] as string | null) as Record<string, unknown> | null
      const drift = typeof feat?.drift_status === 'string' ? feat.drift_status : 'STABLE'
      driftCounts[drift] = (driftCounts[drift] ?? 0) + 1
    }

    let maxCrisis = 0
    let dominantRegime: string | null = null
    const regimeCounts: Record<string, number> = {}
    const ctxOffset = featOffset + featSample.length
    for (let i = 0; i < ctxSample.length; i++) {
      const ctx = safeJson(results?.[ctxOffset + i]?.[1] as string | null) as Record<string, unknown> | null
      if (!ctx) continue
      const c = typeof ctx.crisis_level === 'number' ? ctx.crisis_level : 0
      maxCrisis = Math.max(maxCrisis, c)
      const r = typeof ctx.regime === 'string' ? ctx.regime : null
      if (r) {
        regimeCounts[r] = (regimeCounts[r] ?? 0) + 1
      }
    }
    dominantRegime = Object.entries(regimeCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null

    const fundingAlerts = fundingAlertsRaw.map(s => safeJson(s)).filter(Boolean)
    const recentLiquidations = liquidationsRaw.map(s => safeJson(s)).filter(Boolean)

    const dailyLossPctRaw = typeof immunityStatus?.daily_loss_pct === 'number'
      ? immunityStatus.daily_loss_pct
      : 0
    // immunity:status stores daily_loss_pct as percent (0.15 = 0.15%)
    const dailyLossFraction = dailyLossPctRaw / 100
    const dailyTrades = typeof immunityStatus?.daily_trades === 'number'
      ? immunityStatus.daily_trades
      : 0
    const maxDailyLossPctImmunity = typeof immunityStatus?.max_daily_loss_pct === 'number'
      ? immunityStatus.max_daily_loss_pct / 100
      : 0.02

    return NextResponse.json({
      immunity_halted: Boolean(immunityStatus?.system_halted ?? immunityStatus?.halted ?? false),
      daily_loss_pct: dailyLossFraction,
      daily_loss_display_pct: dailyLossPctRaw,
      max_daily_loss_pct: maxDailyLossPctImmunity,
      daily_trades: dailyTrades,
      crisis_level: maxCrisis,
      regime: dominantRegime,
      vix: macroVixNumber(vixRaw),
      ws_status: wsStatus?.status ?? 'UNKNOWN',
      funding_alerts: fundingAlerts,
      recent_liquidations: recentLiquidations,
      drift_summary: driftCounts,
      symbols_tracked: featureKeys.length,
      promotion: promotionStatus
        ? {
            approved: Boolean(promotionStatus.approved),
            reason: promotionStatus.reason ?? null,
            best_shadow_id: promotionStatus.best_shadow_id ?? null,
            ready_count: promotionStatus.ready_count ?? 0,
            updated_at: promotionStatus.updated_at ?? null,
          }
        : { approved: false, reason: 'shadow_system not reporting', best_shadow_id: null, ready_count: 0 },
      live_trading_requires: ['DRY_RUN=false', 'LIVE_TRADING_CONFIRMED=true', 'promotion.approved=true'],
      limits: {
        max_drawdown: 0.10,
        max_daily_loss: 0.02,
        max_position_pct: 0.05,
        min_confidence: 0.60,
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
