import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const [resultsRaw, statusRaw] = await Promise.all([
      redis.get('backtest:results'),
      redis.get('backtest:status'),
    ])
    return NextResponse.json({
      results: resultsRaw ? JSON.parse(resultsRaw as string) : null,
      status: statusRaw ? JSON.parse(statusRaw as string) : null,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}

// POST — trigger a fresh backtest run
export async function POST() {
  const redis = createRedis()
  try {
    // Set trigger key — backtest service polls for this every 60s
    await redis.set('backtest:trigger', '1', 'EX', 300)
    await redis.del('backtest:results')
    await redis.del('backtest:status')
    return NextResponse.json({ triggered: true, message: 'Backtest queued — results will appear in ~5-10 minutes' })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
