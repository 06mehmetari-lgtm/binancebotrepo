/** Live LLM API probe from dashboard (mirrors probe-llm-keys.py). */

export type ProbeResult = {
  ok: boolean
  http_code: number | null
  message: string
  ip_blocked: boolean
}

const GROQ_MODEL = process.env.GROQ_FAST_MODELS?.split(',')[0]?.trim() || 'llama-3.1-8b-instant'
const CEREBRAS_MODEL = process.env.CEREBRAS_MODEL || 'llama3.1-8b'
const GOOGLE_MODEL = process.env.GOOGLE_AI_MODEL || 'gemini-2.0-flash'

async function openAiProbe(
  baseUrl: string,
  apiKey: string,
  model: string,
  extraHeaders?: Record<string, string>,
): Promise<ProbeResult> {
  try {
    const res = await fetch(`${baseUrl.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        ...(extraHeaders ?? {}),
      },
      body: JSON.stringify({
        model,
        messages: [{ role: 'user', content: 'Reply with exactly one word: OK' }],
        max_tokens: 8,
        temperature: 0,
      }),
      signal: AbortSignal.timeout(20000),
    })
    const body = await res.text()
    if (res.ok) {
      return { ok: true, http_code: res.status, message: 'API yanıt verdi', ip_blocked: false }
    }
    if (res.status === 429) {
      return { ok: true, http_code: 429, message: 'Rate limit — anahtar geçerli', ip_blocked: false }
    }
    const low = body.toLowerCase()
    const ipBlocked =
      res.status === 403 &&
      (low.includes('network settings') || low.includes('access denied') || low.includes('forbidden'))
    return {
      ok: false,
      http_code: res.status,
      message: body.slice(0, 200) || res.statusText,
      ip_blocked: ipBlocked,
    }
  } catch (e) {
    return { ok: false, http_code: null, message: String(e).slice(0, 200), ip_blocked: false }
  }
}

export function probeGroqKey(key: string): Promise<ProbeResult> {
  return openAiProbe('https://api.groq.com/openai/v1', key, GROQ_MODEL)
}

export function probeCerebrasKey(key: string): Promise<ProbeResult> {
  return openAiProbe('https://api.cerebras.ai/v1', key, CEREBRAS_MODEL)
}

export function probeGoogleKey(key: string): Promise<ProbeResult> {
  return openAiProbe(
    'https://generativelanguage.googleapis.com/v1beta/openai',
    key,
    GOOGLE_MODEL,
  )
}

export function maskKey(key: string): string {
  const k = key.trim()
  if (k.length <= 8) return '***'
  return `${k.slice(0, 4)}…${k.slice(-4)}`
}
