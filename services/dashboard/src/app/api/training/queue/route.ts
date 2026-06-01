import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const items = await redis.lrange('training:queue', 0, -1)
    const result = await Promise.all(
      items.map(async (raw) => {
        try {
          const item = JSON.parse(raw)
          const statusRaw = await redis.get(`training:queue:status:${item.id}`)
          const status = statusRaw ? JSON.parse(statusRaw) : { status: 'pending' }
          return {
            id: item.id,
            title: item.title,
            filename: item.filename,
            created_at: item.created_at,
            text_length: (item.raw_text ?? '').length,
            ...status,
          }
        } catch {
          return null
        }
      }),
    )
    return NextResponse.json(result.filter(Boolean))
  } finally {
    redis.disconnect()
  }
}
