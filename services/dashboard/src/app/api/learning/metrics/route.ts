import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'

function parseList(raw: string[]): unknown[] {
  return raw
    .map(r => {
      try {
        return JSON.parse(r)
      } catch {
        return null
      }
    })
    .filter(Boolean) as unknown[]
}

export async function GET() {
  const redis = createRedis()
  try {
    const [neatRaw, rlRaw, tradeHistRaw, learnGlobalRaw] = await Promise.all([
      redis.lrange('neat:evolution_log', 0, 199),
      redis.lrange('rl:train:history', 0, 99),
      redis.lrange('oms:trade_history', 0, 499),
      redis.get('learn:global:v1'),
    ])

    const neat = (parseList(neatRaw as string[]) as Record<string, unknown>[])
      .map(r => ({
        ts: Number(r.ts ?? r.timestamp ?? 0) || Math.floor(Date.now() / 1000),
        fitness: Number(r.fitness ?? 0),
        symbol: String(r.symbol ?? ''),
        generation: Number(r.generation ?? r.gen ?? 0),
        nodes: Number(r.nodes ?? 0),
      }))
      .filter(r => r.fitness > 0)
      .sort((a, b) => a.ts - b.ts)

    const rl = (parseList(rlRaw as string[]) as Record<string, unknown>[])
      .map(r => ({
        ts: Number(r.ts ?? 0),
        buffer_size: Number(r.buffer_size ?? 0),
        timesteps: Number(r.timesteps ?? 0),
        status: String(r.status ?? 'unknown'),
        loss_proxy: r.loss_proxy != null ? Number(r.loss_proxy) : null,
      }))
      .filter(r => r.ts > 0)
      .sort((a, b) => a.ts - b.ts)

    const trades = (parseList(tradeHistRaw as string[]) as Record<string, unknown>[])
      .map(t => ({
        closed_at: Number(t.closed_at ?? 0),
        pnl_pct: Number(t.pnl_pct ?? 0),
        won: Number(t.pnl_pct ?? 0) > 0,
      }))
      .filter(t => t.closed_at > 0)
      .sort((a, b) => a.closed_at - b.closed_at)

    const winRateTrend: { ts: number; win_rate: number; trade_n: number }[] = []
    let wins = 0
    for (let i = 0; i < trades.length; i++) {
      if (trades[i].won) wins++
      winRateTrend.push({
        ts: trades[i].closed_at,
        win_rate: +((wins / (i + 1)) * 100).toFixed(2),
        trade_n: i + 1,
      })
    }

    const learnGlobal = learnGlobalRaw
      ? (() => {
          try {
            return JSON.parse(learnGlobalRaw)
          } catch {
            return null
          }
        })()
      : null

    // NEAT fitness by time (avg per hour bucket for chart)
    const neatByTime: { ts: number; avg_fitness: number; count: number }[] = []
    const bucket = new Map<number, { sum: number; n: number }>()
    for (const e of neat) {
      const hour = Math.floor(e.ts / 3600) * 3600
      const cur = bucket.get(hour) ?? { sum: 0, n: 0 }
      cur.sum += e.fitness
      cur.n++
      bucket.set(hour, cur)
    }
    for (const [ts, v] of Array.from(bucket.entries()).sort((a, b) => a[0] - b[0])) {
      neatByTime.push({ ts, avg_fitness: +(v.sum / v.n).toFixed(4), count: v.n })
    }

    return NextResponse.json({
      neat,
      neat_by_time: neatByTime,
      rl,
      win_rate_trend: winRateTrend,
      learn_global: learnGlobal,
      summary: {
        neat_events: neat.length,
        rl_train_runs: rl.length,
        total_trades: trades.length,
        current_win_rate: winRateTrend.length ? winRateTrend[winRateTrend.length - 1].win_rate : 0,
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
