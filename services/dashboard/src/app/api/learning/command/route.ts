import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'

const GUARD_CHANNEL = 'ch:position:guard'

type CommandAction =
  | 'force_signal'
  | 'close_symbol'
  | 'refresh_debate'
  | 'refresh_learning'
  | 'close_all'
  | 'resume_trading'

export async function POST(req: Request) {
  const redis = createRedis()
  try {
    const body = (await req.json().catch(() => ({}))) as {
      action?: CommandAction
      symbol?: string
      direction?: 'long' | 'short' | 'flat'
      confidence?: number
      source?: 'oms' | 'shadow' | 'both'
    }

    const action = body.action
    const symbol = (body.symbol ?? '').toUpperCase()
    if (!action) {
      return NextResponse.json({ error: 'action required' }, { status: 400 })
    }

    if (action === 'close_all') {
      const payload = JSON.stringify({
        ts: Date.now() / 1000,
        by: 'learning_command',
        action: 'close_all',
      })
      await redis.set(
        'system:trading:halted',
        JSON.stringify({
          halted: true,
          reason: 'Manuel — öğrenme merkezi tüm pozisyonları kapattı',
          by: 'learning_command',
          since: Date.now() / 1000,
        }),
        'EX',
        604800,
      )
      await redis.publish('ch:emergency:close_all', payload)
      return NextResponse.json({ ok: true, message: 'Acil kapatma tetiklendi' })
    }

    if (action === 'resume_trading') {
      await redis.del('system:trading:halted')
      const pulse = JSON.stringify({ ts: Date.now() / 1000, by: 'learning_command', action: 'resume' })
      await redis.publish('ch:trading:restart', pulse)
      await redis.publish('ch:immunity:clear_halt', pulse)
      return NextResponse.json({ ok: true, message: 'İşlem duraklatması kaldırıldı' })
    }

    if (!symbol.endsWith('USDT')) {
      return NextResponse.json({ error: 'symbol must be *USDT' }, { status: 400 })
    }

    if (action === 'force_signal') {
      const direction = body.direction ?? 'long'
      const confidence = Math.min(0.95, Math.max(0.61, body.confidence ?? 0.72))
      const featRaw = await redis.get(`features:latest:${symbol}`)
      const ctxRaw = await redis.get(`context:latest:${symbol}`)
      const feat = featRaw ? JSON.parse(featRaw) : {}
      const ctx = ctxRaw ? JSON.parse(ctxRaw) : {}
      const payload = {
        symbol,
        direction,
        confidence,
        is_valid: direction !== 'flat',
        trade_action: direction === 'flat' ? 'close' : 'open',
        source: 'manual_learning_hub',
        regime: ctx.regime ?? feat.regime ?? 'ranging',
        crisis_level: ctx.crisis_level ?? 0,
        drift_status: ctx.drift_status ?? feat.drift_status ?? 'STABLE',
        kelly_fraction: 0.03,
        rsi: feat.rsi_14 ?? 50,
        timestamp: Date.now() / 1000,
        consensus_reasoning: `Manuel emir — kullanıcı ${direction.toUpperCase()} yönü tetikledi`,
      }
      await redis.set(`signal:latest:${symbol}`, JSON.stringify(payload), 'EX', 600)
      await redis.lpush(
        'activity:feed',
        JSON.stringify({
          type: 'manual_signal',
          symbol,
          direction,
          confidence,
          time: Date.now() / 1000,
        }),
      )
      await redis.ltrim('activity:feed', 0, 499)
      return NextResponse.json({
        ok: true,
        message: `${symbol} sinyali ${direction} (%${Math.round(confidence * 100)}) yazıldı — OMS/shadow döngüsü işler`,
        signal: payload,
      })
    }

    if (action === 'close_symbol') {
      const src = body.source ?? 'both'
      const list = src === 'both' ? ['oms', 'shadow'] : [src]
      for (const src of list) {
        await redis.publish(
          GUARD_CHANNEL,
          JSON.stringify({
            symbol,
            source: src,
            direction: 'long',
            action: 'close',
            urgency: 'high',
            reason: 'Manuel kapat — AI Öğrenme Merkezi',
            ts: Date.now() / 1000,
          }),
        )
      }
      return NextResponse.json({
        ok: true,
        message: `${symbol} kapatma sinyali guard kanalına gönderildi`,
      })
    }

    if (action === 'refresh_debate') {
      await redis.publish(`ch:learn:${symbol}`, symbol)
      return NextResponse.json({
        ok: true,
        message: `${symbol} için ajan debate yenilemesi tetiklendi (ch:learn)`,
      })
    }

    if (action === 'refresh_learning') {
      await redis.publish(`ch:features:${symbol}`, symbol)
      return NextResponse.json({
        ok: true,
        message: `${symbol} öğrenme taraması tetiklendi (ch:features)`,
      })
    }

    return NextResponse.json({ error: 'Unknown action' }, { status: 400 })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
