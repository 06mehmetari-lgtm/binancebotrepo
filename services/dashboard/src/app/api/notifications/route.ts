import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export interface Notification {
  id: string
  type: string
  title: string
  body: string
  level: 'info' | 'success' | 'warning' | 'critical'
  ts: number
  symbol?: string
  direction?: string
  confidence?: number
}

function formatEvent(raw: string): Notification | null {
  try {
    const e = JSON.parse(raw)
    const ts = e.time ?? e.ts ?? Date.now() / 1000
    const id = `${ts}-${e.type}-${e.symbol ?? ''}`

    switch (e.type) {
      case 'signal':
      case 'manual_signal': {
        if (!e.symbol || e.direction === 'flat') return null
        const confRaw = Number(e.confidence ?? 0)
        const conf = confRaw <= 1 ? confRaw : confRaw / 100
        return {
          id, type: e.type, ts, symbol: e.symbol,
          direction: e.direction,
          confidence: conf,
          title: `${e.direction === 'long' ? '▲ LONG' : '▼ SHORT'} Signal — ${e.symbol}`,
          body: `Confidence ${Math.round(conf * 100)}% · ${e.regime ?? ''} regime · source: ${e.source ?? 'signal_engine'}`,
          level: conf >= 0.8 ? 'success' : conf >= 0.7 ? 'info' : 'warning',
        }
      }
      case 'autopsy':
        return {
          id, type: 'autopsy', ts, symbol: e.symbol,
          title: e.title ?? `Autopsy — ${e.symbol ?? '?'}`,
          body: e.body ?? '',
          level: (e.level as Notification['level']) ?? 'warning',
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
