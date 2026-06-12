import { NextResponse } from 'next/server'
import { createRedis } from '../../../_redis'

export const dynamic = 'force-dynamic'

function tradeTs(t: Record<string, unknown>): number {
  return Number(t.closed_at ?? t.timestamp ?? 0)
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ symbol: string }> }
) {
  const { symbol } = await params
  const sym = symbol.toUpperCase().replace(/[^A-Z0-9]/g, '')
  if (!sym) {
    return NextResponse.json({ error: 'invalid symbol' }, { status: 400 })
  }

  const redis = createRedis()
  try {
    const raw = await redis.lrange('oms:trade_history', 0, 4999)
    const trades: Record<string, unknown>[] = []

    for (const line of raw) {
      try {
        const t = JSON.parse(line) as Record<string, unknown>
        if (String(t.symbol ?? '').toUpperCase() === sym) {
          trades.push(t)
        }
      } catch {
        /* skip */
      }
    }

    trades.sort((a, b) => tradeTs(b) - tradeTs(a))

    const posRaw = await redis.get(`oms:position:${sym}`)
    let position: Record<string, unknown> | null = null
    if (posRaw) {
      try {
        position = JSON.parse(posRaw)
      } catch {
        position = null
      }
    }

    return NextResponse.json({
      symbol: sym,
      trades: trades.slice(0, 200),
      position,
      count: trades.length,
    })
  } finally {
    redis.disconnect()
  }
}
