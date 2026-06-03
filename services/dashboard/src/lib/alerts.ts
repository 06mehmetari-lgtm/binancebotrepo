/** Unified alert scoring and types for AlertPanel / SmartAlerts */

export type AlertLevel = 'info' | 'success' | 'warning' | 'critical'

export interface DashboardAlert {
  id: string
  type: string
  title: string
  body: string
  level: AlertLevel
  ts: number
  symbol?: string
  direction?: string
  confidence?: number
  priority: number
  actions?: AlertAction[]
}

export interface AlertAction {
  id: string
  label: string
  variant?: 'primary' | 'danger' | 'ghost'
  href?: string
  command?: {
    action: string
    symbol?: string
    direction?: string
    confidence?: number
  }
}

export function alertPriority(p: {
  sqs?: number
  confidence?: number
  regimeBonus?: number
  urgency?: number
}): number {
  const sqs = (p.sqs ?? 0) / 100
  const conf = p.confidence ?? 0
  const regime = p.regimeBonus ?? 0
  const urg = p.urgency ?? 0
  return Math.round((sqs * 0.4 + conf * 0.3 + regime * 0.2 + urg * 0.1) * 100)
}

export function levelFromPriority(score: number): AlertLevel {
  if (score >= 85) return 'critical'
  if (score >= 60) return 'warning'
  if (score >= 40) return 'success'
  return 'info'
}

export function alertFromSignal(symbol: string, direction: string, confidence: number, sqs?: number): DashboardAlert {
  const priority = alertPriority({
    sqs: sqs ?? confidence * 100,
    confidence,
    regimeBonus: direction !== 'flat' ? 0.2 : 0,
    urgency: confidence >= 0.8 ? 0.3 : 0.1,
  })
  return {
    id: `signal-${symbol}-${Math.floor(Date.now() / 1000)}`,
    type: 'signal',
    title: `${direction === 'long' ? '▲ LONG' : '▼ SHORT'} — ${symbol}`,
    body: `Güven ${Math.round(confidence * 100)}%${sqs != null ? ` · SQS ${sqs}` : ''}`,
    level: levelFromPriority(priority),
    ts: Date.now() / 1000,
    symbol,
    direction,
    confidence,
    priority,
    actions: [
      { id: 'coin', label: 'Detay', href: `/coin/${symbol}` },
      {
        id: 'force',
        label: 'Sinyal yaz',
        variant: 'primary',
        command: { action: 'force_signal', symbol, direction, confidence },
      },
    ],
  }
}

export function alertFromGuard(symbol: string, body: string): DashboardAlert {
  const priority = alertPriority({ urgency: 0.9, confidence: 0.7 })
  return {
    id: `guard-${symbol}-${Math.floor(Date.now() / 1000)}`,
    type: 'guard',
    title: `Guard — ${symbol}`,
    body,
    level: 'critical',
    ts: Date.now() / 1000,
    symbol,
    priority,
    actions: [
      { id: 'close', label: 'Kapat', variant: 'danger', command: { action: 'close_symbol', symbol } },
      { id: 'coin', label: 'Detay', href: `/coin/${symbol}` },
    ],
  }
}

export async function runLearningCommand(body: Record<string, unknown>): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch('/api/learning/command', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const j = await res.json().catch(() => ({}))
  return { ok: res.ok, message: (j as { message?: string }).message ?? (j as { error?: string }).error }
}
