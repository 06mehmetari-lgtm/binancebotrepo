/** Grafik beyni — blueprint / canlı / analiz / tahmin / konsensüs */

export type ChartPoint = {
  ts: number
  price: number
  pnl_pct?: number
  upnl_pct?: number
  delta_pct?: number
  blueprint_price?: number
  kind: 'live' | 'blueprint' | 'planned' | 'forecast' | 'delta' | 'analysis'
}

export type ChartConsensus = {
  action: string
  urgency: string
  score: number
  reasons: string[]
  layers?: Record<string, string>
}

export type RollingAnalysis = {
  status: string
  narrative: string
  trend?: string
  velocity_pct_per_min?: number
  points?: ChartPoint[]
  mismatch?: MismatchInfo
}

export type MismatchInfo = {
  pct: number
  severity: 'ok' | 'drift' | 'warn' | 'critical'
  vs_planned: number
  vs_forecast: number
  aligned?: boolean
  adverse?: boolean
  favorable?: boolean
  why?: string
}

export type EntryBlueprint = {
  frozen_at?: number
  narrative?: string
  reasons?: string[]
  action?: string
  confidence?: number
  regime?: string
  blueprint_curve?: ChartPoint[]
}

export type PositionChartPayload = {
  symbol: string
  direction: string
  entry_price: number
  entry_ts: number
  current_price: number
  unrealized_pct: number
  mismatch: MismatchInfo
  consensus?: ChartConsensus
  rolling?: RollingAnalysis
  blueprint?: EntryBlueprint
  why_move?: string
  llm_lesson?: string | null
  stop_loss?: number | null
  take_profit_prices?: number[]
  tiers_pct?: number[]
  fills?: { tier?: number; price: number; size_usd?: number; reason?: string; ts: number }[]
  live: ChartPoint[]
  blueprint_curve: ChartPoint[]
  planned: ChartPoint[]
  forecast: ChartPoint[]
  delta: ChartPoint[]
  analysis: ChartPoint[]
  updated_at: number
}

export const MISMATCH_COLORS: Record<string, string> = {
  ok: '#22c55e',
  drift: '#eab308',
  warn: '#f97316',
  critical: '#ef4444',
}

export const ACTION_COLORS: Record<string, string> = {
  hold: '#22c55e',
  trail_profit: '#38bdf8',
  tighten_stop: '#facc15',
  take_partial: '#fb923c',
  close: '#ef4444',
}

export function severityLabel(sev: string): string {
  if (sev === 'critical') return 'Kritik — plan bozuldu'
  if (sev === 'warn') return 'Uyarı — sapma büyüyor'
  if (sev === 'drift') return 'Hafif sapma'
  return 'Blueprint ile uyumlu'
}

export function actionLabel(action: string): string {
  const m: Record<string, string> = {
    hold: 'TUT — kâr yolunda',
    trail_profit: 'TRAILING — kârı koru',
    tighten_stop: 'STOP SIKILAŞTIR',
    take_partial: 'KISMİ SAT',
    close: 'KAPAT',
  }
  return m[action] ?? action
}
