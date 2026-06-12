import { NextResponse } from 'next/server'
import { createRedis } from '../../_redis'
import type { LlmHealthPayload } from '@/lib/llm-health-types'
import { buildLlmHealthPayload } from '@/lib/llm-health-build'

export const dynamic = 'force-dynamic'

const HEALTH_KEY = 'system:llm:health'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.get(HEALTH_KEY)
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as LlmHealthPayload
        if (parsed.providers?.groq) {
          return NextResponse.json({ ...parsed, source: 'redis' })
        }
      } catch {
        /* fallback */
      }
    }
    const overrideRaw = await redis.get('system:llm:key_overrides')
    const fallback = await buildLlmHealthPayload(overrideRaw)
    await redis.set(HEALTH_KEY, JSON.stringify(fallback), 'EX', 300)
    return NextResponse.json({ ...fallback, source: 'dashboard_probe' })
  } finally {
    redis.disconnect()
  }
}
