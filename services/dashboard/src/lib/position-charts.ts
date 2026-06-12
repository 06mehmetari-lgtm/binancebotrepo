/** Açık pozisyon — planlı / canlı / fark / tahmin grafik verisi */

export type ChartPoint = {
  ts: number
  price: number
  pnl_pct?: number
  kind: 'live' | 'planned' | 'forecast' | 'delta'
}

export type PositionChartPayload = {
  symbol: string
  direction: string
  entry_price: number
  entry_ts: number
  current_price: number
  unrealized_pct: number
  mismatch: {
    pct: number
    severity: 'ok' | 'drift' | 'warn' | 'critical'
    vs_planned: number
    vs_forecast: number
  }
  stop_loss?: number | null
  take_profit_prices?: number[]
  tiers_pct?: number[]
  fills?: { tier?: number; price: number; size_usd?: number; reason?: string; ts: number }[]
  live: ChartPoint[]
  planned: ChartPoint[]
  forecast: ChartPoint[]
  delta: ChartPoint[]
  updated_at: number
}

export const MISMATCH_COLORS: Record<string, string> = {
  ok: '#22c55e',
  drift: '#eab308',
  warn: '#f97316',
  critical: '#ef4444',
}

export function severityLabel(sev: string): string {
  if (sev === 'critical') return 'Kritik uyumsuzluk'
  if (sev === 'warn') return 'Plan sapması'
  if (sev === 'drift') return 'Hafif sapma'
  return 'Plan ile uyumlu'
}
