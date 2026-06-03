'use client'

import { useCallback, useRef, useState } from 'react'
import {
  type DashboardAlert,
  runLearningCommand,
  alertFromGuard,
  alertFromSignal,
} from '@/lib/alerts'
import { useStreamInvalidate } from '@/hooks/useStream'
import type { StreamEvent } from '@/lib/stream-events'

const LEVEL_BORDER: Record<string, string> = {
  critical: 'border-red-500/50',
  warning: 'border-yellow-500/50',
  success: 'border-green-500/50',
  info: 'border-gray-600',
}

async function persistAlert(alert: DashboardAlert) {
  try {
    await fetch('/api/alerts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(alert),
    })
  } catch {
    /* ignore */
  }
}

export default function AlertPanel() {
  const [alerts, setAlerts] = useState<DashboardAlert[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const seenRef = useRef(new Set<string>())

  const pushAlert = useCallback((a: DashboardAlert) => {
    if (seenRef.current.has(a.id)) return
    seenRef.current.add(a.id)
    setAlerts(prev => [a, ...prev].slice(0, 8))
    void persistAlert(a)
  }, [])

  const onStream = useCallback(
    async (ev: StreamEvent) => {
      if (ev.hint === 'guard' && ev.symbol) {
        pushAlert(alertFromGuard(ev.symbol, 'Position guard tetiklendi'))
        return
      }
      if (ev.hint === 'signal' && ev.symbol) {
        try {
          const coin = await fetch(`/api/coin/${ev.symbol}`).then(r => r.json())
          const row = coin?.signal as { direction?: string; confidence?: number } | null
          if (row?.direction && row.direction !== 'flat' && (row.confidence ?? 0) >= 0.75) {
            pushAlert(alertFromSignal(ev.symbol, row.direction, row.confidence ?? 0))
          }
        } catch {
          /* ignore */
        }
      }
    },
    [pushAlert]
  )

  useStreamInvalidate({
    hints: ['guard', 'signal', 'emergency'],
    debounceMs: 400,
    onEvent: onStream,
  })

  const runAction = async (alert: DashboardAlert, actionId: string) => {
    const act = alert.actions?.find(a => a.id === actionId)
    if (!act) return
    if (act.href) {
      window.location.href = act.href
      return
    }
    if (!act.command) return
    setBusy(`${alert.id}-${actionId}`)
    await runLearningCommand(act.command as Record<string, unknown>)
    setBusy(null)
  }

  if (alerts.length === 0) return null

  return (
    <div className="fixed bottom-4 left-4 z-[9998] flex flex-col gap-2 max-w-sm pointer-events-none">
      {alerts.map(a => (
        <div
          key={a.id}
          className={`pointer-events-auto rounded-xl border bg-gray-900/95 backdrop-blur p-3 shadow-xl ${LEVEL_BORDER[a.level] ?? 'border-gray-700'}`}
        >
          <div className="flex justify-between gap-2">
            <div>
              <p className="text-white text-sm font-bold">{a.title}</p>
              <p className="text-gray-400 text-xs mt-0.5">{a.body}</p>
              <p className="text-gray-600 text-[10px] mt-1">Öncelik {a.priority}</p>
            </div>
            <button
              type="button"
              className="text-gray-500 hover:text-white text-xs"
              onClick={() => setAlerts(p => p.filter(x => x.id !== a.id))}
            >
              ✕
            </button>
          </div>
          {a.actions && a.actions.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {a.actions.map(act => (
                <button
                  key={act.id}
                  type="button"
                  disabled={busy === `${a.id}-${act.id}`}
                  onClick={() => runAction(a, act.id)}
                  className={`text-xs px-2 py-1 rounded border transition-colors ${
                    act.variant === 'danger'
                      ? 'border-red-700 text-red-300 hover:bg-red-950'
                      : act.variant === 'primary'
                        ? 'border-orange-600 text-orange-300 hover:bg-orange-950'
                        : 'border-gray-600 text-gray-300 hover:bg-gray-800'
                  }`}
                >
                  {act.label}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
