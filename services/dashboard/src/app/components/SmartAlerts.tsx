'use client'
import { useEffect, useRef, useState, useCallback } from 'react'

interface Alert {
  id: string
  symbol: string
  direction: string
  confidence: number
  body: string
  ts: number
}

const DIR_COLOR: Record<string, string> = {
  long: 'border-green-500/60 bg-green-950/80',
  short: 'border-red-500/60 bg-red-950/80',
}
const DIR_ICON: Record<string, string> = { long: '▲', short: '▼' }
const DIR_TEXT: Record<string, string> = { long: 'text-green-400', short: 'text-red-400' }

export default function SmartAlerts() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const seenIds = useRef<Set<string>>(new Set())
  const permAsked = useRef(false)

  const requestPermission = useCallback(async () => {
    if (permAsked.current) return
    permAsked.current = true
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      await Notification.requestPermission()
    }
  }, [])

  const fireNativeNotif = useCallback((a: Alert) => {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
    try {
      const n = new Notification(`⚡ ${a.symbol} ${a.direction.toUpperCase()}`, {
        body: `${Math.round(a.confidence * 100)}% güven · ${a.body}`,
        icon: '/favicon.ico',
        tag: a.id,
      })
      n.onclick = () => { window.location.href = `/coin/${a.symbol}`; n.close() }
      setTimeout(() => n.close(), 8000)
    } catch { /* denied or unsupported */ }
  }, [])

  const pollSignals = useCallback(async () => {
    try {
      const data = await fetch('/api/notifications').then(r => r.json())
      if (!Array.isArray(data)) return

      const highConf = data.filter(
        (n: { confidence?: number; symbol?: string; direction?: string; level?: string }) =>
          n.confidence != null && n.confidence >= 0.80 &&
          n.symbol && n.direction && n.direction !== 'flat'
      )

      for (const n of highConf) {
        const id = `${n.symbol}-${n.ts ?? Date.now()}`
        if (seenIds.current.has(id)) continue
        seenIds.current.add(id)

        const alert: Alert = {
          id,
          symbol: n.symbol,
          direction: n.direction,
          confidence: n.confidence,
          body: n.body ?? '',
          ts: n.ts ?? Date.now() / 1000,
        }

        setAlerts(prev => [alert, ...prev].slice(0, 5))
        fireNativeNotif(alert)

        // Auto-dismiss after 8s
        setTimeout(() => {
          setAlerts(prev => prev.filter(a => a.id !== id))
        }, 8000)
      }
    } catch { /* ignore */ }
  }, [fireNativeNotif])

  useEffect(() => {
    requestPermission()
    pollSignals()
    const t = setInterval(pollSignals, 30000)
    return () => clearInterval(t)
  }, [pollSignals, requestPermission])

  if (alerts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      {alerts.map(a => (
        <div
          key={a.id}
          onClick={() => { window.location.href = `/coin/${a.symbol}` }}
          className={`pointer-events-auto w-72 rounded-xl border backdrop-blur-sm shadow-2xl p-3 cursor-pointer
            transition-all duration-300 hover:scale-[1.02] ${DIR_COLOR[a.direction] ?? 'border-gray-700 bg-gray-900/90'}`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className={`text-lg font-black ${DIR_TEXT[a.direction] ?? 'text-gray-400'}`}>
                {DIR_ICON[a.direction] ?? '•'}
              </span>
              <div>
                <p className="text-white font-bold text-sm leading-none">
                  {a.symbol.replace('USDT', '')}
                  <span className={`ml-1.5 text-xs ${DIR_TEXT[a.direction] ?? 'text-gray-400'}`}>
                    {a.direction.toUpperCase()}
                  </span>
                </p>
                <p className="text-gray-300 text-xs mt-0.5">
                  {Math.round(a.confidence * 100)}% güven · Yüksek kalite sinyal
                </p>
              </div>
            </div>
            <button
              onClick={e => { e.stopPropagation(); setAlerts(p => p.filter(x => x.id !== a.id)) }}
              className="text-gray-500 hover:text-white text-xs leading-none shrink-0 mt-0.5"
            >
              ✕
            </button>
          </div>
          {a.body && (
            <p className="text-gray-400 text-xs mt-1.5 leading-snug line-clamp-2">{a.body}</p>
          )}
          <p className="text-gray-600 text-[10px] mt-1.5">Detay için tıkla →</p>
        </div>
      ))}
    </div>
  )
}
