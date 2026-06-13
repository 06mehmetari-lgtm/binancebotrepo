import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const raw = await redis.get('system:deploy:version')
    if (!raw) {
      return NextResponse.json({
        version: 'bilinmiyor',
        status: 'unknown',
        deployed_at_iso: null,
        services_ok: [],
        services_failed: [],
        files_changed: [],
      })
    }
    const data = JSON.parse(raw)
    return NextResponse.json(data)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
