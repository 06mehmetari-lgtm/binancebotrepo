import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { fetchOpenPositions, consolidatePositions } from '@/lib/positions'
import { buildEquityCurve, PORTFOLIO_START } from '@/lib/build-equity-curve'

export async function GET() {
  const redis = createRedis()
  try {
    const [tradeHistRaw, dailyPnlRaw, snapshotsRaw, posData, tryCapRaw, capRaw] = await Promise.all([
      redis.lrange('oms:trade_history', 0, 499),
      redis.get('oms:daily_pnl'),
      redis.lrange('portfolio:pnl:snapshots', 0, 719),
      fetchOpenPositions(redis),
      redis.get('portfolio:try:v1'),
      redis.get('portfolio:capital:v1'),
    ])

    let portfolioCap: {
      try_amount?: number
      usd_cap?: number
      portfolio_usd?: number
      usd_try_rate?: number
      fee_per_side_pct?: number
    } | null = null
    for (const raw of [capRaw, tryCapRaw]) {
      if (!raw) continue
      try {
        const parsed = JSON.parse(raw)
        portfolioCap = { ...portfolioCap, ...parsed }
        break
      } catch {
        continue
      }
    }
    const startEquity =
      typeof portfolioCap?.usd_cap === 'number' && portfolioCap.usd_cap > 0
        ? portfolioCap.usd_cap
        : typeof portfolioCap?.portfolio_usd === 'number' && portfolioCap.portfolio_usd > 0
          ? portfolioCap.portfolio_usd
          : PORTFOLIO_START

    const trades = tradeHistRaw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
      .sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0))

    const snapshots = snapshotsRaw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
      .sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0))

    const consolidated = consolidatePositions(posData.positions)
    const unrealizedUsdt = consolidated.reduce((s, p) => s + (p.unrealized_usdt ?? 0), 0)

    const { curve, realizedEquity, liveEquity } = buildEquityCurve({
      trades,
      snapshots,
      unrealizedUsdt,
      startEquity,
    })

    const winTrades = trades.filter(t => (t.pnl_pct ?? 0) > 0)
    const lossTrades = trades.filter(t => (t.pnl_pct ?? 0) <= 0)
    const winRate = trades.length > 0 ? (winTrades.length / trades.length) * 100 : 0
    const avgWin = winTrades.length > 0
      ? winTrades.reduce((s, t) => s + (t.pnl_usdt ?? 0), 0) / winTrades.length
      : 0
    const avgLoss = lossTrades.length > 0
      ? Math.abs(lossTrades.reduce((s, t) => s + (t.pnl_usdt ?? 0), 0) / lossTrades.length)
      : 0

    const grossWin = winTrades.reduce((s, t) => s + (t.pnl_usdt ?? 0), 0)
    const grossLoss = Math.abs(lossTrades.reduce((s, t) => s + (t.pnl_usdt ?? 0), 0))

    let peak = PORTFOLIO_START
    let maxDrawdown = 0
    for (const p of curve) {
      if (p.equity > peak) peak = p.equity
      const dd = peak > 0 ? (peak - p.equity) / peak : 0
      if (dd > maxDrawdown) maxDrawdown = dd
    }

    const totalPnl = liveEquity - startEquity
    const recentTrades = [...trades].reverse().slice(0, 15)

    return NextResponse.json({
      curve,
      snapshots,
      recent_trades: recentTrades,
      stats: {
        start_equity: startEquity,
        portfolio_try: portfolioCap?.try_amount ?? null,
        usd_try_rate: portfolioCap?.usd_try_rate ?? null,
        fee_per_side_pct: portfolioCap?.fee_per_side_pct ?? null,
        current_equity: liveEquity,
        realized_equity: realizedEquity,
        unrealized_usdt: +unrealizedUsdt.toFixed(2),
        total_pnl: +totalPnl.toFixed(2),
        total_pnl_pct: +(totalPnl / startEquity * 100).toFixed(2),
        daily_pnl: dailyPnlRaw ? parseFloat(dailyPnlRaw) : 0,
        total_trades: trades.length,
        win_rate: +winRate.toFixed(1),
        avg_win_usdt: +avgWin.toFixed(2),
        avg_loss_usdt: +avgLoss.toFixed(2),
        profit_factor: grossLoss > 0 ? +(grossWin / grossLoss).toFixed(2) : null,
        max_drawdown_pct: +(maxDrawdown * 100).toFixed(2),
        open_positions: consolidated.length,
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    await redis.quit()
  }
}
