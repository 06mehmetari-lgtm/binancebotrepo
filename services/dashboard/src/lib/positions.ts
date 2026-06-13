import type { Redis } from 'ioredis'
import { scanKeys } from '@/lib/universe'
import { computeExitEstimate } from '@/lib/exit-estimate'
import { resolveMarkPrice } from '@/lib/mark-price'
import { computeUnrealizedPnL } from '@/lib/pnl'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export type PositionDecision = {
  symbol: string
  direction: string
  size_usd: number
  entry_price: number
  entry_time?: number
  current_price?: number | null
  unrealized_pct?: number
  unrealized_usdt?: number
  age_hours?: number
  source: 'oms' | 'shadow'
  shadow_id?: string
  entry_signal?: Record<string, unknown>
  current_signal?: Record<string, unknown>
  verdict?: {
    direction?: string
    confidence?: number
    consensus_reasoning?: string
    dissent_risk?: string
    probabilities?: { long_pct?: number; short_pct?: number; ai_confidence_pct?: number }
    targets?: Record<string, unknown>
  }
  votes?: { agent: string; signal: string; confidence: number; reasoning: string }[]
  trade_action?: string
  open_reason?: string
  guard?: {
    action?: string
    urgency?: string
    reason?: string
    unrealized_pct?: number
    ai_confidence?: number
    updated_at?: number
  }
  regime?: string
  context_regime?: string
  ai_confidence_pct?: number
  shadow_accounts?: number
  sources_label?: string
  ladder?: {
    tier?: number
    take_profit_pct?: number
    stop_loss_pct?: number
    entry_confidence?: number
    entry_reason?: string
    leverage?: number
    leverage_reasons?: string[]
    notional_usd?: number
    margin_usd?: number
    position_size_pct?: number
    slot_budget_usd?: number
    breakeven_armed?: boolean
    peak_upnl_pct?: number
    entry_lesson?: string
    learn_note?: string
  }
  leverage?: number
  /** Giriş anındaki kaldıraç (ladder'dan donmuş) */
  entry_leverage?: number
  notional_usd?: number
  margin_usd?: number
  qty_estimate?: number
  entry_at_label?: string
  exit_plan?: string
  leverage_reasons?: string[]
  hold_seconds?: number
  peak_upnl_pct?: number
  breakeven_armed?: boolean
  learning_stage?: string
  avoid_hint?: string
  best_entry_hint?: string
  last_lesson?: string
  learn_win_rate?: number
  learn_trades?: number
  exit_estimate?: {
    trigger: string
    label: string
    countdown_sec: number
    estimated_close_at: number
    urgency: 'now' | 'imminent' | 'normal'
    detail: string
    secondary?: string
  }
}

async function fetchBinanceMarkPrices(symbols: string[]): Promise<Record<string, number>> {
  const out: Record<string, number> = {}
  if (!symbols.length) return out
  await Promise.all(
    symbols.slice(0, 80).map(async sym => {
      try {
        const res = await fetch(
          `https://fapi.binance.com/fapi/v1/ticker/price?symbol=${sym}`,
          { cache: 'no-store', signal: AbortSignal.timeout(4000) },
        )
        if (!res.ok) return
        const j = (await res.json()) as { price?: string }
        const p = parseFloat(String(j.price ?? 0))
        if (p > 0) out[sym] = p
      } catch {
        /* REST yedek — sessiz */
      }
    }),
  )
  return out
}

