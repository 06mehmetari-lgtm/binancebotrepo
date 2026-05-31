import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { discoverSymbols } from '@/lib/universe'

export async function GET() {
  const redis = createRedis()
  try {
    const symbols = (await discoverSymbols(redis)).sort()
    return NextResponse.json(symbols)
  } catch (e) {
    return NextResponse.json([], { status: 500 })
  } finally {
    redis.disconnect()
  }
}
