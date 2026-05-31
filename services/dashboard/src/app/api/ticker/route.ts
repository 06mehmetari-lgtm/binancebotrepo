import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

/** All symbols with live ticker; nav shows top movers by signal confidence. */
export async function GET() {
  const redis = createRedis()
  try {
    const keys = await redis.keys('binance:ticker:*')
    const symbols = keys
      .map(k => k.replace('binance:ticker:', '').toUpperCase())
      .filter(s => s.endsWith('USDT'))
      .sort()

    if (!symbols.length) {
      const featKeys = await redis.keys('features:latest:*')
      symbols.push(...featKeys.map(k => k.replace('features:latest:', '')).sort())
    }

    const pipeline = redis.pipeline()
    for (const sym of symbols) {
      pipeline.get(`binance:ticker:${sym.toLowerCase()}`)
      pipeline.get(`signal:latest:${sym}`)
    }
    const results = await pipeline.exec()

    const entries: Array<{
      symbol: string
      price: number | null
      bid: number | null
      ask: number | null
      direction: string
      confidence: number
      live: boolean
    }> = []

    for (let i = 0; i < symbols.length; i++) {
      const sym = symbols[i]
      const tickerRaw = results?.[i * 2]?.[1] as string | null
      const signalRaw = results?.[i * 2 + 1]?.[1] as string | null

      let bid = 0, ask = 0
      if (tickerRaw) {
        try {
          const t = safeJson(tickerRaw) as Record<string, unknown>
          const d = (t?.data ?? t) as Record<string, unknown>
          bid = parseFloat(String(d.b ?? 0))
          ask = parseFloat(String(d.a ?? bid))
        } catch { /* ignore */ }
      }

      const signal = safeJson(signalRaw) as { direction?: string; confidence?: number } | null

      entries.push({
        symbol: sym,
        price: bid > 0 && ask > 0 ? +((bid + ask) / 2).toFixed(6) : null,
        bid: bid || null,
        ask: ask || null,
        direction: signal?.direction ?? 'flat',
        confidence: signal?.confidence ?? 0,
        live: bid > 0,
      })
    }

    const active = entries.filter(e => e.live).length
    const topNav = [...entries]
      .filter(e => e.live)
      .sort((a, b) => Math.abs(b.confidence) - Math.abs(a.confidence))
      .slice(0, 15)

    const result: Record<string, unknown> = { _meta: { total: entries.length, active, top_nav: topNav.map(e => e.symbol) } }
    for (const e of entries) {
      result[e.symbol] = {
        price: e.price,
        bid: e.bid,
        ask: e.ask,
        direction: e.direction,
        confidence: e.confidence,
        live: e.live,
      }
    }

    return NextResponse.json(result)
  } finally {
    await redis.disconnect()
  }
}
