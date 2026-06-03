'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { StreamEvent } from '@/lib/stream-events'

export interface UseStreamOptions {
  /** Match channel prefix or exact channel; empty = all non-ping events */
  channels?: string[]
  hints?: string[]
  maxEvents?: number
  enabled?: boolean
  onEvent?: (ev: StreamEvent) => void
}

const PING_HINTS = new Set(['ping', 'connected'])

export function useStream(options: UseStreamOptions = {}) {
  const {
    channels = [],
    hints = [],
    maxEvents = 100,
    enabled = true,
    onEvent,
  } = options

  const [events, setEvents] = useState<StreamEvent[]>([])
  const [connected, setConnected] = useState(false)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  const matches = useCallback(
    (ev: StreamEvent) => {
      if (PING_HINTS.has(ev.hint ?? '')) return false
      if (channels.length > 0) {
        const ok = channels.some(
          c =>
            ev.ch === c ||
            ev.ch.startsWith(c.replace('*', '')) ||
            (c.endsWith('*') && ev.ch.startsWith(c.slice(0, -1)))
        )
        if (!ok) return false
      }
      if (hints.length > 0 && ev.hint && !hints.includes(ev.hint)) return false
      return true
    },
    [channels, hints]
  )

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return

    let es: EventSource | null = null
    let retryMs = 1000
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let disposed = false

    const connect = () => {
      if (disposed) return
      es = new EventSource('/api/stream')

      es.onopen = () => {
        setConnected(true)
        retryMs = 1000
      }

      es.onmessage = e => {
        try {
          const ev = JSON.parse(e.data) as StreamEvent
          if (ev.hint === 'connected') {
            setConnected(true)
            return
          }
          if (!matches(ev)) return
          setEvents(prev => [ev, ...prev].slice(0, maxEvents))
          onEventRef.current?.(ev)
        } catch {
          /* ignore malformed */
        }
      }

      es.onerror = () => {
        setConnected(false)
        es?.close()
        es = null
        if (disposed) return
        retryTimer = setTimeout(() => {
          retryMs = Math.min(retryMs * 2, 30000)
          connect()
        }, retryMs)
      }
    }

    connect()

    return () => {
      disposed = true
      if (retryTimer) clearTimeout(retryTimer)
      es?.close()
      setConnected(false)
    }
  }, [enabled, matches, maxEvents])

  const clear = useCallback(() => setEvents([]), [])

  return { events, connected, clear }
}

/** Fire callback when stream receives matching invalidation (no event buffer) */
export function useStreamInvalidate(
  options: UseStreamOptions & { debounceMs?: number }
) {
  const { debounceMs = 300, onEvent, ...rest } = options
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const wrappedOnEvent = useCallback(
    (ev: StreamEvent) => {
      if (debounceMs <= 0) {
        onEvent?.(ev)
        return
      }
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => onEvent?.(ev), debounceMs)
    },
    [debounceMs, onEvent]
  )

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    []
  )

  return useStream({ ...rest, onEvent: wrappedOnEvent, maxEvents: 0 })
}
