import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const WATCH = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT']

export async function GET() {
  const redis = createRedis()
  try {
    const [tickerRaws, signalRaws] = await Promise.all([
      Promise.all(WATCH.map(s => redis.get(`binance:ticker:${s.toLowerCase()}`))),
      Promise.all(WATCH.map(s => redis.get(`signal:latest:${s}`))),
    ])

    const result: Record<string, {
      price: number | null
      bid: number | null
      ask: number | null
      direction: string
      confidence: number
      live: boolean
    }> = {}

    WATCH.forEach((sym, i) => {
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
