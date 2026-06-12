/** Normalize Redis /api/backtest payloads for the backtest UI (continuous + legacy shapes). */

export function safeNum(v: unknown, fallback = 0): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : fallback
}

export type NormalizedSymbol = {
  symbol: string
  total_trades: number
  win_rate_pct: number
  avg_win_pct: number
  avg_loss_pct: number
  profit_factor: number
  total_return_pct: number
  sharpe_ratio: number
  max_drawdown_pct: number
  final_capital: number
  long_trades: number
  short_trades: number
  long_win_rate_pct: number
  short_win_rate_pct: number
  avg_bars_held: number
  exit_reasons: Record<string, number>
  monthly_returns: { month: string; return_pct: number; capital: number }[]
  walk_forward?: boolean
  folds?: number
}

export type NormalizedSummary = {
  symbols_tested: number
  universe_target?: number
  total_trades: number
  avg_win_rate_pct: number
  portfolio_sharpe: number
  avg_return_pct: number
  avg_max_drawdown_pct: number
  avg_profit_factor: number
  top5_symbols: string[]
  bottom5_symbols: string[]
  days_tested: number
  completed_at: number
  elapsed_seconds: number
  avg_monthly_returns: Record<string, number>
}

export type NormalizedConfig = {
  atr_sl_mult: number
  atr_tp_mult: number
  rr_ratio: number
  max_position_pct: number
  confidence_threshold_pct: number
  max_hold_bars: number
  fee_round_trip_pct: number
  interval: string
  chunk_size?: number
  total_symbols?: number
}

export type NormalizedBacktest = {
  summary: NormalizedSummary
  symbols: NormalizedSymbol[]
  config: NormalizedConfig
}

function normalizeSymbolRow(row: unknown, symbolHint?: string): NormalizedSymbol | null {
  if (!row || typeof row !== 'object') return null
  const r = row as Record<string, unknown>
  const symbol = String(r.symbol ?? symbolHint ?? '')
  if (!symbol.endsWith('USDT')) return null

  const winRate =
    typeof r.win_rate_pct === 'number'
      ? r.win_rate_pct
      : typeof r.win_rate === 'number'
        ? r.win_rate <= 1
          ? r.win_rate * 100
          : r.win_rate
        : 0

  const exitRaw = r.exit_reasons
  const exit_reasons: Record<string, number> =
    exitRaw && typeof exitRaw === 'object' && !Array.isArray(exitRaw)
      ? Object.fromEntries(
          Object.entries(exitRaw as Record<string, unknown>).map(([k, v]) => [k, safeNum(v)])
        )
      : {}

  const monthlyRaw = r.monthly_returns
  const monthly_returns = Array.isArray(monthlyRaw)
    ? monthlyRaw
        .filter(m => m && typeof m === 'object')
        .map(m => {
          const x = m as Record<string, unknown>
          return {
            month: String(x.month ?? ''),
            return_pct: safeNum(x.return_pct),
            capital: safeNum(x.capital),
          }
        })
    : []

  return {
    symbol,
    total_trades: safeNum(r.total_trades),
    win_rate_pct: winRate,
    avg_win_pct: safeNum(r.avg_win_pct),
    avg_loss_pct: safeNum(r.avg_loss_pct),
    profit_factor: safeNum(r.profit_factor),
    total_return_pct: safeNum(r.total_return_pct),
    sharpe_ratio: safeNum(r.sharpe_ratio ?? r.sharpe),
    max_drawdown_pct: safeNum(r.max_drawdown_pct),
    final_capital: safeNum(r.final_capital),
    long_trades: safeNum(r.long_trades),
    short_trades: safeNum(r.short_trades),
    long_win_rate_pct: safeNum(r.long_win_rate_pct),
    short_win_rate_pct: safeNum(r.short_win_rate_pct),
    avg_bars_held: safeNum(r.avg_bars_held),
    exit_reasons,
    monthly_returns,
    walk_forward: Boolean(r.walk_forward),
    folds: safeNum(r.folds) || undefined,
  }
}

function aggregateMonthly(symbols: NormalizedSymbol[]): Record<string, number> {
  const acc: Record<string, { sum: number; n: number }> = {}
  for (const s of symbols) {
    for (const m of s.monthly_returns) {
      if (!m.month) continue
      if (!acc[m.month]) acc[m.month] = { sum: 0, n: 0 }
      acc[m.month].sum += m.return_pct
      acc[m.month].n += 1
    }
  }
  const out: Record<string, number> = {}
  for (const [month, { sum, n }] of Object.entries(acc)) {
    if (n > 0) out[month] = Math.round((sum / n) * 10) / 10
  }
  return out
}

