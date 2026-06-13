/** Redis ticker / features / kline → tek mark fiyat (shadow price_resolver ile uyumlu). */

function priceFromDict(data: Record<string, unknown>): number {
  for (const key of ['close', 'last_price', 'mark_price', 'c', 'price']) {
    const p = parseFloat(String(data[key] ?? 0))
    if (p > 0) return p
  }
  return 0
}

export function midFromTickerRaw(raw: string | null): number {
  if (!raw) return 0
  try {
    const t = JSON.parse(raw) as { data?: Record<string, unknown> }
    const d = (t.data ?? t) as Record<string, unknown>
    const bid = parseFloat(String(d.b ?? d.bid ?? 0))
    const ask = parseFloat(String(d.a ?? d.ask ?? bid))
    if (bid > 0) return ask > 0 ? (bid + ask) / 2 : bid
    return ask > 0 ? ask : 0
  } catch {
    return 0
  }
}

export function priceFromFeaturesRaw(raw: string | null): number {
  if (!raw) return 0
  try {
    return priceFromDict(JSON.parse(raw) as Record<string, unknown>)
  } catch {
    return 0
  }
}

export function priceFromKlineRaw(raw: string | null): number {
  if (!raw) return 0
  try {
    const k = JSON.parse(raw) as { data?: Record<string, unknown> }
    const payload = (k.data ?? k) as Record<string, unknown>
    const candle = payload.k as Record<string, unknown> | undefined
    if (candle) {
      const c = parseFloat(String(candle.c ?? 0))
      if (c > 0) return c
    }
    return priceFromDict(payload)
  } catch {
    return 0
  }
}

export function priceFromKlines1hRaw(raw: string | null): number {
  if (!raw) return 0
  try {
    const arr = JSON.parse(raw) as unknown
    if (!Array.isArray(arr) || !arr.length) return 0
    const last = arr[arr.length - 1] as Record<string, unknown>
    return parseFloat(String(last.close ?? 0)) || 0
  } catch {
    return 0
  }
}

export function resolveMarkPrice(inputs: {
  tickerRaw?: string | null
  featRaw?: string | null
  klineRaw?: string | null
  klines1hRaw?: string | null
  storedMark?: number
  storedQuoteTs?: number
  maxQuoteAgeSec?: number
}): number {
  const maxAge = inputs.maxQuoteAgeSec ?? 15
  const stored = inputs.storedMark ?? 0
  const ts = inputs.storedQuoteTs ?? 0
  if (stored > 0 && ts > 0 && Date.now() / 1000 - ts <= maxAge) {
    return stored
  }

  let p = midFromTickerRaw(inputs.tickerRaw ?? null)
  if (p > 0) return p
  p = priceFromFeaturesRaw(inputs.featRaw ?? null)
  if (p > 0) return p
  p = priceFromKlineRaw(inputs.klineRaw ?? null)
  if (p > 0) return p
  return priceFromKlines1hRaw(inputs.klines1hRaw ?? null)
}
