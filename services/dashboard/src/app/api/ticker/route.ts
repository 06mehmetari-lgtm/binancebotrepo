import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

function featureClose(raw: string | null): number {
  const f = safeJson(raw) as { close?: number } | null
  const c = parseFloat(String(f?.close ?? 0))
  return c > 0 ? c : 0
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
      pipeline.get(`features:latest:${sym}`)
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
      const tickerRaw = results?.[i * 3]?.[1] as string | null
      const signalRaw = results?.[i * 3 + 1]?.[1] as string | null
      const featRaw = results?.[i * 3 + 2]?.[1] as string | null

      let bid = 0, ask = 0
      if (tickerRaw) {
        try {
          const t = safeJson(tickerRaw) as Record<string, unknown>
          const d = (t?.data ?? t) as Record<string, unknown>
          bid = parseFloat(String(d.b ?? d.bid ?? 0))
          ask = parseFloat(String(d.a ?? d.ask ?? bid))
        } catch { /* ignore */ }
      }

      const featClose = featureClose(featRaw)
      if (bid <= 0 && featClose > 0) {
        bid = featClose
        ask = featClose
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
      .sort((a, b) => {
        const aDir = a.direction !== 'flat' ? 1 : 0
        const bDir = b.direction !== 'flat' ? 1 : 0
        if (bDir !== aDir) return bDir - aDir
        return Math.abs(b.confidence) - Math.abs(a.confidence)
      })
      .slice(0, 15)

    const deployRaw = await redis.get('system:deploy:version')
    let deploy: Record<string, unknown> | null = null
    if (deployRaw) {
      try { deploy = JSON.parse(deployRaw) } catch { deploy = null }
    }

    const result: Record<string, unknown> = {
      _meta: {
        total: entries.length,
        active,
        top_nav: topNav.map(e => e.symbol),
        deploy,
      },
    }
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
