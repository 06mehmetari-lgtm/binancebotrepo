import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

export async function GET() {
  const redis = createRedis()
  try {
    const keys = await redis.keys('features:latest:*')
    const symbols = keys.map(k => k.replace('features:latest:', '')).sort()
    return NextResponse.json(symbols)
  } catch (e) {
    return NextResponse.json([], { status: 500 })
  } finally {
    redis.disconnect()
  }
}
