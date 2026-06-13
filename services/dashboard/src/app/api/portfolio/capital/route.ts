import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'
import { resolveRiskLimits } from '@/lib/risk-limits-service'

const CAPITAL_KEY = 'portfolio:capital:v1'
const TRY_KEY = 'portfolio:try:v1'
const PUB_CHANNEL = 'ch:portfolio:updated'

function parseUsdCap(raw: string | null): number {
  if (!raw) return 0
  try {
    const d = JSON.parse(raw) as Record<string, unknown>
    for (const k of ['usd_cap', 'portfolio_usd', 'cap_usd']) {
      const v = Number(d[k])
      if (Number.isFinite(v) && v > 0) return v
    }
  } catch {
    return 0
  }
  return 0
}

export async function GET() {
  const redis = createRedis()
  try {
    const [capRaw, tryRaw, limitsRes, liveRaw] = await Promise.all([
      redis.get(CAPITAL_KEY),
      redis.get(TRY_KEY),
      resolveRiskLimits({ syncRedisIfMissing: false }),
      redis.get('portfolio:live_equity:v1'),
    ])
    const usd_cap = parseUsdCap(capRaw) || parseUsdCap(tryRaw) || 10_000
    let live_equity = usd_cap
    let realized_pnl = 0
    if (liveRaw) {
      try {
        const live = JSON.parse(liveRaw) as { live_equity_usd?: number; realized_pnl_usd?: number }
        if (live.live_equity_usd && live.live_equity_usd > 0) {
          live_equity = live.live_equity_usd
          realized_pnl = Number(live.realized_pnl_usd ?? live.live_equity_usd - usd_cap)
        }
      } catch {
        /* ignore */
      }
    }
    const sizing_base = Math.max(usd_cap, live_equity)
    const limits = limitsRes.limits
    const slot = sizing_base / Math.max(limits.max_open_positions, 1)
    const maxMargin = sizing_base * limits.max_position_pct
    const exampleLev = Math.max(limits.min_leverage ?? 5, 3)
    let meta: Record<string, unknown> = {}
    if (capRaw) {
      try {
        meta = JSON.parse(capRaw)
      } catch {
        meta = {}
      }
    }
    return NextResponse.json({
      usd_cap,
      live_equity_usd: +live_equity.toFixed(2),
      realized_pnl_usd: +realized_pnl.toFixed(2),
      sizing_base_usd: +sizing_base.toFixed(2),
      updated_at: meta.updated_at ?? null,
      updated_by: meta.updated_by ?? null,
      source: meta.source ?? (capRaw ? 'redis' : 'default'),
      sizing: {
        slot_budget_usd: +slot.toFixed(2),
        max_margin_per_position_usd: +maxMargin.toFixed(2),
        max_open_positions: limits.max_open_positions,
        max_position_pct: limits.max_position_pct,
        max_leverage: limits.max_leverage,
        example_65conf_3x: {
          margin_usd: +(Math.min(maxMargin, slot * 0.92) * 0.65).toFixed(2),
          notional_usd: +(Math.min(maxMargin, slot * 0.92) * 0.65 * exampleLev).toFixed(2),
          leverage: exampleLev,
        },
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}

export async function POST(req: Request) {
  const redis = createRedis()
  try {
    const body = await req.json().catch(() => ({}))
    const usd_cap = Number(body.usd_cap)
    if (!Number.isFinite(usd_cap) || usd_cap < 100) {
      return NextResponse.json({ error: 'Bakiye en az $100 olmalı' }, { status: 400 })
    }
    if (usd_cap > 50_000_000) {
      return NextResponse.json({ error: 'Bakiye en fazla $50.000.000' }, { status: 400 })
    }
    const payload = {
      usd_cap: Math.round(usd_cap * 100) / 100,
      source: 'dashboard',
      updated_at: Date.now() / 1000,
      updated_by: String(body.updated_by || 'dashboard_positions'),
      fee_per_side_pct: Number(process.env.TRADE_FEE_PCT_PER_SIDE || 0.001),
    }
    const bodyStr = JSON.stringify(payload)
    await redis.set(CAPITAL_KEY, bodyStr)
    await redis.set(
      TRY_KEY,
      JSON.stringify({
        usd_cap: payload.usd_cap,
        portfolio_usd: payload.usd_cap,
        source: 'dashboard',
        updated_at: payload.updated_at,
        updated_by: payload.updated_by,
      }),
      'EX',
      86400 * 7,
    )
    await redis.publish(PUB_CHANNEL, bodyStr)
    const { limits } = await resolveRiskLimits({ syncRedisIfMissing: false })
    const slot = payload.usd_cap / Math.max(limits.max_open_positions, 1)
    return NextResponse.json({
      ok: true,
      message: `Bakiye $${payload.usd_cap.toLocaleString()} — OMS ve Shadow birkaç saniye içinde günceller.`,
      ...payload,
      sizing: {
        slot_budget_usd: +slot.toFixed(2),
        max_margin_per_position_usd: +(payload.usd_cap * limits.max_position_pct).toFixed(2),
        max_open_positions: limits.max_open_positions,
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
