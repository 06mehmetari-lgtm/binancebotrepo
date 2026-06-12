import { collectKeysFromEnv } from '@/lib/llm-key-env'
import { probeCerebrasKey, probeGoogleKey, probeGroqKey, probeOpenRouterKey } from '@/lib/llm-probe'
import type { LlmHealthPayload } from '@/lib/llm-health-types'

async function ollamaQuick(): Promise<LlmHealthPayload['providers']['ollama']> {
  const url = (process.env.OLLAMA_URL || 'http://ollama:11434').replace(/\/$/, '')
  try {
    const res = await fetch(`${url}/api/tags`, { signal: AbortSignal.timeout(5000) })
    if (!res.ok) {
      return { id: 'ollama', status: 'error', ok: false, message: `HTTP ${res.status}` }
    }
    const data = (await res.json()) as { models?: { name?: string }[] }
    const names = (data.models ?? []).map(m => m.name ?? '').filter(Boolean)
    const model = process.env.OLLAMA_MODEL || 'llama3.2:3b'
    const base = model.split(':')[0]
    const ok = names.some(n => n.includes(base))
    return {
      id: 'ollama',
      status: ok ? 'ok' : 'no_model',
      ok,
      message: ok ? `${names.length} model yüklü` : `ollama pull ${model} gerekli`,
    }
  } catch (e) {
    return { id: 'ollama', status: 'error', ok: false, message: String(e).slice(0, 160) }
  }
}

/** Probe keys from optional Redis override JSON or process.env. */
export async function buildLlmHealthPayload(overrideRaw?: string | null): Promise<LlmHealthPayload> {
  let groqKeys = collectKeysFromEnv('GROQ_API_KEY')
  let cerebrasKeys = collectKeysFromEnv('CEREBRAS_API_KEY')
  let googleKeys = collectKeysFromEnv('GOOGLE_AI_API_KEY', 'GEMINI_API_KEY')
  let openrouterKeys = collectKeysFromEnv('OPENROUTER_API_KEY')

  if (overrideRaw) {
    try {
      const o = JSON.parse(overrideRaw) as Record<string, string[]>
      if (Array.isArray(o.groq) && o.groq.length) groqKeys = o.groq
      if (Array.isArray(o.cerebras) && o.cerebras.length) cerebrasKeys = o.cerebras
      if (Array.isArray(o.google) && o.google.length) googleKeys = o.google
      if (Array.isArray(o.openrouter) && o.openrouter.length) openrouterKeys = o.openrouter
    } catch {
      /* keep env */
    }
  }

  const [groqProbe, cerebrasProbe, googleProbe, openrouterProbe, ollama] = await Promise.all([
    groqKeys[0] ? probeGroqKey(groqKeys[0]) : Promise.resolve(null),
    cerebrasKeys[0] ? probeCerebrasKey(cerebrasKeys[0]) : Promise.resolve(null),
    googleKeys[0] ? probeGoogleKey(googleKeys[0]) : Promise.resolve(null),
    openrouterKeys[0] ? probeOpenRouterKey(openrouterKeys[0]) : Promise.resolve(null),
    ollamaQuick(),
  ])

  const groq = groqKeys.length
    ? {
        id: 'groq',
        status: groqProbe?.ok ? 'ok' : groqProbe?.http_code === 403 ? 'blocked' : 'error',
        ok: groqProbe?.ok,
        http_code: groqProbe?.http_code ?? null,
        message: groqProbe?.message ?? '',
        ip_blocked: groqProbe?.ip_blocked ?? false,
        key_source: overrideRaw ? 'runtime' : 'env',
      }
    : { id: 'groq', status: 'no_keys', ok: false, message: 'Anahtar yok' }

  const cerebras = cerebrasKeys.length
    ? {
        id: 'cerebras',
        status: cerebrasProbe?.ok ? 'ok' : cerebrasProbe?.http_code === 403 ? 'blocked' : 'error',
        ok: cerebrasProbe?.ok,
        http_code: cerebrasProbe?.http_code ?? null,
        message: cerebrasProbe?.message ?? '',
        ip_blocked: cerebrasProbe?.ip_blocked ?? false,
        key_source: overrideRaw ? 'runtime' : 'env',
      }
    : { id: 'cerebras', status: 'no_keys', ok: false, message: 'Anahtar yok' }

  const google = googleKeys.length
    ? {
        id: 'google',
        status: googleProbe?.ok ? 'ok' : 'error',
        ok: googleProbe?.ok,
        http_code: googleProbe?.http_code ?? null,
        message: googleProbe?.message ?? '',
        ip_blocked: googleProbe?.ip_blocked ?? false,
        key_source: overrideRaw ? 'runtime' : 'env',
      }
    : { id: 'google', status: 'no_keys', ok: false, message: 'Anahtar yok' }

  const openrouter = openrouterKeys.length
    ? {
        id: 'openrouter',
        status: openrouterProbe?.ok ? 'ok' : 'error',
        ok: openrouterProbe?.ok,
        http_code: openrouterProbe?.http_code ?? null,
        message: openrouterProbe?.message ?? '',
        ip_blocked: openrouterProbe?.ip_blocked ?? false,
        key_source: overrideRaw ? 'runtime' : 'env',
      }
    : { id: 'openrouter', status: 'no_keys', ok: false, message: 'Anahtar yok' }

  const anyCloudOk = Boolean(groq.ok || cerebras.ok || google.ok || openrouter.ok)
  const cloudBlocked = Boolean(
    (groq.status === 'blocked' || cerebras.status === 'blocked') && !anyCloudOk,
  )
  const needsKeyUpdate = cloudBlocked

  let alert_level: LlmHealthPayload['alert_level'] = 'ok'
  let alert_message = ''
  if (needsKeyUpdate && !ollama?.ok) {
    alert_level = 'critical'
    alert_message =
      'Groq/Cerebras 403 — VPS IP engeli. Google Gemini anahtarı ekleyin veya Ollama kullanın.'
  } else if (needsKeyUpdate) {
    alert_level = 'warning'
    alert_message = 'Bulut LLM engelli — Ollama yedek aktif. Alternatif anahtar ekleyebilirsiniz.'
  }

  return {
    updated_at: Date.now() / 1000,
    providers: { groq, cerebras, google, openrouter, ollama },
    any_cloud_ok: anyCloudOk,
    cloud_blocked: cloudBlocked,
    needs_key_update: needsKeyUpdate,
    alert_level,
    alert_message,
    runtime_keys_active: Boolean(overrideRaw),
  }
}
