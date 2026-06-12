import { NextResponse } from 'next/server'
import { createRedis } from '../../_redis'
import { cleanKeyList, collectKeysFromEnv } from '@/lib/llm-key-env'
import { maskKey, probeCerebrasKey, probeGoogleKey, probeGroqKey } from '@/lib/llm-probe'
import type { KeyOverridesMeta, ProbeSummary } from '@/lib/llm-health-types'
import { buildLlmHealthPayload } from '@/lib/llm-health-build'

export const dynamic = 'force-dynamic'

const OVERRIDES_KEY = 'system:llm:key_overrides'
const CHANNEL = 'ch:llm:keys_updated'

function parseOverrides(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    return null
  }
}

function metaFromOverrides(data: Record<string, unknown> | null, envFallback: boolean): KeyOverridesMeta {
  let groq = cleanKeyList(data?.groq)
  let cerebras = cleanKeyList(data?.cerebras)
  let google = cleanKeyList(data?.google)

  if (!groq.length && envFallback) groq = collectKeysFromEnv('GROQ_API_KEY')
  if (!cerebras.length && envFallback) cerebras = collectKeysFromEnv('CEREBRAS_API_KEY')
  if (!google.length && envFallback) google = collectKeysFromEnv('GOOGLE_AI_API_KEY', 'GEMINI_API_KEY')

  const runtimeGroq = cleanKeyList(data?.groq)
  const runtimeCerebras = cleanKeyList(data?.cerebras)
  const runtimeGoogle = cleanKeyList(data?.google)

  return {
    updated_at: typeof data?.updated_at === 'number' ? data.updated_at : undefined,
    updated_by: typeof data?.updated_by === 'string' ? data.updated_by : undefined,
    groq_count: groq.length,
    cerebras_count: cerebras.length,
    google_count: google.length,
    runtime_keys_active: Boolean(
      runtimeGroq.length || runtimeCerebras.length || runtimeGoogle.length,
    ),
    groq_masked: groq.map(maskKey),
    cerebras_masked: cerebras.map(maskKey),
    google_masked: google.map(maskKey),
    probe_results: (data?.probe_results as Record<string, ProbeSummary>) ?? undefined,
  }
}

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.get(OVERRIDES_KEY)
    const data = parseOverrides(raw)
    return NextResponse.json({
      overrides: metaFromOverrides(data, !data),
      has_runtime_overrides: Boolean(data),
    })
  } finally {
    redis.disconnect()
  }
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  const groqKeys = cleanKeyList(body.groq_keys, 32)
  const cerebrasKeys = cleanKeyList(body.cerebras_keys, 16)
  const googleKeys = cleanKeyList(body.google_keys ?? (body.google_key ? [body.google_key] : []), 4)
  const testBeforeSave = body.test_before_save !== false

  if (!groqKeys.length && !cerebrasKeys.length && !googleKeys.length) {
    return NextResponse.json({ error: 'En az bir anahtar girin (Groq, Cerebras veya Google).' }, { status: 400 })
  }

  const probeResults: Record<string, ProbeSummary> = {}
  let anyOk = false

  if (testBeforeSave) {
    if (groqKeys[0]) {
      const p = await probeGroqKey(groqKeys[0])
      probeResults.groq = p
      if (p.ok) anyOk = true
    }
    if (cerebrasKeys[0]) {
      const p = await probeCerebrasKey(cerebrasKeys[0])
      probeResults.cerebras = p
      if (p.ok) anyOk = true
    }
    if (googleKeys[0]) {
      const p = await probeGoogleKey(googleKeys[0])
      probeResults.google = p
      if (p.ok) anyOk = true
    }

    const allBlocked =
      groqKeys.length > 0 &&
      cerebrasKeys.length > 0 &&
      probeResults.groq?.ip_blocked &&
      probeResults.cerebras?.ip_blocked &&
      !probeResults.google?.ok

    if (!anyOk && allBlocked && body.force_save !== true) {
      return NextResponse.json(
        {
          error:
            'Tüm anahtarlar 403 (VPS IP engeli). Google Gemini deneyin veya Ollama kullanın. Yine de kaydetmek için force_save: true gönderin.',
          probe_results: probeResults,
          blocked: true,
        },
        { status: 422 },
      )
    }
  }

  const payload: Record<string, unknown> = {
    updated_at: Date.now() / 1000,
    updated_by: 'dashboard',
    probe_results: probeResults,
  }
  if (groqKeys.length) payload.groq = groqKeys
  if (cerebrasKeys.length) payload.cerebras = cerebrasKeys
  if (googleKeys.length) payload.google = googleKeys

  const redis = createRedis()
  try {
    await redis.set(OVERRIDES_KEY, JSON.stringify(payload))
    await redis.publish(CHANNEL, 'updated')

    const health = await buildLlmHealthPayload(JSON.stringify(payload))
    await redis.set('system:llm:health', JSON.stringify(health), 'EX', 600)

    return NextResponse.json({
      ok: true,
      message: anyOk
        ? 'Anahtarlar kaydedildi — agent_system ve learning_engine ~30 sn içinde yükler.'
        : 'Anahtarlar kaydedildi (test başarısız — Ollama yedek olarak çalışabilir).',
      overrides: metaFromOverrides(payload, false),
      probe_results: probeResults,
      health,
    })
  } finally {
    redis.disconnect()
  }
}
