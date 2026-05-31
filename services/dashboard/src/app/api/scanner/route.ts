import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

function safe(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

export async function GET() {
  const redis = createRedis()
  try {
    const [featKeys, wsRaw] = await Promise.all([
      redis.keys('features:latest:*'),
      redis.get('ws:status'),
    ])

    if (featKeys.length === 0) {
      return NextResponse.json({ coins: [], total: 0, long_count: 0, short_count: 0, flat_count: 0, ws_status: null })
    }

    const symbols = featKeys.map(k => (k as string).replace('features:latest:', ''))

    const pipeline = redis.pipeline()
    for (const sym of symbols) pipeline.get(`features:latest:${sym}`)
    for (const sym of symbols) pipeline.get(`signal:latest:${sym}`)
    const results = await pipeline.exec()

    const half = symbols.length
    const coins: Record<string, unknown>[] = []

    for (let i = 0; i < symbols.length; i++) {
      const f = safe(results?.[i]?.[1] as string | null)
      if (!f) continue
      const s = safe(results?.[half + i]?.[1] as string | null) ?? {}

      const direction = (s.direction as string) || 'flat'
      const confidence = typeof s.confidence === 'number' ? s.confidence : 0
      const rsi = typeof f.rsi_14 === 'number' ? f.rsi_14 : null
      const macdHist = typeof f.macd_hist === 'number' ? f.macd_hist : null
      const bbPos = typeof f.bb_position === 'number' ? f.bb_position : null
      const atrPct = typeof f.atr_pct === 'number' ? f.atr_pct : null
      const volRatio = typeof f.volume_ratio === 'number' ? f.volume_ratio : null
      const drift = typeof f.drift_status === 'string' ? f.drift_status : 'STABLE'
      const regime = (s.regime as string) || (f.regime as string) || null
      const ts = typeof f.timestamp === 'number' ? f.timestamp : null

      coins.push({
        symbol: symbols[i],
        direction,
        confidence,
        rsi,
        macd_hist: macdHist,
        bb_position: bbPos,
        atr_pct: atrPct,
        volume_ratio: volRatio,
        drift,
        regime,
        timestamp: ts,
      })
    }

    // Active signals first, then by confidence desc
    coins.sort((a, b) => {
      const ad = a.direction as string
      const bd = b.direction as string
      if (ad !== 'flat' && bd === 'flat') return -1
      if (ad === 'flat' && bd !== 'flat') return 1
      return (b.confidence as number) - (a.confidence as number)
    })

    const ws_status = safe(wsRaw)

    return NextResponse.json({
      coins,
      total: coins.length,
      long_count: coins.filter(c => c.direction === 'long').length,
      short_count: coins.filter(c => c.direction === 'short').length,
      flat_count: coins.filter(c => c.direction === 'flat').length,
      ws_status,
      server_time: Date.now(),
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
