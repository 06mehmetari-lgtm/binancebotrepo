import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

// Approximate free-tier daily limits. null = pay-per-token (no hard cap).
const LIMITS: Record<string, { daily: number | null; note: string }> = {
  Groq:       { daily: 14400, note: 'Ücretsiz: ~14.400 istek/gün' },
  Cerebras:   { daily: null,  note: 'Ücretsiz: dakika başı limit var, günlük sınır yok' },
  SambaNova:  { daily: 600,   note: 'Ücretsiz tahmini: ~600 istek/gün' },
  OpenRouter: { daily: 200,   note: 'Ücretsiz model: ~200 istek/gün' },
  Cohere:     { daily: 33,    note: 'Deneme: 1.000 istek/ay (~33/gün)' },
  DeepSeek:   { daily: null,  note: 'Token başı ücret, günlük sınır yok' },
  ZAI:        { daily: null,  note: 'Plana göre değişir' },
  Anthropic:  { daily: null,  note: 'Token başı ücret, günlük sınır yok' },
  Ollama:       { daily: null,  note: 'Yerel model, sınırsız' },
  HuggingFace:  { daily: null,  note: 'Ücretsiz: dakika başı limit var' },
}

const KEY_ENVS: Record<string, string> = {
  Groq:       'GROQ_API_KEY',
  Cerebras:   'CEREBRAS_API_KEY',
  SambaNova:  'SAMBANOVA_API_KEY',
  OpenRouter: 'OPENROUTER_API_KEY',
  Cohere:     'COHERE_API_KEY',
  DeepSeek:   'DEEPSEEK_API_KEY',
  ZAI:        'ZAI_API_KEY',
  Anthropic:    'ANTHROPIC_API_KEY',
  HuggingFace:  'HUGGINGFACE_API_KEY',
}

function countKeys(baseEnv: string): number {
  let n = process.env[baseEnv] ? 1 : 0
  for (let i = 1; i <= 20; i++) if (process.env[`${baseEnv}_${i}`]) n++
  return n
}

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.get('llm:provider_stats')
    const agentStats: Record<string, Record<string, number | string>> = raw ? JSON.parse(raw) : {}
    const now = Date.now() / 1000

    const providers = ['Groq', 'Cerebras', 'SambaNova', 'OpenRouter', 'Cohere', 'DeepSeek', 'ZAI', 'Anthropic', 'HuggingFace', 'Ollama']

    const result = providers.map(name => {
      const s = agentStats[name] ?? {}
      const keyEnv = KEY_ENVS[name]
      const keysConfigured = name === 'Ollama' ? 1 : (keyEnv ? countKeys(keyEnv) : 0)
      const lim = LIMITS[name] ?? { daily: null, note: '' }

      const calls      = Number(s.calls      ?? 0)
      const rateLimits = Number(s.rate_limits ?? 0)
      const errors     = Number(s.errors      ?? 0)
      const successes  = Number(s.successes   ?? 0)
      const lastSuccessTs  = Number(s.last_success_ts ?? 0)
      const cooldownUntil  = Number(s.cooldown_until ?? 0)
      const keysReady      = Number(s.keys_ready ?? keysConfigured)
      const lastError      = String(s.last_error ?? '')

      const inCooldown = cooldownUntil > now
      const cooldownSecsLeft = inCooldown ? Math.ceil(cooldownUntil - now) : 0

      let status: 'working' | 'rate_limited' | 'no_key' | 'error' | 'local' | 'unknown'
      if (name === 'Ollama') status = 'local'
      else if (keysConfigured === 0) status = 'no_key'
      else if (inCooldown && keysReady === 0) status = 'rate_limited'
      else if (rateLimits > 0 && successes === 0 && !inCooldown) status = 'rate_limited'
      else if (successes > 0) status = 'working'
      else if (errors > 0 && successes === 0 && calls > 0) status = 'error'
      else if (calls === 0 && keysConfigured > 0) status = 'unknown'
      else status = 'unknown'

      const estimatedRemaining = lim.daily !== null
        ? Math.max(0, lim.daily - calls)
        : null

      return {
        name,
        status,
        keysConfigured,
        keysReady,
        calls,
        rateLimits,
        errors,
        successes,
        lastSuccessTs,
        lastError,
        cooldownUntil: inCooldown ? cooldownUntil : 0,
        cooldownSecsLeft,
        dailyLimit: lim.daily,
        estimatedRemaining,
        note: lim.note,
      }
    })

    return NextResponse.json(result)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
