import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.get('portfolio:state:v1')
    if (!raw) {
      return NextResponse.json({
        updated_at: null,
        total_open: 0,
        oms_open: 0,
        shadow_open: 0,
        long_positions: 0,
        short_positions: 0,
        positions: [],
      })
    }
    return NextResponse.json(JSON.parse(raw))
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
