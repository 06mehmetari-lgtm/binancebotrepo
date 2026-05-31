import type { Redis } from 'ioredis'
import { scanKeys } from '@/lib/universe'

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
}

function tickerMid(raw: string | null): number {
  if (!raw) return 0
  try {
    const t = JSON.parse(raw) as { data?: { b?: string; a?: string } }
    const d = t.data ?? t
    const bid = parseFloat(String((d as { b?: string }).b ?? 0))
    const ask = parseFloat(String((d as { a?: string }).a ?? bid))
    return bid > 0 && ask > 0 ? (bid + ask) / 2 : bid || ask
  } catch {
    return 0
  }
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
  for (const r of raws) pipeline.get(`signal:latest:${r.symbol}`)
  for (const r of raws) pipeline.get(`agents:verdict:${r.symbol}`)
  for (const r of raws) pipeline.get(`agents:verdicts:${r.symbol}`)

  const n = raws.length
  const exec = await pipeline.exec()

  const positions: PositionDecision[] = []

  for (let i = 0; i < n; i++) {
    const posRaw = exec?.[i]?.[1] as string | null
    const posObj = safeJson(posRaw) as Record<string, unknown> | null
    if (!posObj) continue

    const tickerRaw = exec?.[n + i]?.[1] as string | null
    const sigRaw = exec?.[2 * n + i]?.[1] as string | null
    const verdictRaw = exec?.[3 * n + i]?.[1] as string | null
    const votesRaw = exec?.[4 * n + i]?.[1] as string | null

    const currentPrice = tickerMid(tickerRaw)
    const entryPrice = Number(posObj.entry_price ?? posObj.price ?? 0)
    const direction = String(posObj.direction ?? 'long')
    const sizeUsd = Number(posObj.size_usd ?? 0)

    let unrealizedPct = 0
    let unrealizedUsdt = 0
    if (currentPrice > 0 && entryPrice > 0 && sizeUsd > 0) {
      unrealizedPct =
        direction === 'long'
          ? ((currentPrice - entryPrice) / entryPrice) * 100
          : ((entryPrice - currentPrice) / entryPrice) * 100
      unrealizedUsdt = sizeUsd * (unrealizedPct / 100)
    }

    const entryTime = Number(posObj.entry_time ?? posObj.time ?? 0)
    const ageSeconds = entryTime ? Date.now() / 1000 - entryTime : 0

    const entrySignal = (posObj.entry_signal ?? {}) as Record<string, unknown>
    const currentSignal = safeJson(sigRaw) as Record<string, unknown> | null
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

    positions.push({
      symbol: raws[i].symbol,
      direction,
      size_usd: sizeUsd,
      entry_price: entryPrice,
      entry_time: entryTime || undefined,
      current_price: currentPrice > 0 ? currentPrice : null,
      unrealized_pct: +unrealizedPct.toFixed(3),
      unrealized_usdt: +unrealizedUsdt.toFixed(4),
      age_hours: +(ageSeconds / 3600).toFixed(1),
      source: raws[i].source,
      shadow_id: raws[i].shadow_id,
      entry_signal: Object.keys(entrySignal).length ? entrySignal : undefined,
      current_signal: currentSignal ?? undefined,
      verdict,
      votes: Array.isArray(votes) ? votes : [],
      trade_action: currentSignal?.trade_action as string | undefined,
      open_reason: openReason,
    })
  }

  const longN = positions.filter(p => p.direction === 'long').length
  const shortN = positions.filter(p => p.direction === 'short').length

  return {
    positions,
    portfolio: {
      total_open: pf?.total_open ?? positions.length,
      oms_open: pf?.oms_open ?? positions.filter(p => p.source === 'oms').length,
      shadow_open: pf?.shadow_open ?? positions.filter(p => p.source === 'shadow').length,
      long_positions: pf?.long_positions ?? longN,
      short_positions: pf?.short_positions ?? shortN,
      updated_at: pf?.updated_at,
    },
  }
}
