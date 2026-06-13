export interface RiskLimitsConfig {
  max_leverage: number
  min_leverage: number
  max_position_pct: number
  max_daily_loss_pct: number
  max_open_positions: number
  min_signal_confidence: number
  min_immunity_confidence: number
  max_trades_per_day: number
  updated_at?: number
  updated_by?: string
}

export const RISK_LIMITS_DEFAULTS: RiskLimitsConfig = {
  max_leverage: 15,
  min_leverage: 5,
  max_position_pct: 0.05,
  max_daily_loss_pct: 0.02,
  max_open_positions: 30,
  min_signal_confidence: 0.6,
  min_immunity_confidence: 0.52,
  max_trades_per_day: 50,
}

export function validateRiskLimits(input: Partial<RiskLimitsConfig>): string[] {
  const errors: string[] = []
  const l = { ...RISK_LIMITS_DEFAULTS, ...input }
  if (l.max_leverage < 1 || l.max_leverage > 125) errors.push('Kaldıraç 1–125')
  if (l.min_leverage < 1 || l.min_leverage > 125) errors.push('Min kaldıraç 1–125')
  if (l.min_leverage > l.max_leverage) errors.push('Min kaldıraç, max kaldıraçtan büyük olamaz')
  if (l.max_position_pct < 0.001 || l.max_position_pct > 1) errors.push('Max pozisyon %0.1–100')
  if (l.max_daily_loss_pct < 0.001 || l.max_daily_loss_pct > 1) errors.push('Günlük kayıp %0.1–100')
  if (l.max_open_positions < 1 || l.max_open_positions > 500) errors.push('Açık pozisyon 1–500')
  if (l.min_signal_confidence < 0.1 || l.min_signal_confidence > 1) errors.push('Min sinyal güveni 10–100%')
  if (l.min_immunity_confidence < 0.1 || l.min_immunity_confidence > 1) errors.push('Min immunity güveni 10–100%')
  if (l.max_trades_per_day < 1 || l.max_trades_per_day > 10000) errors.push('Günlük işlem 1–10000')
  return errors
}

export function rowToLimits(row: Record<string, unknown>): RiskLimitsConfig {
  return {
    max_leverage: Number(row.max_leverage),
    min_leverage: Number(row.min_leverage ?? RISK_LIMITS_DEFAULTS.min_leverage),
    max_position_pct: Number(row.max_position_pct),
    max_daily_loss_pct: Number(row.max_daily_loss_pct),
    max_open_positions: Number(row.max_open_positions),
    min_signal_confidence: Number(row.min_signal_confidence),
    min_immunity_confidence: Number(row.min_immunity_confidence),
    max_trades_per_day: Number(row.max_trades_per_day),
    updated_at: row.updated_at != null ? Number(row.updated_at) : undefined,
    updated_by: row.updated_by != null ? String(row.updated_by) : undefined,
  }
}

export const UPSERT_SQL = `
INSERT INTO system_risk_limits (
  id, max_leverage, min_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day, updated_by
) VALUES (1, $1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (id) DO UPDATE SET
  max_leverage = EXCLUDED.max_leverage,
  min_leverage = EXCLUDED.min_leverage,
  max_position_pct = EXCLUDED.max_position_pct,
  max_daily_loss_pct = EXCLUDED.max_daily_loss_pct,
  max_open_positions = EXCLUDED.max_open_positions,
  min_signal_confidence = EXCLUDED.min_signal_confidence,
  min_immunity_confidence = EXCLUDED.min_immunity_confidence,
  max_trades_per_day = EXCLUDED.max_trades_per_day,
  updated_by = EXCLUDED.updated_by,
  updated_at = NOW()
RETURNING max_leverage, min_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day,
  EXTRACT(EPOCH FROM updated_at) AS updated_at, updated_by
`

export const SELECT_SQL = `
SELECT max_leverage, min_leverage, max_position_pct, max_daily_loss_pct, max_open_positions,
  min_signal_confidence, min_immunity_confidence, max_trades_per_day,
  EXTRACT(EPOCH FROM updated_at) AS updated_at, updated_by
FROM system_risk_limits WHERE id = 1
`