/** Aynı sembol+yön: OMS öncelikli, shadow kopyaları tek satırda birleştirilir. */
export function consolidatePositions(rows: PositionDecision[]): PositionDecision[] {
  const map = new Map<string, PositionDecision>()
  for (const p of rows) {
    const key = `${p.symbol}:${p.direction}`
    const cur = map.get(key)
    if (!cur) {
      map.set(key, { ...p, shadow_accounts: p.source === 'shadow' ? 1 : 0 })
      continue
    }
    if (p.source === 'oms') {
      map.set(key, {
        ...p,
        shadow_accounts: cur.shadow_accounts,
        sources_label: cur.shadow_accounts ? 'oms+shadow' : 'oms',
        notional_usd: (p.notional_usd ?? 0) + (cur.notional_usd ?? 0),
        margin_usd: (p.margin_usd ?? p.size_usd) + (cur.margin_usd ?? cur.size_usd),
        unrealized_usdt: (p.unrealized_usdt ?? 0) + (cur.unrealized_usdt ?? 0),
        entry_leverage: p.entry_leverage ?? cur.entry_leverage,
        leverage: p.entry_leverage ?? p.leverage ?? cur.entry_leverage ?? cur.leverage,
      })
      continue
    }
    if (cur.source === 'oms') {
      map.set(key, {
        ...cur,
        size_usd: cur.size_usd + p.size_usd,
        margin_usd: (cur.margin_usd ?? cur.size_usd) + (p.margin_usd ?? p.size_usd),
        notional_usd: (cur.notional_usd ?? 0) + (p.notional_usd ?? 0),
        shadow_accounts: (cur.shadow_accounts ?? 0) + 1,
        sources_label: 'oms+shadow',
        unrealized_usdt: (cur.unrealized_usdt ?? 0) + (p.unrealized_usdt ?? 0),
        leverage: cur.entry_leverage ?? cur.leverage ?? p.entry_leverage ?? p.leverage,
        entry_leverage: cur.entry_leverage ?? p.entry_leverage,
      })
      continue
    }
    map.set(key, {
      ...cur,
      size_usd: cur.size_usd + p.size_usd,
      margin_usd: (cur.margin_usd ?? cur.size_usd) + (p.margin_usd ?? p.size_usd),
      notional_usd: (cur.notional_usd ?? 0) + (p.notional_usd ?? 0),
      shadow_accounts: (cur.shadow_accounts ?? 1) + 1,
      sources_label: `shadow×${(cur.shadow_accounts ?? 1) + 1}`,
      unrealized_usdt: (cur.unrealized_usdt ?? 0) + (p.unrealized_usdt ?? 0),
      entry_leverage: cur.entry_leverage ?? p.entry_leverage,
      leverage: cur.entry_leverage ?? cur.leverage ?? p.entry_leverage ?? p.leverage,
    })
  }
  return Array.from(map.values())
}

