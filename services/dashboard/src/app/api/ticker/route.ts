import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const FALLBACK = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT']
const MAX_SYMBOLS = 20

async function resolveWatchList(redis: ReturnType<typeof createRedis>): Promise<string[]> {
  try {
    const keys = await redis.keys('signal:latest:*')
    if (keys && keys.length > 0) {
      const syms = keys
        .map((k: string) => k.replace('signal:latest:', '').toUpperCase())
        .filter((s: string) => s.length > 0)
        .sort()
        .slice(0, MAX_SYMBOLS)
      if (syms.length > 0) return syms
    }
  } catch { /* ignore */ }
  return FALLBACK
}

export async function GET() {
  const redis = createRedis()
  try {
    const watch = await resolveWatchList(redis)

    const [tickerRaws, signalRaws] = await Promise.all([
      Promise.all(watch.map((s: string) => redis.get(`binance:ticker:${s.toLowerCase()}`))),
      Promise.all(watch.map((s: string) => redis.get(`signal:latest:${s}`))),
    ])

    const result: Record<string, {
      price: number | null
      bid: number | null
      ask: number | null
      direction: string
      confidence: number
      live: boolean
    }> = {}

    watch.forEach((sym: string, i: number) => {
      const tickerRaw = tickerRaws[i]
      const signalRaw = signalRaws[i]

      let bid = 0, ask = 0
      if (tickerRaw) {
        try {
          const t = JSON.parse(tickerRaw)
          const d = t.data ?? t
          bid = parseFloat(d.b ?? 0)
          ask = parseFloat(d.a ?? bid)
        } catch { /* ignore */ }
      }

      const signal = signalRaw ? JSON.parse(signalRaw) : null

      result[sym] = {
        price: bid > 0 && ask > 0 ? +((bid + ask) / 2).toFixed(4) : null,
        bid: bid || null,
        ask: ask || null,
        direction: signal?.direction ?? 'flat',
        confidence: signal?.confidence ?? 0,
        live: bid > 0,
      }
    })

    return NextResponse.json(result)
  } finally {
    await redis.quit()
  }
}
