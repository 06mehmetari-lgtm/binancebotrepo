import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

/** POST { action: 'close_all' } — flatten OMS + shadow, halt new entries */
export async function POST(req: Request) {
  const redis = createRedis()
  try {
    const body = await req.json().catch(() => ({}))
    const action = (body as { action?: string }).action ?? 'close_all'

    if (action === 'resume') {
      await redis.del('system:trading:halted')
      return NextResponse.json({ ok: true, action: 'resume', message: 'Trading halt cleared' })
    }

    if (action !== 'close_all') {
      return NextResponse.json({ error: 'Unknown action' }, { status: 400 })
    }

    const payload = JSON.stringify({
      ts: Date.now() / 1000,
      by: 'dashboard',
      action: 'close_all',
    })
    await redis.set(
      'system:trading:halted',
      JSON.stringify({
        halted: true,
        reason: 'ACIL DURUM — kullanıcı tüm pozisyonları kapattı',
        by: 'dashboard',
        since: Date.now() / 1000,
      }),
      'EX',
      604800,
    )
    await redis.publish('ch:emergency:close_all', payload)
    await redis.set('system:emergency:last', payload, 'EX', 86400)

    return NextResponse.json({
      ok: true,
      action: 'close_all',
      message: 'Acil durum tetiklendi — OMS ve shadow pozisyonları kapatılıyor, yeni işlem durduruldu',
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}

export async function GET() {
  const redis = createRedis()
  try {
    const [haltRaw, lastRaw] = await Promise.all([
      redis.get('system:trading:halted'),
      redis.get('system:emergency:last'),
    ])
    let halted = false
    let haltInfo: Record<string, unknown> | null = null
    if (haltRaw) {
      try {
        haltInfo = JSON.parse(haltRaw)
        halted = Boolean(haltInfo?.halted)
      } catch {
        halted = true
      }
    }
    return NextResponse.json({
      halted,
      halt: haltInfo,
      last_emergency: lastRaw ? JSON.parse(lastRaw) : null,
    })
  } finally {
    redis.disconnect()
  }
}