function fmtEntryTime(ts: number): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('tr-TR', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function buildExitPlan(
  ladder: PositionDecision['ladder'],
  guard: PositionDecision['guard'],
  unrealizedPct: number,
): string {
  const parts: string[] = []
  const sl = ladder?.stop_loss_pct
  const tp = ladder?.take_profit_pct
  if (sl) parts.push(`SL -${sl}%`)
  if (tp) parts.push(`TP +${tp}%`)
  if (guard?.action && guard.action !== 'hold') {
    parts.push(`Guard: ${guard.action}`)
  }
  if (unrealizedPct <= -(sl ?? 1.2)) parts.push('STOP yakın')
  if (unrealizedPct >= (tp ?? 1.5)) parts.push('TP yakın')
  return parts.length ? parts.join(' · ') : 'SL/TP ladder'
}

export async function fetchOpenPositions(redis: Redis): Promise<{
  positions: PositionDecision[]
  portfolio: {
    total_open: number
    oms_open: number
    shadow_open: number
    long_positions: number
    short_positions: number
    updated_at?: number
  }
}> {
  const pfRaw = await redis.get('portfolio:state:v1')
  const pf = safeJson(pfRaw) as {
    total_open?: number
    oms_open?: number
    shadow_open?: number
    long_positions?: number
    short_positions?: number
    updated_at?: number
    positions?: { symbol: string; direction: string; source?: string; shadow_id?: string }[]
  } | null

  const omsKeys = await scanKeys(redis, 'oms:position:*')
  const shadowKeys = await scanKeys(redis, 'shadow:positions:*')

  type RawPos = { key: string; symbol: string; source: 'oms' | 'shadow'; shadow_id?: string }
  const raws: RawPos[] = []

  for (const key of omsKeys) {
    const symbol = key.split(':').pop() ?? ''
    if (symbol.endsWith('USDT')) raws.push({ key, symbol, source: 'oms' })
  }
  for (const key of shadowKeys) {
    const parts = key.split(':')
    if (parts.length >= 4) {
      raws.push({
        key,
        symbol: parts[3],
        source: 'shadow',
        shadow_id: parts[2],
      })
    }
  }

  if (!raws.length && pf?.positions?.length) {
    for (const p of pf.positions) {
      if (p.symbol?.endsWith('USDT')) {
        raws.push({
          key: p.source === 'shadow' ? `shadow:positions:x:${p.symbol}` : `oms:position:${p.symbol}`,
          symbol: p.symbol,
          source: (p.source === 'shadow' ? 'shadow' : 'oms') as 'oms' | 'shadow',
          shadow_id: (p as { shadow_id?: string }).shadow_id,
        })
      }
    }
  }

  const pipeline = redis.pipeline()
  for (const r of raws) pipeline.get(r.key)
  for (const r of raws) pipeline.get(`binance:ticker:${r.symbol.toLowerCase()}`)
  for (const r of raws) pipeline.get(`features:latest:${r.symbol}`)
  for (const r of raws) pipeline.lindex(`binance:kline:${r.symbol.toLowerCase()}`, 0)
  for (const r of raws) pipeline.get(`klines:1h:${r.symbol}`)
  for (const r of raws) pipeline.get(`context:latest:${r.symbol}`)
  for (const r of raws) pipeline.get(`signal:latest:${r.symbol}`)
  for (const r of raws) pipeline.get(`agents:verdict:${r.symbol}`)
  for (const r of raws) pipeline.get(`agents:verdicts:${r.symbol}`)
  for (const r of raws) pipeline.get(`guard:position:${r.symbol}`)
  for (const r of raws) pipeline.get(`learn:profile:${r.symbol}`)
  for (const r of raws) pipeline.lindex(`trade:lessons:${r.symbol}`, 0)

  const n = raws.length
  const exec = await pipeline.exec()

  const KLINE_OFF = 2 * n
  const KLINES1H_OFF = 3 * n
  const CTX_OFF = 4 * n
  const SIG_OFF = 5 * n
  const VERDICT_OFF = 6 * n
  const VOTES_OFF = 7 * n
  const GUARD_OFF = 8 * n
  const LEARN_OFF = 9 * n
  const LESSON_OFF = 10 * n

  const positions: PositionDecision[] = []
  const needRestPrice: string[] = []

  for (let i = 0; i < n; i++) {
    const posRaw = exec?.[i]?.[1] as string | null
    const posObj = safeJson(posRaw) as Record<string, unknown> | null
    if (!posObj) continue

    const tickerRaw = exec?.[n + i]?.[1] as string | null
    const featRaw = exec?.[2 * n + i]?.[1] as string | null
    const klineRaw = exec?.[KLINE_OFF + i]?.[1] as string | null
    const klines1hRaw = exec?.[KLINES1H_OFF + i]?.[1] as string | null
    const ctxRaw = exec?.[CTX_OFF + i]?.[1] as string | null
    const sigRaw = exec?.[SIG_OFF + i]?.[1] as string | null
    const verdictRaw = exec?.[VERDICT_OFF + i]?.[1] as string | null
    const votesRaw = exec?.[VOTES_OFF + i]?.[1] as string | null
    const guardRaw = exec?.[GUARD_OFF + i]?.[1] as string | null
    const learnRaw = exec?.[LEARN_OFF + i]?.[1] as string | null
    const lessonRaw = exec?.[LESSON_OFF + i]?.[1] as string | null
    const guardParsed = safeJson(guardRaw) as Record<string, unknown> | null
    const learnParsed = safeJson(learnRaw) as Record<string, unknown> | null

    let currentPrice = resolveMarkPrice({
      tickerRaw,
      featRaw,
      klineRaw,
      klines1hRaw,
      storedMark: Number(posObj.mark_price ?? 0),
      storedQuoteTs: Number(posObj.quote_ts ?? 0),
    })
    const ctxParsed = safeJson(ctxRaw) as { regime?: string } | null
    const regime =
      String(ctxParsed?.regime ?? '') ||
      String((safeJson(sigRaw) as { regime?: string } | null)?.regime ?? '') ||
      'unknown'
    const entryPrice = Number(posObj.entry_price ?? posObj.price ?? 0)
    const direction = String(posObj.direction ?? 'long')
    const sizeUsd = Number(posObj.size_usd ?? 0)

    const entryTime = Number(posObj.entry_time ?? posObj.time ?? 0)
    const ageSeconds = entryTime ? Date.now() / 1000 - entryTime : 0

    const entrySignal = (posObj.entry_signal ?? {}) as Record<string, unknown>
    const currentSignal = safeJson(sigRaw) as Record<string, unknown> | null

    const ladder = (posObj.ladder ?? {}) as PositionDecision['ladder']
    const entryLeverage = Math.max(
      1,
      Number(
        ladder?.leverage ??
          (entrySignal as { leverage?: number }).leverage ??
          1,
      ),
    )
    const leverage = entryLeverage
    const marginUsd = Number(
      posObj.margin_usd ?? ladder?.margin_usd ?? posObj.size_usd ?? sizeUsd,
    )
    const notionalUsd = Number(
      ladder?.notional_usd ?? marginUsd * leverage,
    )

    if (currentPrice <= 0 && raws[i].symbol) {
      needRestPrice.push(raws[i].symbol)
    }

    const storedUpnlPct = Number(posObj.upnl_pct ?? 0)
    const storedUpnlUsdt = Number(posObj.upnl_usdt ?? 0)
    const quoteFresh =
      Number(posObj.quote_ts ?? 0) > 0 &&
      Date.now() / 1000 - Number(posObj.quote_ts) <= 20

    let unrealizedPct = 0
    let unrealizedUsdt = 0
    if (currentPrice > 0 && entryPrice > 0) {
      const live = computeUnrealizedPnL({
        direction,
        entryPrice,
        currentPrice,
        marginUsd,
        leverage,
        notionalUsd,
      })
      unrealizedPct = live.pct
      unrealizedUsdt = live.usdt
    } else if (quoteFresh && storedUpnlPct !== 0) {
      unrealizedPct = storedUpnlPct
      unrealizedUsdt = storedUpnlUsdt
      if (currentPrice <= 0 && entryPrice > 0 && unrealizedPct !== 0) {
        const factor = 1 + (direction === 'long' ? unrealizedPct : -unrealizedPct) / 100
        currentPrice = entryPrice * factor
      }
    } else if (guardParsed?.unrealized_pct != null) {
      unrealizedPct = Number(guardParsed.unrealized_pct)
      unrealizedUsdt = computeUnrealizedPnL({
        direction,
        entryPrice,
        currentPrice: entryPrice,
        marginUsd,
        leverage,
        notionalUsd,
      }).usdt
      if (unrealizedPct !== 0 && entryPrice > 0) {
        const factor = 1 + (direction === 'long' ? unrealizedPct : -unrealizedPct) / 100
        currentPrice = entryPrice * factor
        unrealizedUsdt = computeUnrealizedPnL({
          direction,
          entryPrice,
          currentPrice,
          marginUsd,
          leverage,
          notionalUsd,
        }).usdt
      }
    }

    if (
      raws[i].symbol &&
      currentPrice > 0 &&
      entryPrice > 0 &&
      Math.abs(currentPrice - entryPrice) / entryPrice < 1e-8 &&
      unrealizedPct === 0
    ) {
      needRestPrice.push(raws[i].symbol)
    }

    const qtyEstimate =
      entryPrice > 0 && notionalUsd > 0 ? notionalUsd / entryPrice : undefined

    const verdictParsed = safeJson(verdictRaw) as Record<string, unknown> | null
    const votes = votesRaw ? (safeJson(votesRaw) as PositionDecision['votes']) : []

    const verdict = verdictParsed
      ? ({
          direction: String(verdictParsed.direction ?? ''),
          confidence: Number(verdictParsed.confidence ?? 0),
          consensus_reasoning: String(
            verdictParsed.consensus_reasoning ?? verdictParsed.reasoning ?? ''
          ),
          dissent_risk: String(verdictParsed.dissent_risk ?? ''),
          probabilities: verdictParsed.probabilities as {
            long_pct?: number
            short_pct?: number
            ai_confidence_pct?: number
          },
          targets: verdictParsed.targets as Record<string, unknown>,
        } satisfies NonNullable<PositionDecision['verdict']>)
      : undefined

    const openReason =
      String(entrySignal.consensus_reasoning ?? entrySignal.reasoning ?? '') ||
      verdict?.consensus_reasoning ||
      String(currentSignal?.consensus_reasoning ?? currentSignal?.reject_reason ?? '') ||
      (direction === 'long'
        ? 'Long pozisyon — giriş sinyali ensemble + ajan onayı ile açıldı'
        : 'Short pozisyon — giriş sinyali ensemble + ajan onayı ile açıldı')

    const aiConf = verdict?.confidence ?? Number(currentSignal?.confidence ?? 0)

    const guardBlock = guardParsed
        ? {
            action: String(guardParsed.action ?? 'hold'),
            urgency: String(guardParsed.urgency ?? 'low'),
            reason: String(guardParsed.reason ?? ''),
            unrealized_pct: Number(guardParsed.unrealized_pct ?? unrealizedPct),
            ai_confidence: Number(guardParsed.ai_confidence ?? 0),
            updated_at: Number(guardParsed.ts ?? 0),
          }
        : undefined

    const peakUpnl = Number(ladder?.peak_upnl_pct ?? 0)
    const breakevenArmed = Boolean(ladder?.breakeven_armed)
    const holdSeconds = entryTime ? Math.floor(ageSeconds) : 0
    const exitEstimate = computeExitEstimate({
      entry_time: entryTime || undefined,
      direction,
      unrealized_pct: unrealizedPct,
      ladder,
      guard: guardBlock,
      current_signal_direction: String(currentSignal?.direction ?? 'flat'),
    })

    let lastLesson = String(ladder?.entry_lesson ?? '')
    if (!lastLesson && lessonRaw) {
      const lessonObj = safeJson(lessonRaw) as { text?: string } | null
      lastLesson = String(lessonObj?.text ?? lessonRaw ?? '').slice(0, 200)
    }

    positions.push({
      symbol: raws[i].symbol,
      direction,
      size_usd: marginUsd,
      margin_usd: marginUsd,
      notional_usd: +notionalUsd.toFixed(2),
      leverage,
      entry_leverage: entryLeverage,
      qty_estimate: qtyEstimate ? +qtyEstimate.toFixed(6) : undefined,
      entry_price: entryPrice,
      entry_time: entryTime || undefined,
      entry_at_label: fmtEntryTime(entryTime),
      current_price: currentPrice > 0 ? currentPrice : null,
      unrealized_pct: +unrealizedPct.toFixed(3),
      unrealized_usdt: +unrealizedUsdt.toFixed(4),
      age_hours: +(ageSeconds / 3600).toFixed(1),
      hold_seconds: holdSeconds,
      peak_upnl_pct: peakUpnl > 0 ? peakUpnl : undefined,
      breakeven_armed: breakevenArmed || undefined,
      exit_estimate: exitEstimate,
      source: raws[i].source,
      shadow_id: raws[i].shadow_id,
      entry_signal: Object.keys(entrySignal).length ? entrySignal : undefined,
      current_signal: currentSignal ?? undefined,
      verdict,
      votes: Array.isArray(votes) ? votes : [],
      trade_action: currentSignal?.trade_action as string | undefined,
      open_reason: openReason,
      ladder,
      leverage_reasons: ladder?.leverage_reasons,
      exit_plan: buildExitPlan(ladder, guardBlock, unrealizedPct),
      learning_stage: learnParsed ? String(learnParsed.learning_stage ?? 'L0') : undefined,
      avoid_hint: learnParsed ? String(learnParsed.avoid_hint ?? '') : undefined,
      best_entry_hint: learnParsed ? String(learnParsed.best_entry_hint ?? '') : undefined,
      learn_win_rate: learnParsed ? Number(learnParsed.win_rate ?? 0) : undefined,
      learn_trades: learnParsed ? Number(learnParsed.trades ?? 0) : undefined,
      last_lesson: lastLesson || undefined,
      regime,
      context_regime: regime,
      ai_confidence_pct: aiConf > 0 ? Math.round(aiConf * 100) : undefined,
      guard: guardBlock,
    })
  }

  if (needRestPrice.length) {
    const restPrices = await fetchBinanceMarkPrices(Array.from(new Set(needRestPrice)))
    for (const p of positions) {
      const mark = restPrices[p.symbol]
      if (!mark || mark <= 0 || !p.entry_price) continue
      const live = computeUnrealizedPnL({
        direction: p.direction,
        entryPrice: p.entry_price,
        currentPrice: mark,
        marginUsd: p.margin_usd ?? p.size_usd,
        leverage: p.leverage,
        notionalUsd: p.notional_usd,
      })
      p.current_price = mark
      p.unrealized_pct = +live.pct.toFixed(3)
      p.unrealized_usdt = +live.usdt.toFixed(4)
    }
  }

  const consolidated = consolidatePositions(positions)
  const longN = consolidated.filter(p => p.direction === 'long').length
  const shortN = consolidated.filter(p => p.direction === 'short').length

  return {
    positions: consolidated,
    portfolio: {
      total_open: consolidated.length,
      oms_open: consolidated.filter(p => p.source === 'oms').length,
      shadow_open: consolidated.filter(p => p.shadow_accounts && p.shadow_accounts > 0).length,
      long_positions: pf?.long_positions ?? longN,
      short_positions: pf?.short_positions ?? shortN,
      updated_at: pf?.updated_at,
    },
  }
}
