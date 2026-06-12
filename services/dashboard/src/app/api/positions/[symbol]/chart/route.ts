import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../../_redis'
import type { ChartPoint, PositionChartPayload } from '@/lib/position-charts'

function safeJson(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    return null
  }
}

function tickerMid(raw: string | null): number {
  if (!raw) return 0
  try {
    const t = JSON.parse(raw) as { data?: { b?: string; a?: string } }
    const d = t.data ?? t
    const bid = parseFloat(String((d as { b?: string }).b ?? 0))
    const ask = parseFloat(String((d as { a?: string }).a ?? bid))
    return bid > 0 && ask > 0 ? (bid + ask) / 2 : bid || ask
  } catch {
    return 0
  }
}

function priceAtPct(entry: number, direction: string, pct: number): number {
  if (entry <= 0) return 0
  return direction === 'long' ? entry * (1 + pct / 100) : entry * (1 - pct / 100)
}

function plannedNow(
  tradePlan: Record<string, unknown> | null,
  entryTs: number,
  entry: number,
  direction: string,
): number {
  if (!tradePlan) return entry
  const elapsed = Math.max(0, Date.now() / 1000 - entryTs)
  const curve = (tradePlan.planned_curve as { elapsed_sec?: number; price?: number }[]) || []
  if (curve.length) {
    let best = curve[0]
    for (const pt of curve) {
      if ((pt.elapsed_sec ?? 0) <= elapsed) best = pt
      else break
    }
    return Number(best.price ?? entry)
  }
  const horizon = Number(tradePlan.horizon_sec ?? 3600)
  const tp0 = Number((tradePlan.take_profit_tiers_pct as number[])?.[0] ?? 0.5)
  const prog = Math.min(1, elapsed / horizon)
  return priceAtPct(entry, direction, tp0 * prog ** 0.65)
}

function buildForecast(
  current: number,
  direction: string,
  signal: Record<string, unknown> | null,
): ChartPoint[] {
  if (current <= 0) return []
  const decision = (signal?.decision as Record<string, unknown>) || {}
  const outcome =
    ((signal?.ensemble as Record<string, unknown>)?.outcome as Record<string, unknown>) || {}
  const expRet = Number(outcome.expected_return_pct ?? decision.expected_return_pct ?? 0.8)
  const winP = Number(outcome.win_probability ?? 0.55)
  const risk = Number(outcome.max_drawdown_risk ?? decision.risk_score ?? 0.3)
  const regimeStrength = Number(signal?.regime_strength ?? 0.5)
  let targetPct = expRet * winP * (1 - Math.min(risk, 0.5))
  targetPct *= 0.7 + 0.3 * regimeStrength

  const now = Date.now() / 1000
  const points = 48
  const step = 30
  const out: ChartPoint[] = []
  for (let i = 0; i < points; i++) {
    const prog = i / Math.max(points - 1, 1)
    const move = targetPct * prog ** 0.85
    const p =
      direction === 'long'
        ? current * (1 + move / 100)
        : current * (1 - move / 100)
    out.push({ ts: now + i * step, price: p, pnl_pct: move, kind: 'forecast' })
  }
  return out
}

function mismatchSeverity(pct: number): PositionChartPayload['mismatch']['severity'] {
  if (pct >= 1.2) return 'critical'
  if (pct >= 0.55) return 'warn'
  if (pct >= 0.25) return 'drift'
  return 'ok'
}

