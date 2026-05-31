import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const [resultsRaw, statusRaw, triggerRaw, logsRaw] = await Promise.all([
      redis.get('backtest:results'),
      redis.get('backtest:status'),
      redis.get('backtest:trigger'),
      redis.lrange('backtest:log', 0, 299),
    ])

    const logs = (logsRaw as string[])
      .map(l => { try { return JSON.parse(l) } catch { return null } })
      .filter(Boolean)
      .reverse()  // oldest first — chronological terminal order

    return NextResponse.json({
      results: resultsRaw ? JSON.parse(resultsRaw as string) : null,
      status: statusRaw ? JSON.parse(statusRaw as string) : null,
      trigger_pending: !!triggerRaw,
      logs,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}

// POST — queue a fresh backtest run
export async function POST() {
  const redis = createRedis()
  try {
    // Set trigger key — backtest service polls for this every 60s.
    // Old results/status are NOT deleted — they remain visible until the new run completes.
    await redis.set('backtest:trigger', '1', 'EX', 300)
    return NextResponse.json({ triggered: true, message: 'Backtest queued — results will appear in ~5-10 minutes' })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
