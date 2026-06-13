import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { getPostgresPool, closePostgresPool } from '@/lib/postgres'
import {
  rowToLimits,
  validateRiskLimits,
  UPSERT_SQL,
} from '@/lib/risk-limits-config'
import {
  publishRiskLimitsToRedis,
  resolveRiskLimits,
} from '@/lib/risk-limits-service'

export async function GET() {
  const { limits, source } = await resolveRiskLimits({ syncRedisIfMissing: true })
  return NextResponse.json({ limits, source })
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  const input = {
    min_leverage: Number(body.min_leverage),
    max_leverage: Number(body.max_leverage),
    max_position_pct: Number(body.max_position_pct),
    max_daily_loss_pct: Number(body.max_daily_loss_pct),
    max_open_positions: Number(body.max_open_positions),
    min_signal_confidence: Number(body.min_signal_confidence),
    min_immunity_confidence: Number(body.min_immunity_confidence),
    max_trades_per_day: Number(body.max_trades_per_day),
    updated_by: String(body.updated_by || 'dashboard_positions'),
  }

  const errors = validateRiskLimits(input)
  if (errors.length > 0) {
    return NextResponse.json({ error: errors.join('; ') }, { status: 400 })
  }

  const pool = getPostgresPool()
  try {
    const res = await pool.query(UPSERT_SQL, [
      input.min_leverage,
      input.max_leverage,
      input.max_position_pct,
      input.max_daily_loss_pct,
      input.max_open_positions,
      input.min_signal_confidence,
      input.min_immunity_confidence,
      input.max_trades_per_day,
      input.updated_by,
    ])
    const limits = rowToLimits(res.rows[0] as Record<string, unknown>)
    await publishRiskLimitsToRedis(limits)
    return NextResponse.json({
      ok: true,
      limits,
      message: 'Limitler kaydedildi — immunity, signal_engine ve OMS birkaç saniye içinde günceller.',
    })
  } catch (e) {
    const msg = String(e)
    if (msg.includes('system_risk_limits') || msg.includes('does not exist')) {
      return NextResponse.json(
        {
          error:
            'Tablo yok. Sunucuda çalıştırın: psql ... -f infrastructure/postgres/migrations/002_system_risk_limits.sql',
        },
        { status: 503 },
      )
    }
    return NextResponse.json({ error: msg }, { status: 500 })
  } finally {
    await closePostgresPool()
  }
}
