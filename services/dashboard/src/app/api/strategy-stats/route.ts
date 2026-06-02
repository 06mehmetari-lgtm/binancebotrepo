import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

interface Lesson {
  symbol: string
  side: string
  pnl_pct: number
  outcome: string
  close_reason: string
  confidence: number
  regime: string
  hold_seconds?: number
  ts: number
}

interface CellStats { wins: number; losses: number }

function cell(): CellStats { return { wins: 0, losses: 0 } }

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.lrange('training:lessons', 0, 499)
    const lessons: Lesson[] = raw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)

    if (lessons.length === 0) {
      return NextResponse.json({ lessons_count: 0, regimes: [], grid: {}, symbols: [], strategy_doc: null })
    }

    // Regime × side heat map
    const regimes = Array.from(new Set(lessons.map(l => l.regime || 'unknown'))).sort()
    const sides = ['long', 'short']

    const grid: Record<string, Record<string, CellStats>> = {}
    for (const regime of regimes) {
      grid[regime] = {}
      for (const side of sides) {
        grid[regime][side] = cell()
      }
    }

    // Overall close-reason breakdown
    const byReason: Record<string, CellStats> = {}
    // Confidence buckets
    const confBuckets: Record<string, CellStats> = {
      '<60%': cell(), '60-70%': cell(), '70-80%': cell(), '80%+': cell(),
    }
    // Symbol leaderboard
    const bySymbol: Record<string, CellStats> = {}

    for (const l of lessons) {
      const regime = l.regime || 'unknown'
      const side = (l.side || 'long').toLowerCase()
      const isWin = l.outcome === 'WIN'

      if (grid[regime]?.[side]) {
        if (isWin) grid[regime][side].wins++
        else grid[regime][side].losses++
      }

      const reason = l.close_reason || 'unknown'
      if (!byReason[reason]) byReason[reason] = cell()
      if (isWin) byReason[reason].wins++
      else byReason[reason].losses++

      const conf = l.confidence || 0
      const bucket = conf < 0.6 ? '<60%' : conf < 0.7 ? '60-70%' : conf < 0.8 ? '70-80%' : '80%+'
      if (isWin) confBuckets[bucket].wins++
      else confBuckets[bucket].losses++

      if (!bySymbol[l.symbol]) bySymbol[l.symbol] = cell()
      if (isWin) bySymbol[l.symbol].wins++
      else bySymbol[l.symbol].losses++
    }

    const wins = lessons.filter(l => l.outcome === 'WIN').length
    const avgPnl = lessons.reduce((s, l) => s + (l.pnl_pct || 0), 0) / lessons.length
    const avgHold = lessons.filter(l => l.hold_seconds).reduce((s, l) => s + (l.hold_seconds || 0), 0)
      / (lessons.filter(l => l.hold_seconds).length || 1)

    // Top 5 symbols by trade count
    const symbols = Object.entries(bySymbol)
      .sort((a, b) => (b[1].wins + b[1].losses) - (a[1].wins + a[1].losses))
      .slice(0, 8)
      .map(([sym, s]) => ({
        symbol: sym,
        wins: s.wins,
        losses: s.losses,
        win_rate: s.wins + s.losses > 0 ? s.wins / (s.wins + s.losses) : 0,
      }))

    // Latest AI strategy doc
    let strategy_doc: string | null = null
    const docsRaw = await redis.get('training:docs')
    if (docsRaw) {
      const docs = JSON.parse(docsRaw)
      const aiDoc = docs.find((d: { title?: string }) => d?.title?.startsWith('AI Öğrenilmiş Strateji'))
      if (aiDoc) strategy_doc = aiDoc.content || null
    }

    return NextResponse.json({
      lessons_count: lessons.length,
      wins,
      losses: lessons.length - wins,
      win_rate: wins / lessons.length,
      avg_pnl: avgPnl,
      avg_hold_hours: avgHold / 3600,
      regimes,
      sides,
      grid,
      by_reason: byReason,
      conf_buckets: confBuckets,
      symbols,
      strategy_doc,
    })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
