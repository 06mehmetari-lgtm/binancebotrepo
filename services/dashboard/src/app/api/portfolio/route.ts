import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

const PORTFOLIO_START = 10000

export async function GET() {
  const redis = createRedis()
  try {
    const [tradeHistRaw, dailyPnlRaw, snapshotsRaw] = await Promise.all([
      redis.lrange('oms:trade_history', 0, 499),
      redis.get('oms:daily_pnl'),
      redis.lrange('portfolio:pnl:snapshots', 0, 719), // up to 30 days of hourly data
    ])

    const trades = tradeHistRaw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
      .sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0))

    // Build equity curve from trade history
    const curve: { ts: number; equity: number; pnl: number; symbol: string; direction: string }[] = []
    let equity = PORTFOLIO_START
    for (const t of trades) {
      equity += t.pnl_usdt ?? 0
      curve.push({
        ts: Math.round(t.closed_at ?? 0),
        equity: +equity.toFixed(2),
        pnl: +(t.pnl_usdt ?? 0).toFixed(2),
        symbol: t.symbol ?? '',
        direction: t.direction ?? '',
      })
    }

    // Hourly snapshots (if OMS writes them)
    const snapshots = snapshotsRaw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)
      .sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0))

    // Stats
    const totalPnl = equity - PORTFOLIO_START
    const winTrades = trades.filter(t => (t.pnl_pct ?? 0) > 0)
    const lossTrades = trades.filter(t => (t.pnl_pct ?? 0) <= 0)
    const winRate = trades.length > 0 ? (winTrades.length / trades.length) * 100 : 0
    const avgWin = winTrades.length > 0
      ? winTrades.reduce((s, t) => s + (t.pnl_usdt ?? 0), 0) / winTrades.length
      : 0
    const avgLoss = lossTrades.length > 0
      ? Math.abs(lossTrades.reduce((s, t) => s + (t.pnl_usdt ?? 0), 0) / lossTrades.length)
      : 0

    // Max drawdown from equity curve
    let peak = PORTFOLIO_START
    let maxDrawdown = 0
    for (const p of curve) {
      if (p.equity > peak) peak = p.equity
      const dd = (peak - p.equity) / peak
      if (dd > maxDrawdown) maxDrawdown = dd
    }

    return NextResponse.json({
      curve,
      snapshots,
      stats: {
        start_equity: PORTFOLIO_START,
        current_equity: +equity.toFixed(2),
        total_pnl: +totalPnl.toFixed(2),
        total_pnl_pct: +(totalPnl / PORTFOLIO_START * 100).toFixed(2),
        daily_pnl: dailyPnlRaw ? parseFloat(dailyPnlRaw) : 0,
        total_trades: trades.length,
        win_rate: +winRate.toFixed(1),
        avg_win_usdt: +avgWin.toFixed(2),
        avg_loss_usdt: +avgLoss.toFixed(2),
        profit_factor: avgLoss > 0 ? +(avgWin / avgLoss).toFixed(2) : null,
        max_drawdown_pct: +(maxDrawdown * 100).toFixed(2),
      },
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    await redis.quit()
  }
}
