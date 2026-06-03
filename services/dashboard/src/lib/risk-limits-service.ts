import { createRedis } from '@/app/api/_redis'
import { getPostgresPool } from '@/lib/postgres'
import {
  RISK_LIMITS_DEFAULTS,
  SELECT_SQL,
  rowToLimits,
  type RiskLimitsConfig,
} from '@/lib/risk-limits-config'

export const REDIS_KEY = 'system:risk_limits:v1'
export const REDIS_CHANNEL = 'ch:risk_limits:updated'

export async function loadRiskLimitsFromDb(): Promise<RiskLimitsConfig | null> {
  const pool = getPostgresPool()
  try {
    const res = await pool.query(SELECT_SQL)
    if (res.rows.length === 0) return null
    return rowToLimits(res.rows[0] as Record<string, unknown>)
  } catch (e) {
    console.error('[risk-limits] db read failed', e)
    return null
  }
}

export async function loadRiskLimitsFromRedis(): Promise<RiskLimitsConfig | null> {
  const redis = createRedis()
  try {
    const raw = await redis.get(REDIS_KEY)
    if (!raw) return null
    return { ...RISK_LIMITS_DEFAULTS, ...JSON.parse(raw) } as RiskLimitsConfig
  } catch {
    return null
  } finally {
    redis.disconnect()
  }
}

export async function publishRiskLimitsToRedis(limits: RiskLimitsConfig): Promise<void> {
  const redis = createRedis()
  try {
    const payload = JSON.stringify({
      ...limits,
      updated_at: limits.updated_at ?? Date.now() / 1000,
    })
    await redis.set(REDIS_KEY, payload)
    await redis.publish(REDIS_CHANNEL, payload)
  } finally {
    redis.disconnect()
  }
}

/** DB is source of truth; fill Redis when empty so Python services pick up limits. */
export async function resolveRiskLimits(opts?: {
  syncRedisIfMissing?: boolean
}): Promise<{ limits: RiskLimitsConfig; source: 'database' | 'redis' | 'defaults' }> {
  const fromDb = await loadRiskLimitsFromDb()
  if (fromDb) {
    if (opts?.syncRedisIfMissing !== false) {
      const cached = await loadRiskLimitsFromRedis()
      if (!cached) {
        await publishRiskLimitsToRedis(fromDb)
      }
    }
    return { limits: fromDb, source: 'database' }
  }
  const fromRedis = await loadRiskLimitsFromRedis()
  if (fromRedis) return { limits: fromRedis, source: 'redis' }
  return { limits: RISK_LIMITS_DEFAULTS, source: 'defaults' }
}

export function limitsToApiShape(limits: RiskLimitsConfig) {
  return {
    max_drawdown: 0.1,
    max_daily_loss: limits.max_daily_loss_pct,
    max_position_pct: limits.max_position_pct,
    min_confidence: limits.min_signal_confidence,
    min_immunity_confidence: limits.min_immunity_confidence,
    max_trades_per_day: limits.max_trades_per_day,
    max_leverage: limits.max_leverage,
    max_open_positions: limits.max_open_positions,
  }
}
