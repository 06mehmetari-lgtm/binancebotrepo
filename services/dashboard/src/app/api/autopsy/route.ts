export const dynamic = 'force-dynamic'
import { withApiHandler } from '@/lib/api-handler'
import { createRedis } from '../_redis'

function safeJson(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    return null
  }
}

export async function GET(req: Request) {
  return withApiHandler('autopsy', async () => {
    const { searchParams } = new URL(req.url)
    const limit = Math.min(100, Math.max(1, parseInt(searchParams.get('limit') ?? '40', 10)))

    const redis = createRedis()
    try {
      const [historyRaw, feedRaw] = await Promise.all([
        redis.lrange('oms:trade_history', 0, limit - 1),
        redis.lrange('activity:feed', 0, 199),
      ])

      const trades = historyRaw
        .map(r => safeJson(r))
        .filter((t): t is Record<string, unknown> => !!t)

      const autopsyEvents = feedRaw
        .map(r => safeJson(r))
        .filter(e => e?.type === 'autopsy')

      const enriched = await Promise.all(
        trades.map(async t => {
          const symbol = String(t.symbol ?? '').toUpperCase()
          const lessonsRaw = symbol
            ? await redis.lrange(`trade:lessons:${symbol}`, 0, 4)
            : []
          const lessons = lessonsRaw
            .map(l => safeJson(l))
            .filter(Boolean)
          const body = autopsyEvents.find(
            e => String(e?.symbol ?? '').toUpperCase() === symbol,
          )?.body as string | undefined
          return {
            ...t,
            symbol,
            lessons,
            autopsy_summary: body ?? null,
            error_category: parseCategory(body),
          }
        }),
      )

      return {
        trades: enriched,
        autopsy_feed: autopsyEvents.slice(0, 30),
        total: enriched.length,
      }
    } finally {
      redis.disconnect()
    }
  })
}

function parseCategory(body?: string): string | null {
  if (!body) return null
  const m = body.match(/—\s*([A-Z_]+)\s*$/i)
  return m?.[1] ?? null
}
