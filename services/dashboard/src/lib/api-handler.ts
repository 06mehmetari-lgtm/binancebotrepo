import { NextResponse } from 'next/server'
import { createRedis } from '@/app/api/_redis'

type HandlerResult = unknown

export async function withApiHandler(
  label: string,
  fn: () => Promise<HandlerResult>,
): Promise<NextResponse> {
  try {
    const result = await fn()
    return NextResponse.json(result)
  } catch (err) {
    console.error(`[API ${label}]`, err)
    return NextResponse.json(
      { error: 'Internal server error', detail: String(err) },
      { status: 500 },
    )
  }
}

export async function withRedisCache(
  cacheKey: string,
  ttlSec: number,
  fn: (redis: ReturnType<typeof createRedis>) => Promise<HandlerResult>,
): Promise<NextResponse> {
  const redis = createRedis()
  try {
    const cached = await redis.get(cacheKey)
    if (cached) {
      return NextResponse.json(JSON.parse(cached))
    }
    const result = await fn(redis)
    await redis.setex(cacheKey, ttlSec, JSON.stringify(result))
    return NextResponse.json(result)
  } catch (err) {
    console.error(`[API cache ${cacheKey}]`, err)
    return NextResponse.json({ error: String(err) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
