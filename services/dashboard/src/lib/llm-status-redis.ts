import type { Redis } from 'ioredis'
import { anyLlmConfigured, getLlmProviderStatus, type LlmProviderStatus } from '@/lib/llm-providers'
import { getGroqPoolStatus } from '@/lib/groq-pools'
import { publishLlmStatusFromEnv } from '@/lib/publish-llm-status'

export type LlmStatusBundle = {
  providers: LlmProviderStatus[]
  groq_pools: ReturnType<typeof getGroqPoolStatus>
  any_configured: boolean
  groq_configured: boolean
  groq_key_count: number
  source: 'redis' | 'env' | 'dashboard'
}

type RedisLlmPayload = {
  providers?: LlmProviderStatus[]
  groq_pools?: ReturnType<typeof getGroqPoolStatus>
  any_configured?: boolean
  groq_configured?: boolean
  groq_key_count?: number
}

function envFallback(): LlmStatusBundle {
  const providers = getLlmProviderStatus()
  const groq = providers.find(p => p.id === 'groq')
  return {
    providers,
    groq_pools: getGroqPoolStatus(),
    any_configured: anyLlmConfigured(),
    groq_configured: Boolean(groq?.configured),
    groq_key_count: groq?.key_count ?? 0,
    source: 'env',
  }
}

function parseRedis(raw: string): LlmStatusBundle | null {
  try {
    const data = JSON.parse(raw) as RedisLlmPayload
    if (!Array.isArray(data.providers) || data.providers.length === 0) return null
    const providers = data.providers as LlmProviderStatus[]
    const groq = providers.find(p => p.id === 'groq')
    const groqKeyCount = data.groq_key_count ?? groq?.key_count ?? 0
    return {
      providers,
      groq_pools: Array.isArray(data.groq_pools) ? data.groq_pools : getGroqPoolStatus(),
      any_configured: Boolean(data.any_configured ?? providers.some(p => p.configured)),
      groq_configured: Boolean(data.groq_configured ?? groq?.configured),
      groq_key_count: groqKeyCount,
      source: 'redis',
    }
  } catch {
    return null
  }
}

export async function resolveLlmStatus(
  raw: string | null,
  redis?: Redis | null,
): Promise<LlmStatusBundle> {
  const env = envFallback()
  const redisBundle = raw ? parseRedis(raw) : null

  // Redis boş veya Groq 0 anahtar ama dashboard env'de anahtar var → Redis'e yaz
  if (redis && env.groq_key_count > 0) {
    const redisGroq = redisBundle?.groq_key_count ?? 0
    if (!redisBundle || redisGroq < env.groq_key_count) {
      await publishLlmStatusFromEnv(redis)
      const refreshed = await redis.get('system:llm:status')
      const reparsed = refreshed ? parseRedis(refreshed) : null
      if (reparsed && reparsed.groq_key_count > 0) {
        return { ...reparsed, source: 'dashboard' }
      }
    }
  }

  if (redisBundle && redisBundle.groq_key_count > 0) {
    return redisBundle
  }
  if (redisBundle && env.groq_key_count === 0) {
    return redisBundle
  }
  return env
}
