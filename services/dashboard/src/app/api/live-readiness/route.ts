import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

// Shadow promotion criteria (from promotion_engine.py)
const TARGETS = {
  trades:    100,
  winRate:   0.52,
  sharpe:    1.5,
  maxDrawdown: 0.10,  // must be BELOW this
}

interface Lesson {
  symbol?: string
  side?: string
  direction?: string
  pnl_pct?: number
  outcome?: string
  close_reason?: string
  confidence?: number
  regime?: string
  ts?: number
  lesson?: string
  category?: string
}

function pct(val: number, target: number, invert = false): number {
  if (invert) return Math.min(100, Math.max(0, (1 - val / target) * 100))
  return Math.min(100, Math.max(0, (val / target) * 100))
}

export async function GET() {
  const redis = createRedis()
  try {
    const [leaderRaw, lessonsRaw, shadowStatsRaw] = await Promise.all([
      redis.get('shadow:leaderboard'),
      redis.lrange('training:lessons', 0, 499),
      redis.get('shadow:stats'),
    ])

    // ── Parse leaderboard (best strategy's stats) ─────────────────────────────
    let bestSharpe = 0, bestWinRate = 0, bestDrawdown = 0, bestTrades = 0
    let leaderSymbol = '—'
    if (leaderRaw) {
      try {
        const lb = JSON.parse(leaderRaw)
        const strategies = Array.isArray(lb) ? lb : []
        for (const s of strategies) {
          const trades = Number(s.trades ?? s.total_trades ?? 0)
          const wr = Number(s.win_rate ?? 0)
          const sh = Number(s.sharpe ?? 0)
          const dd = Number(s.max_drawdown ?? s.drawdown ?? 0)
          if (sh > bestSharpe) {
            bestSharpe = sh; bestWinRate = wr; bestDrawdown = dd
            bestTrades = trades; leaderSymbol = s.symbol ?? s.strategy ?? '—'
          }
        }
      } catch { /* ignore */ }
    }

    // ── Parse shadow stats (aggregate) ────────────────────────────────────────
    let totalTrades = bestTrades, totalWinRate = bestWinRate
    let totalSharpe = bestSharpe, totalMaxDD = bestDrawdown
    if (shadowStatsRaw) {
      try {
        const ss = JSON.parse(shadowStatsRaw)
        totalTrades   = Number(ss.total_trades   ?? ss.trades    ?? totalTrades)
        totalWinRate  = Number(ss.win_rate        ?? totalWinRate)
        totalSharpe   = Number(ss.sharpe          ?? totalSharpe)
        totalMaxDD    = Number(ss.max_drawdown    ?? ss.drawdown  ?? totalMaxDD)
      } catch { /* ignore */ }
    }

    // ── Parse training lessons for trade history ───────────────────────────────
    const lessons: Lesson[] = lessonsRaw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)

    const trades = lessons.filter(l => l.outcome === 'WIN' || l.outcome === 'LOSS' || typeof l.pnl_pct === 'number')

    // Compute from lessons if shadow stats not available
    if (trades.length > 0 && totalTrades === 0) {
      totalTrades = trades.length
      const wins = trades.filter(t => (t.outcome === 'WIN') || (Number(t.pnl_pct) > 0)).length
      totalWinRate = wins / trades.length
      const pnls = trades.map(t => Number(t.pnl_pct ?? 0)).filter(p => p !== 0)
      if (pnls.length > 1) {
        const mean = pnls.reduce((a, b) => a + b, 0) / pnls.length
        const std = Math.sqrt(pnls.map(p => (p - mean) ** 2).reduce((a, b) => a + b, 0) / pnls.length)
        totalSharpe = std > 0 ? (mean / std) * Math.sqrt(252) : 0
      }
      // Max drawdown from cumulative returns
      let peak = 0, equity = 0, maxDD = 0
      for (const p of pnls) {
        equity += p
        if (equity > peak) peak = equity
        const dd = peak > 0 ? (peak - equity) / peak : 0
        if (dd > maxDD) maxDD = dd
      }
      totalMaxDD = maxDD
    }

    // ── Progress scores ────────────────────────────────────────────────────────
    const progTrades   = pct(totalTrades, TARGETS.trades)
    const progWinRate  = pct(totalWinRate, TARGETS.winRate)
    const progSharpe   = pct(totalSharpe, TARGETS.sharpe)
    const progDrawdown = pct(totalMaxDD, TARGETS.maxDrawdown, true)  // lower is better

    // Overall = weighted average (drawdown only counts if we have trades)
    const hasData = totalTrades > 0
    const overall = hasData
      ? Math.round((progTrades * 0.3 + progWinRate * 0.25 + progSharpe * 0.3 + progDrawdown * 0.15))
      : 0

    // ── Recent trade history (last 30) ────────────────────────────────────────
    const recentTrades = trades.slice(0, 30).map(t => ({
      symbol:      t.symbol ?? '—',
      direction:   (t.side ?? t.direction ?? 'long').toLowerCase(),
      pnl_pct:     Number(t.pnl_pct ?? 0),
      outcome:     t.outcome ?? (Number(t.pnl_pct) > 0 ? 'WIN' : 'LOSS'),
      reason:      t.close_reason ?? '—',
      confidence:  Number(t.confidence ?? 0),
      regime:      t.regime ?? '—',
      lesson:      t.lesson ?? null,
      ts:          Number(t.ts ?? 0),
    }))

    // ── Win/loss breakdown by reason ─────────────────────────────────────────
    const byReason: Record<string, { wins: number; losses: number }> = {}
    for (const t of trades) {
      const r = t.close_reason ?? 'unknown'
      if (!byReason[r]) byReason[r] = { wins: 0, losses: 0 }
      const isWin = t.outcome === 'WIN' || Number(t.pnl_pct) > 0
      if (isWin) byReason[r].wins++; else byReason[r].losses++
    }

    return NextResponse.json({
      overall,
      criteria: {
        trades:      { value: totalTrades,                   target: TARGETS.trades,      progress: Math.round(progTrades),   label: 'Trade Sayısı',    unit: '' },
        winRate:     { value: Math.round(totalWinRate * 100), target: Math.round(TARGETS.winRate * 100), progress: Math.round(progWinRate), label: 'Kazanma Oranı', unit: '%' },
        sharpe:      { value: Math.round(totalSharpe * 100) / 100, target: TARGETS.sharpe, progress: Math.round(progSharpe), label: 'Sharpe Oranı',    unit: '' },
        maxDrawdown: { value: Math.round(totalMaxDD * 100),  target: Math.round(TARGETS.maxDrawdown * 100), progress: Math.round(progDrawdown), label: 'Maks. Drawdown', unit: '%', invert: true },
      },
      bestStrategy: leaderSymbol,
      recentTrades,
      byReason,
      totalTrades,
      totalWins: trades.filter(t => t.outcome === 'WIN' || Number(t.pnl_pct) > 0).length,
      totalLosses: trades.filter(t => t.outcome === 'LOSS' || Number(t.pnl_pct) <= 0).length,
      totalPnl: Math.round(trades.reduce((s, t) => s + Number(t.pnl_pct ?? 0), 0) * 100) / 100,
    })
  } finally {
    redis.disconnect()
  }
}
