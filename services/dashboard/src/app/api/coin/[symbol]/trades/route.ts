import { NextResponse } from 'next/server'
import { getRedis } from '@/lib/redis'

export const dynamic = 'force-dynamic'

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ symbol: string }> }
) {
  const { symbol } = await params
  const sym = symbol.toUpperCase().replace(/[^A-Z0-9]/g, '')
  if (!sym) {
    return NextResponse.json({ error: 'invalid symbol' }, { status: 400 })
  }

  const redis = getRedis()
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

  trades.sort((a, b) => Number(b.timestamp ?? 0) - Number(a.timestamp ?? 0))

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
}
