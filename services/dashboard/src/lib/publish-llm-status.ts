import type { Redis } from 'ioredis'
import { getGroqPoolStatus } from '@/lib/groq-pools'
import { getLlmProviderStatus } from '@/lib/llm-providers'

/** Dashboard env → Redis (yedek; agent_system birincil yayıncı). */
export async function publishLlmStatusFromEnv(redis: Redis): Promise<boolean> {
  const providers = getLlmProviderStatus()
  const groq = providers.find(p => p.id === 'groq')
  const groqPools = getGroqPoolStatus()
  const keyCount = groq?.key_count ?? 0
  if (keyCount === 0 && !providers.some(p => p.id !== 'ollama' && p.configured)) {
    return false
  }

  const payload = {
    updated_at: Date.now() / 1000,
    providers: providers.map(p => ({
      ...p,
      env:
        p.id === 'groq' && keyCount > 0
          ? `GROQ_API_KEY_1..${keyCount}`
          : p.id === 'cerebras' && p.key_count > 0
            ? `CEREBRAS_API_KEY_1..${p.key_count}`
            : p.env,
    })),
    groq_pools: groqPools.filter(p => p.count > 0),
    any_configured: providers.some(p => p.configured),
    groq_configured: Boolean(groq?.configured),
    groq_key_count: keyCount,
    source: 'dashboard',
  }

  await redis.set('system:llm:status', JSON.stringify(payload), 'EX', 300)
  return true
}
