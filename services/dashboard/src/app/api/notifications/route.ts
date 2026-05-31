import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

export interface Notification {
  id: string
  type: string
  title: string
  body: string
  level: 'info' | 'success' | 'warning' | 'critical'
  ts: number
  symbol?: string
}

function formatEvent(raw: string): Notification | null {
  try {
    const e = JSON.parse(raw)
    const ts = e.time ?? e.ts ?? Date.now() / 1000
    const id = `${ts}-${e.type}-${e.symbol ?? ''}`

    switch (e.type) {
      case 'signal': {
        if (!e.symbol || e.direction === 'flat') return null
        const conf = Math.round((e.confidence ?? 0) * 100)
        return {
          id, type: 'signal', ts, symbol: e.symbol,
          title: `${e.direction === 'long' ? '▲ LONG' : '▼ SHORT'} Signal — ${e.symbol}`,
          body: `Confidence ${conf}% · ${e.regime ?? ''} regime · source: ${e.source ?? 'signal_engine'}`,
          level: conf >= 80 ? 'success' : conf >= 70 ? 'info' : 'warning',
        }
      }
      case 'rsi_alert':
        return {
          id, type: 'rsi_alert', ts, symbol: e.symbol,
          title: `RSI Alert — ${e.symbol}`,
          body: `${e.label ?? 'RSI extreme'} · RSI = ${e.rsi ?? '—'}`,
          level: (e.rsi ?? 50) < 25 || (e.rsi ?? 50) > 75 ? 'warning' : 'info',
        }
      case 'regime_change':
        return {
          id, type: 'regime_change', ts, symbol: e.symbol,
          title: `Regime Change — ${e.symbol ?? 'Market'}`,
          body: `${e.prev_regime ?? '?'} → ${e.regime ?? '?'}`,
          level: (e.regime === 'volatile' || e.regime === 'trending_down') ? 'warning' : 'info',
        }
      case 'scan_summary':
        return {
          id, type: 'scan_summary', ts,
          title: 'Scan Complete',
          body: `${e.total ?? 0} symbols · ▲ ${e.long ?? 0} long · ▼ ${e.short ?? 0} short`,
          level: 'info',
        }
      default:
        return null
    }
  } catch {
    return null
  }
}

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.lrange('activity:feed', 0, 49)
    const notifications = raw
      .map(formatEvent)
      .filter(Boolean)
      .slice(0, 20) as Notification[]

    return NextResponse.json(notifications)
  } finally {
    await redis.quit()
  }
}
