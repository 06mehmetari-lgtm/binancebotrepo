import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../../_redis'
import type { ChartPoint, PositionChartPayload } from '@/lib/position-charts'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try {
    return JSON.parse(raw)
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
    const [posRaw, ticksRaw, tickerRaw, featRaw, brainRaw, lessonRaw] = await Promise.all([
      redis.get(`oms:position:${symbol}`),
      redis.lrange(`oms:ticks:${symbol}`, 0, 399),
      redis.get(`binance:ticker:${symbol.toLowerCase()}`),
      redis.get(`features:latest:${symbol}`),
      redis.get(`oms:chart:brain:${symbol}`),
      redis.lindex(`trade:lessons:${symbol}`, 0),
    ])

    const pos = safeJson(posRaw) as Record<string, unknown> | null
    if (!pos) {
      return NextResponse.json({ error: 'no open position' }, { status: 404 })
    }

    const brain = safeJson(brainRaw) as Record<string, unknown> | null
    const direction = String(pos.direction ?? 'long')
    const entry = Number(pos.entry_price ?? 0)
    const entryTs = Number(pos.entry_time ?? 0)
    let current = tickerMid(tickerRaw)
    if (current <= 0) {
      const f = safeJson(featRaw) as Record<string, unknown> | null
      current = Number(f?.close ?? f?.last_price ?? 0)
    }

    const blueprint = (pos.entry_blueprint ?? pos.trade_plan) as Record<string, unknown> | null
    const tradePlan = (pos.trade_plan ?? blueprint) as Record<string, unknown> | null

    const live: ChartPoint[] = ticksRaw
      .map(r => safeJson(r) as Record<string, unknown> | null)
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
      const upnl =
        entry > 0
          ? direction === 'long'
            ? ((current - entry) / entry) * 100
            : ((entry - current) / entry) * 100
          : 0
      const last = live[live.length - 1]
      if (!last || Math.abs(last.ts - now) > 0.05) {
        live.push({ ts: now, price: current, pnl_pct: upnl, kind: 'live' })
      } else {
        live[live.length - 1] = { ...last, price: current, pnl_pct: upnl }
      }
    }

    const blueprintCurve: ChartPoint[] = (
      (blueprint?.blueprint_curve ?? tradePlan?.planned_curve ?? []) as ChartPoint[]
    ).map(p => ({
      ts: Number(p.ts),
      price: Number(p.price),
      pnl_pct: Number(p.pnl_pct ?? 0),
      kind: 'blueprint' as const,
    }))

    const rolling = brain?.rolling as PositionChartPayload['rolling']
    const analysis: ChartPoint[] = (rolling?.points ?? []).map(p => ({
      ts: Number(p.ts),
      price: Number(p.price),
      pnl_pct: Number(p.upnl_pct ?? 0),
      delta_pct: Number(p.delta_pct ?? 0),
      blueprint_price: Number(p.blueprint_price ?? 0),
      kind: 'analysis' as const,
    }))

    const forecastRaw = (brain?.forecast as ChartPoint[]) ?? []
    const forecast: ChartPoint[] = forecastRaw.map(p => ({
      ts: Number(p.ts),
      price: Number(p.price),
      pnl_pct: Number(p.pnl_pct ?? 0),
      kind: 'forecast' as const,
    }))

    const mmFromBrain = brain?.mismatch as PositionChartPayload['mismatch'] | undefined
    const tick = brain?.tick as Record<string, unknown> | undefined
    const plannedPrice = Number(tick?.blueprint_price ?? tick?.planned_price ?? entry)
    const vsPlanned = mmFromBrain?.vs_planned ?? (
      plannedPrice > 0 ? ((current - plannedPrice) / plannedPrice) * 100 : 0
    )
    const mismatchPct = mmFromBrain?.pct ?? Math.abs(vsPlanned)

    const delta: ChartPoint[] = live.map(lp => {
      const bp = Number(
        analysis.find(a => Math.abs(a.ts - lp.ts) < 2)?.blueprint_price ?? plannedPrice,
      )
      return {
        ts: lp.ts,
        price: lp.price - bp,
        pnl_pct: bp > 0 ? ((lp.price - bp) / bp) * 100 : 0,
        kind: 'delta',
      }
    })

    const unrealizedPct = Number(tick?.upnl_pct ?? live[live.length - 1]?.pnl_pct ?? 0)

    let llmLesson: string | null = null
    const lesson = safeJson(lessonRaw as string | null) as { text?: string; source?: string } | null
    if (lesson?.text && (lesson.source === 'chart_brain' || lesson.source === 'position_track_llm')) {
      llmLesson = lesson.text
    }

    const payload: PositionChartPayload = {
      symbol,
      direction,
      entry_price: entry,
      entry_ts: entryTs,
      current_price: current,
      unrealized_pct: +unrealizedPct.toFixed(4),
      mismatch: mmFromBrain ?? {
        pct: +mismatchPct.toFixed(4),
        severity: mismatchSeverity(Math.abs(mismatchPct)),
        vs_planned: +vsPlanned.toFixed(4),
        vs_forecast: 0,
        why: 'hesaplanıyor',
      },
      consensus: brain?.consensus as PositionChartPayload['consensus'],
      rolling,
      blueprint: blueprint
        ? {
            frozen_at: Number(blueprint.frozen_at ?? entryTs),
            narrative: String(blueprint.narrative ?? ''),
            reasons: (blueprint.reasons as string[]) ?? [],
            action: String(blueprint.action ?? ''),
            confidence: Number(blueprint.confidence ?? 0),
            regime: String(blueprint.regime ?? ''),
            blueprint_curve: blueprintCurve,
          }
        : undefined,
      why_move: String((brain as { why_move?: string })?.why_move ?? rolling?.trend ?? ''),
      llm_lesson: llmLesson,
      stop_loss: Number(tradePlan?.stop_loss ?? blueprint?.stop_loss ?? 0) || null,
      take_profit_prices: (tradePlan?.take_profit_prices as number[]) ?? (blueprint?.take_profit_prices as number[]) ?? [],
      tiers_pct: (tradePlan?.take_profit_tiers_pct as number[]) ?? (blueprint?.take_profit_tiers_pct as number[]) ?? [],
      fills: (pos.fills as PositionChartPayload['fills']) ?? [],
      live,
      blueprint_curve: blueprintCurve,
      planned: blueprintCurve,
      forecast,
      delta,
      analysis,
      updated_at: Number(brain?.updated_at ?? Date.now() / 1000),
    }

    return NextResponse.json(payload)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
