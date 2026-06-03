import { anyLlmConfigured, getLlmProviderStatus, type LlmProviderStatus } from '@/lib/llm-providers'
import { getGroqPoolStatus } from '@/lib/groq-pools'

export type LlmStatusBundle = {
  providers: LlmProviderStatus[]
  groq_pools: ReturnType<typeof getGroqPoolStatus>
  any_configured: boolean
  groq_configured: boolean
  groq_key_count: number
  source: 'redis' | 'env'
}

type RedisLlmPayload = {
  providers?: LlmProviderStatus[]
  groq_pools?: ReturnType<typeof getGroqPoolStatus>
  any_configured?: boolean
  groq_configured?: boolean
  groq_key_count?: number
}

export function resolveLlmStatus(raw: string | null): LlmStatusBundle {
  if (raw) {
    try {
      const data = JSON.parse(raw) as RedisLlmPayload
      if (Array.isArray(data.providers) && data.providers.length > 0) {
        const providers = data.providers as LlmProviderStatus[]
        const groq = providers.find(p => p.id === 'groq')
        return {
          providers,
          groq_pools: Array.isArray(data.groq_pools) ? data.groq_pools : getGroqPoolStatus(),
          any_configured: Boolean(data.any_configured ?? providers.some(p => p.configured)),
          groq_configured: Boolean(data.groq_configured ?? groq?.configured),
          groq_key_count: data.groq_key_count ?? groq?.key_count ?? 0,
          source: 'redis',
        }
      }
    } catch {
      /* fall through */
    }
  }

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