function normalizeSummary(
  raw: unknown,
  symbols: NormalizedSymbol[]
): NormalizedSummary | null {
  const s = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  if (!symbols.length && !raw) return null

  const sorted = [...symbols].sort((a, b) => b.sharpe_ratio - a.sharpe_ratio)
  const top5 =
    Array.isArray(s.top5_symbols) && s.top5_symbols.length
      ? (s.top5_symbols as string[])
      : sorted.slice(0, 5).map(x => x.symbol)
  const bottom5 =
    Array.isArray(s.bottom5_symbols) && s.bottom5_symbols.length
      ? (s.bottom5_symbols as string[])
      : sorted.slice(-5).map(x => x.symbol)

  const monthlyRaw = s.avg_monthly_returns
  const avg_monthly_returns =
    monthlyRaw && typeof monthlyRaw === 'object' && !Array.isArray(monthlyRaw)
      ? Object.fromEntries(
          Object.entries(monthlyRaw as Record<string, unknown>).map(([k, v]) => [
            k,
            safeNum(v),
          ])
        )
      : aggregateMonthly(symbols)

  const totalTrades =
    safeNum(s.total_trades) ||
    symbols.reduce((sum, x) => sum + x.total_trades, 0)

  return {
    symbols_tested: safeNum(s.symbols_tested) || symbols.length,
    universe_target: safeNum(s.universe_target) || undefined,
    total_trades: totalTrades,
    avg_win_rate_pct: safeNum(s.avg_win_rate_pct),
    portfolio_sharpe: safeNum(s.portfolio_sharpe),
    avg_return_pct: safeNum(s.avg_return_pct),
    avg_max_drawdown_pct: safeNum(s.avg_max_drawdown_pct),
    avg_profit_factor: safeNum(s.avg_profit_factor),
    top5_symbols: top5,
    bottom5_symbols: bottom5,
    days_tested: safeNum(s.days_tested) || 365,
    completed_at: safeNum(s.completed_at) || Date.now() / 1000,
    elapsed_seconds: safeNum(s.elapsed_seconds),
    avg_monthly_returns,
  }
}

function normalizeConfig(raw: unknown): NormalizedConfig {
  const c = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  return {
    atr_sl_mult: safeNum(c.atr_sl_mult, 1.5),
    atr_tp_mult: safeNum(c.atr_tp_mult, 3),
    rr_ratio: safeNum(c.rr_ratio, 2),
    max_position_pct: safeNum(c.max_position_pct, 5),
    confidence_threshold_pct: safeNum(c.confidence_threshold_pct, 60),
    max_hold_bars: safeNum(c.max_hold_bars, 48),
    fee_round_trip_pct: safeNum(c.fee_round_trip_pct, 0.1),
    interval: String(c.interval ?? '1h'),
    chunk_size: c.chunk_size != null ? safeNum(c.chunk_size) : undefined,
    total_symbols: c.total_symbols != null ? safeNum(c.total_symbols) : undefined,
  }
}

export function normalizeBacktestResults(raw: unknown): NormalizedBacktest | null {
  if (!raw || typeof raw !== 'object') return null
  const root = raw as Record<string, unknown>

  let summaryRaw = root.summary
  let configRaw = root.config
  let symbolRows: unknown[] = []

  if (Array.isArray(root.symbols)) {
    symbolRows = root.symbols
  } else {
    for (const [k, v] of Object.entries(root)) {
      if (k === 'summary') summaryRaw = v
      else if (k === 'config') configRaw = v
      else if (k.endsWith('USDT')) symbolRows.push({ ...(v as object), symbol: k })
    }
  }

  const symbols = symbolRows
    .map(row => normalizeSymbolRow(row))
    .filter((x): x is NormalizedSymbol => x !== null)

  const summary = normalizeSummary(summaryRaw, symbols)
  if (!summary && !symbols.length) return null
  if (!summary) return null

  return {
    summary,
    symbols,
    config: normalizeConfig(configRaw),
  }
}

export type BacktestApiPayload = {
  results: unknown
  status: unknown
  trigger_pending?: boolean
  logs?: unknown
  queue?: unknown
  error?: string
}

export function parseBacktestApiResponse(d: BacktestApiPayload) {
  return {
    results: normalizeBacktestResults(d.results),
    status:
      d.status && typeof d.status === 'object'
        ? (d.status as Record<string, unknown>)
        : null,
    trigger_pending: Boolean(d.trigger_pending),
    logs: Array.isArray(d.logs) ? d.logs : [],
    queue: d.queue ?? null,
    error: d.error ?? null,
  }
}