export async function GET(
  _req: Request,
  { params }: { params: { symbol: string } },
) {
  const redis = createRedis()
  const symbol = params.symbol?.toUpperCase()
  if (!symbol?.endsWith('USDT')) {
    return NextResponse.json({ error: 'invalid symbol' }, { status: 400 })
  }

  try {
    const [posRaw, ticksRaw, tickerRaw, featRaw, sigRaw] = await Promise.all([
      redis.get(`oms:position:${symbol}`),
      redis.lrange(`oms:ticks:${symbol}`, 0, 599),
      redis.get(`binance:ticker:${symbol.toLowerCase()}`),
      redis.get(`features:latest:${symbol}`),
      redis.get(`signal:latest:${symbol}`),
    ])

    const pos = safeJson(posRaw)
    if (!pos) {
      return NextResponse.json({ error: 'no open position' }, { status: 404 })
    }

    const direction = String(pos.direction ?? 'long')
    const entry = Number(pos.entry_price ?? 0)
    const entryTs = Number(pos.entry_time ?? 0)
    let current = tickerMid(tickerRaw)
    if (current <= 0) {
      const f = safeJson(featRaw)
      current = Number(f?.close ?? f?.last_price ?? 0)
    }

    const signal = safeJson(sigRaw)
    const tradePlan = (pos.trade_plan as Record<string, unknown>) || null
    const ladder = (pos.ladder as Record<string, unknown>) || {}

    const live: ChartPoint[] = ticksRaw
      .map(r => safeJson(r))
      .filter(Boolean)
      .map(t => ({
        ts: Number(t!.ts_ms ?? t!.ts ?? 0) / (Number(t!.ts_ms) > 1e12 ? 1000 : 1),
        price: Number(t!.price ?? 0),
        pnl_pct: Number(t!.upnl_pct ?? 0),
        kind: 'live' as const,
      }))
      .filter(p => p.price > 0)
      .reverse()

    if (current > 0) {
      const now = Date.now() / 1000
      live.push({
        ts: now,
        price: current,
        pnl_pct:
          entry > 0
            ? direction === 'long'
              ? ((current - entry) / entry) * 100
              : ((entry - current) / entry) * 100
            : 0,
        kind: 'live',
      })
    }

    const plannedCurve = (tradePlan?.planned_curve as ChartPoint[]) || []
    const planned: ChartPoint[] = plannedCurve.map(p => ({
      ts: Number(p.ts),
      price: Number(p.price),
      pnl_pct: Number(p.pnl_pct ?? 0),
      kind: 'planned',
    }))

    const forecast = buildForecast(current, direction, signal)

    const plannedPrice = plannedNow(tradePlan, entryTs, entry, direction)
    const forecastNow = forecast[0]?.price ?? current
    const vsPlanned = plannedPrice > 0 ? ((current - plannedPrice) / plannedPrice) * 100 : 0
    const vsForecast = forecastNow > 0 ? ((current - forecastNow) / forecastNow) * 100 : 0
    const mismatchPct = Math.abs(vsPlanned)

    const delta: ChartPoint[] = live.map(lp => {
      const elapsed = lp.ts - entryTs
      let planPt = plannedPrice
      for (const pp of planned) {
        if (pp.ts - entryTs <= elapsed) planPt = pp.price
      }
      return {
        ts: lp.ts,
        price: lp.price - planPt,
        pnl_pct: planPt > 0 ? ((lp.price - planPt) / planPt) * 100 : 0,
        kind: 'delta',
      }
    })

    const unrealizedPct =
      entry > 0 && current > 0
        ? direction === 'long'
          ? ((current - entry) / entry) * 100
          : ((entry - current) / entry) * 100
        : 0

    const payload: PositionChartPayload = {
      symbol,
      direction,
      entry_price: entry,
      entry_ts: entryTs,
      current_price: current,
      unrealized_pct: +unrealizedPct.toFixed(4),
      mismatch: {
        pct: +mismatchPct.toFixed(4),
        severity: mismatchSeverity(mismatchPct),
        vs_planned: +vsPlanned.toFixed(4),
        vs_forecast: +vsForecast.toFixed(4),
      },
      stop_loss: Number(tradePlan?.stop_loss ?? 0) || null,
      take_profit_prices: (tradePlan?.take_profit_prices as number[]) || [],
      tiers_pct: (tradePlan?.take_profit_tiers_pct as number[]) || [],
      fills: (pos.fills as PositionChartPayload['fills']) || [],
      live,
      planned,
      forecast,
      delta,
      updated_at: Date.now() / 1000,
    }

    return NextResponse.json(payload)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
