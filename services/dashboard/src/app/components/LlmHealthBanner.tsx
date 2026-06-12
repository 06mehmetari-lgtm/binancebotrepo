'use client'

import { useCallback, useEffect, useState } from 'react'
import type { LlmHealthPayload } from '@/lib/llm-health-types'

export default function LlmHealthBanner() {
  const [health, setHealth] = useState<LlmHealthPayload | null>(null)
  const [dismissed, setDismissed] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/llm/health', { cache: 'no-store' })
      if (res.ok) setHealth(await res.json())
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [load])

  if (!health || dismissed) return null

  const critical =
    health.alert_level === 'critical' ||
    (health.needs_key_update && health.cloud_blocked && !health.any_cloud_ok)
  const warning = health.alert_level === 'warning' || health.needs_key_update

  if (!critical && !warning) return null

  const bg = critical
    ? 'bg-red-950 border-red-600 text-red-100'
    : 'bg-amber-950/90 border-amber-600 text-amber-100'

  return (
    <div className={`border-b px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 ${bg}`}>
      <div className="flex items-start gap-2 text-sm min-w-0">
        <span className="text-lg shrink-0">{critical ? '🚨' : '⚠️'}</span>
        <div className="min-w-0">
          <p className="font-semibold">
            {critical ? 'LLM erişim sorunu — Groq/Cerebras 403 (VPS IP engeli)' : 'LLM uyarısı'}
          </p>
          <p className="text-xs opacity-90 mt-0.5">
            {health.alert_message ||
              'Yapay zeka anahtarlarını güncelleyin veya Google Gemini / Ollama kullanın.'}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <a
          href="/llm-keys"
          className="px-3 py-1.5 rounded-lg bg-white/15 hover:bg-white/25 text-sm font-semibold border border-white/20"
        >
          Anahtarları güncelle →
        </a>
        {!critical && (
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="text-xs opacity-70 hover:opacity-100 px-2"
          >
            Kapat
          </button>
        )}
      </div>
    </div>
  )
}
