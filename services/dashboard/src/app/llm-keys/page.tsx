'use client'

import { useCallback, useEffect, useState } from 'react'
import type { KeyOverridesMeta, LlmHealthPayload, ProbeSummary } from '@/lib/llm-health-types'

type SaveResult = {
  ok?: boolean
  error?: string
  blocked?: boolean
  probe_results?: Record<string, ProbeSummary>
  message?: string
}

function StatusBadge({ ok, blocked, label }: { ok?: boolean; blocked?: boolean; label: string }) {
  if (ok) {
    return <span className="text-green-400 text-xs font-semibold">✓ {label} OK</span>
  }
  if (blocked) {
    return <span className="text-red-400 text-xs font-semibold">✗ {label} 403 engel</span>
  }
  return <span className="text-gray-500 text-xs">{label} — test yok</span>
}

export default function LlmKeysPage() {
  const [health, setHealth] = useState<LlmHealthPayload | null>(null)
  const [meta, setMeta] = useState<KeyOverridesMeta | null>(null)
  const [groqKeys, setGroqKeys] = useState<string[]>(['', '', ''])
  const [cerebrasKeys, setCerebrasKeys] = useState<string[]>(['', ''])
  const [googleKey, setGoogleKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<SaveResult | null>(null)
  const [forceSave, setForceSave] = useState(false)

  const load = useCallback(async () => {
    const [hRes, kRes] = await Promise.all([
      fetch('/api/llm/health', { cache: 'no-store' }),
      fetch('/api/llm/keys', { cache: 'no-store' }),
    ])
    if (hRes.ok) setHealth(await hRes.json())
    if (kRes.ok) {
      const k = await kRes.json()
      setMeta(k.overrides)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const blocked = Boolean(
    health?.cloud_blocked ||
      health?.providers?.groq?.status === 'blocked' ||
      health?.providers?.cerebras?.status === 'blocked',
  )

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setResult(null)
    try {
      const res = await fetch('/api/llm/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          groq_keys: groqKeys.filter(k => k.trim()),
          cerebras_keys: cerebrasKeys.filter(k => k.trim()),
          google_keys: googleKey.trim() ? [googleKey.trim()] : [],
          test_before_save: true,
          force_save: forceSave,
        }),
      })
      const data = (await res.json()) as SaveResult
      setResult(data)
      if (res.ok) {
        setGroqKeys(['', '', ''])
        setCerebrasKeys(['', ''])
        setGoogleKey('')
        setForceSave(false)
        await load()
      } else if (data.blocked) {
        setForceSave(true)
      }
    } catch (err) {
      setResult({ error: String(err) })
    } finally {
      setSaving(false)
    }
  }

  function updateGroq(i: number, v: string) {
    setGroqKeys(prev => {
      const next = [...prev]
      next[i] = v
      return next
    })
  }

  function addGroqSlot() {
    if (groqKeys.length < 10) setGroqKeys(prev => [...prev, ''])
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">🔑 LLM API Anahtarları</h1>
        <p className="text-gray-500 text-sm mt-1">
          Groq/Cerebras VPS engeli (403) olduğunda yeni anahtar girin — kayıt sonrası ~30 sn içinde
          agent_system ve learning_engine kullanır.
        </p>
      </div>

      {blocked && (
        <div className="rounded-xl border-2 border-red-600 bg-red-950/50 p-5 animate-pulse-slow">
          <h2 className="text-red-300 font-bold text-lg">🚨 VPS IP engeli tespit edildi (HTTP 403)</h2>
          <p className="text-red-200/90 text-sm mt-2 leading-relaxed">
            Bu sunucunun IP adresinden Groq ve Cerebras API&apos;leri erişimi reddediyor. Aynı
            sunucuda <strong>yeni Groq anahtarı</strong> genelde sorunu çözmez — farklı sağlayıcı
            deneyin:
          </p>
          <ul className="text-red-200/80 text-sm mt-3 list-disc list-inside space-y-1">
            <li>
              <strong>Google Gemini</strong> — aşağıdaki alana <code className="text-red-100">GOOGLE_AI_API_KEY</code>{' '}
              yapıştırın (VPS&apos;ten çoğu zaman çalışır)
            </li>
            <li>
              <strong>Ollama</strong> — yerel model (sunucuda{' '}
              <code className="text-red-100">bash scripts/fix-ollama-on-server.sh</code>)
            </li>
            <li>Farklı VPS bölgesi veya HTTPS proxy / LLM relay</li>
          </ul>
        </div>
      )}

      {health && (
        <div
          className={`rounded-xl border p-4 grid sm:grid-cols-2 gap-3 text-sm ${
            blocked ? 'border-red-800 bg-red-950/20' : 'border-gray-800 bg-gray-900'
          }`}
        >
          <div>
            <span className="text-gray-500">Groq</span>
            <p className={health.providers?.groq?.ok ? 'text-green-400' : 'text-red-400'}>
              {health.providers?.groq?.message || health.providers?.groq?.status}
              {health.providers?.groq?.http_code ? ` (${health.providers.groq.http_code})` : ''}
            </p>
          </div>
          <div>
            <span className="text-gray-500">Cerebras</span>
            <p className={health.providers?.cerebras?.ok ? 'text-green-400' : 'text-red-400'}>
              {health.providers?.cerebras?.message || health.providers?.cerebras?.status}
            </p>
          </div>
          <div>
            <span className="text-gray-500">Google Gemini</span>
            <p className={health.providers?.google?.ok ? 'text-green-400' : 'text-gray-400'}>
              {health.providers?.google?.message || health.providers?.google?.status || '—'}
            </p>
          </div>
          <div>
            <span className="text-gray-500">Ollama</span>
            <p className={health.providers?.ollama?.ok ? 'text-green-400' : 'text-amber-400'}>
              {health.providers?.ollama?.message || '—'}
            </p>
          </div>
        </div>
      )}

      {meta && (
        <div className="text-xs text-gray-500 border border-gray-800 rounded-lg p-3 bg-gray-900/50">
          Aktif: Groq {meta.groq_count} · Cerebras {meta.cerebras_count} · Google {meta.google_count}
          {meta.runtime_keys_active && (
            <span className="text-orange-400 ml-2">(dashboard runtime override)</span>
          )}
          {meta.updated_at && (
            <span className="ml-2">
              son güncelleme: {new Date(meta.updated_at * 1000).toLocaleString('tr-TR')}
            </span>
          )}
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-6 bg-gray-900 border border-gray-800 rounded-xl p-6">
        <section className="space-y-3">
          <h2 className="text-orange-400 font-bold">Groq anahtarları</h2>
          <p className="text-gray-500 text-xs">gsk_… — birden fazla key rate-limit için rotasyon</p>
          {groqKeys.map((k, i) => (
            <input
              key={`g-${i}`}
              type="password"
              autoComplete="off"
              placeholder={`GROQ_API_KEY_${i + 1}`}
              value={k}
              onChange={e => updateGroq(i, e.target.value)}
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white font-mono"
            />
          ))}
          {groqKeys.length < 10 && (
            <button
              type="button"
              onClick={addGroqSlot}
              className="text-xs text-orange-400 hover:text-orange-300"
            >
              + Groq slot ekle
            </button>
          )}
        </section>

        <section className="space-y-3">
          <h2 className="text-cyan-400 font-bold">Cerebras anahtarları</h2>
          {cerebrasKeys.map((k, i) => (
            <input
              key={`c-${i}`}
              type="password"
              autoComplete="off"
              placeholder={`CEREBRAS_API_KEY_${i + 1}`}
              value={k}
              onChange={e => {
                const next = [...cerebrasKeys]
                next[i] = e.target.value
                setCerebrasKeys(next)
              }}
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white font-mono"
            />
          ))}
        </section>

        <section className="space-y-2">
          <h2 className="text-blue-400 font-bold">Google Gemini (VPS için önerilen)</h2>
          <input
            type="password"
            autoComplete="off"
            placeholder="GOOGLE_AI_API_KEY veya GEMINI_API_KEY"
            value={googleKey}
            onChange={e => setGoogleKey(e.target.value)}
            className="w-full bg-gray-950 border border-blue-900/50 rounded-lg px-3 py-2 text-sm text-white font-mono"
          />
          <p className="text-gray-600 text-xs">
            Ücretsiz:{' '}
            <a
              href="https://aistudio.google.com/apikey"
              target="_blank"
              rel="noreferrer"
              className="text-blue-400 underline"
            >
              Google AI Studio
            </a>
          </p>
        </section>

        {forceSave && (
          <p className="text-amber-400 text-sm border border-amber-800 rounded-lg p-3 bg-amber-950/30">
            Son test 403 döndü. Yine de kaydetmek için tekrar &quot;Kaydet ve test et&quot;e basın
            (force_save aktif).
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className="w-full py-3 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white font-bold transition-colors"
        >
          {saving ? 'Test ediliyor…' : 'Kaydet ve test et'}
        </button>
      </form>

      {result && (
        <div
          className={`rounded-xl border p-4 text-sm ${
            result.ok ? 'border-green-800 bg-green-950/30 text-green-200' : 'border-red-800 bg-red-950/30 text-red-200'
          }`}
        >
          {result.error && <p className="font-semibold">{result.error}</p>}
          {result.message && <p className="mt-1">{result.message}</p>}
          {result.probe_results && (
            <div className="mt-3 flex flex-wrap gap-3">
              {result.probe_results.groq && (
                <StatusBadge
                  ok={result.probe_results.groq.ok}
                  blocked={result.probe_results.groq.ip_blocked}
                  label="Groq"
                />
              )}
              {result.probe_results.cerebras && (
                <StatusBadge
                  ok={result.probe_results.cerebras.ok}
                  blocked={result.probe_results.cerebras.ip_blocked}
                  label="Cerebras"
                />
              )}
              {result.probe_results.google && (
                <StatusBadge ok={result.probe_results.google.ok} label="Google" />
              )}
            </div>
          )}
        </div>
      )}

      <p className="text-gray-600 text-xs text-center">
        Anahtarlar Redis&apos;te şifrelenmeden saklanır — yalnızca bu VPS&apos;te kullanın. Kalıcı
        .env için sunucuda manuel güncelleme önerilir.
      </p>
    </div>
  )
}
