import { NextResponse } from 'next/server'
import { Redis } from 'ioredis'

const redis = new Redis({ host: process.env.REDIS_HOST || 'redis', port: 6379, password: process.env.REDIS_PASSWORD || undefined, lazyConnect: true })

export async function GET() {
  try {
    const raw = await redis.get('shadow:leaderboard')
    return NextResponse.json(raw ? JSON.parse(raw) : [])
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
