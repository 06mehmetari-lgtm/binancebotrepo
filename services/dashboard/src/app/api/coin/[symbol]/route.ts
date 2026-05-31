import { NextResponse } from 'next/server'
import { createRedis } from '../../_redis'

// ── Indicator helpers ────────────────────────────────────────────────────────

function ema(values: number[], period: number): number[] {
  const k = 2 / (period + 1)
  const out = new Array(values.length).fill(NaN)
  let sum = 0, count = 0
  for (let i = 0; i < values.length; i++) {
    if (isNaN(values[i])) continue
    if (count < period) { sum += values[i]; count++ }
    if (count === period) {
      out[i] = sum / period
      for (let j = i + 1; j < values.length; j++) {
        if (!isNaN(values[j])) out[j] = values[j] * k + out[j - 1] * (1 - k)
        else out[j] = out[j - 1]
      }
      break
    }
  }
  return out
}

function computeRSI(closes: number[], period = 14): number[] {
  const out = new Array(closes.length).fill(NaN)
  if (closes.length < period + 1) return out
  let ag = 0, al = 0
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1]
    if (d > 0) ag += d; else al += Math.abs(d)
  }
  ag /= period; al /= period
  out[period] = al === 0 ? 100 : 100 - 100 / (1 + ag / al)
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    ag = (ag * (period - 1) + Math.max(d, 0)) / period
    al = (al * (period - 1) + Math.max(-d, 0)) / period
    out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al)
  }
  return out
}

function computeMACD(closes: number[]): { macdLine: number[]; sigLine: number[]; hist: number[] } {
  const ema12 = ema(closes, 12)
  const ema26 = ema(closes, 26)
  const macdLine = closes.map((_, i) =>
    isNaN(ema12[i]) || isNaN(ema26[i]) ? NaN : ema12[i] - ema26[i]
  )
  const validMacd = macdLine.map(v => (isNaN(v) ? 0 : v))
  const sigLine = ema(validMacd, 9)
  const hist = macdLine.map((m, i) =>
    isNaN(m) || isNaN(sigLine[i]) ? NaN : m - sigLine[i]
  )
  return { macdLine, sigLine, hist }
}

function computeATR(raw: { high: number; low: number; close: number }[], period = 14): number[] {
  const trs = raw.map((k, i) => {
    if (i === 0) return k.high - k.low
    const pc = raw[i - 1].close
    return Math.max(k.high - k.low, Math.abs(k.high - pc), Math.abs(k.low - pc))
  })
  const out = new Array(raw.length).fill(NaN)
  let atr = trs.slice(0, period).reduce((a, b) => a + b, 0) / period
  out[period - 1] = atr
  for (let i = period; i < trs.length; i++) {
    atr = (atr * (period - 1) + trs[i]) / period
    out[i] = atr
  }
  return out
}

function computeBB(closes: number[], period = 20): { upper: number[]; lower: number[]; mid: number[] } {
  const upper = new Array(closes.length).fill(NaN)
  const lower = new Array(closes.length).fill(NaN)
  const mid = new Array(closes.length).fill(NaN)
  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1)
    const m = slice.reduce((a, b) => a + b, 0) / period
    const std = Math.sqrt(slice.reduce((a, b) => a + (b - m) ** 2, 0) / period)
    mid[i] = m; upper[i] = m + 2 * std; lower[i] = m - 2 * std
  }
  return { upper, lower, mid }
}

// ── Main handler ─────────────────────────────────────────────────────────────

export async function GET(
  _req: Request,
  { params }: { params: { symbol: string } }
) {
  const symbol = params.symbol.toUpperCase()

  let rawKlines: { time: number; open: number; high: number; low: number; close: number; volume: number }[] = []
  let ticker24h: { lastPrice: number; priceChangePercent: number; quoteVolume: number } | null = null

  const redis = createRedis()
  try {
    // ── 1. Parallel: Redis kline cache + bookTicker + all signal data ──
    const [cachedKlines, tickerRaw, featRaw, sigRaw, verdictRaw, verdictsRaw, btRaw, shadowRaw, contextRaw] =
      await Promise.all([
        redis.get(`klines:1h:${symbol}`),
        redis.get(`binance:ticker:${symbol.toLowerCase()}`),
        redis.get(`features:latest:${symbol}`),
        redis.get(`signal:latest:${symbol}`),
        redis.get(`agents:verdict:${symbol}`),
        redis.get(`agents:verdicts:${symbol}`),
        redis.get('backtest:results'),
        redis.get('shadow:leaderboard'),
        redis.get(`context:latest:${symbol}`),
      ])

    // ── 2. Parse klines (Redis cache → Binance REST fallback) ──
    if (cachedKlines) {
      rawKlines = JSON.parse(cachedKlines)
    } else {
      try {
        const kRes = await fetch(
          `https://fapi.binance.com/fapi/v1/klines?symbol=${symbol}&interval=1h&limit=200`,
          { signal: AbortSignal.timeout(5000) }
        )
        if (kRes.ok) {
          const raw: string[][] = await kRes.json()
          rawKlines = raw.map(k => ({
            time: Number(k[0]), open: parseFloat(k[1]), high: parseFloat(k[2]),
            low: parseFloat(k[3]), close: parseFloat(k[4]), volume: parseFloat(k[5]),
          }))
        }
      } catch { /* network unavailable */ }
    }

    // ── 3. Ticker: Redis bookTicker (real-time bid/ask) → Binance REST fallback ──
    if (tickerRaw) {
      try {
        const d = (JSON.parse(tickerRaw) as any).data ?? JSON.parse(tickerRaw)
        const bid = parseFloat(d.b ?? 0)
        const ask = parseFloat(d.a ?? bid)
        const mid = bid > 0 && ask > 0 ? (bid + ask) / 2 : bid || ask
        if (mid > 0) ticker24h = { lastPrice: mid, priceChangePercent: 0, quoteVolume: 0 }
      } catch { /* ignore */ }
    }
    if (!ticker24h) {
      try {
        const tRes = await fetch(
          `https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=${symbol}`,
          { signal: AbortSignal.timeout(4000) }
        )
        if (tRes.ok) {
          const t = await tRes.json()
          ticker24h = {
            lastPrice: parseFloat(t.lastPrice),
            priceChangePercent: parseFloat(t.priceChangePercent),
            quoteVolume: parseFloat(t.quoteVolume),
          }
        }
      } catch { /* ignore */ }
    }

    // ── 4. Compute technical indicators ──
    const closes = rawKlines.map(k => k.close)
    const rsiArr = computeRSI(closes)
    const { macdLine, sigLine, hist: macdHist } = computeMACD(closes)
    const atrArr = computeATR(rawKlines)
    const { upper: bbUp, lower: bbLow, mid: bbMid } = computeBB(closes)

    const enrichedKlines = rawKlines.map((k, i) => ({
      ...k,
      timeStr: new Date(k.time).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' }),
      rsi: rsiArr[i] !== undefined ? +(rsiArr[i]?.toFixed(2) ?? NaN) : NaN,
      macd: macdLine[i] !== undefined ? +(macdLine[i]?.toFixed(4) ?? NaN) : NaN,
      macdSig: sigLine[i] !== undefined ? +(sigLine[i]?.toFixed(4) ?? NaN) : NaN,
      macdHist: macdHist[i] !== undefined ? +(macdHist[i]?.toFixed(4) ?? NaN) : NaN,
      atr: atrArr[i] !== undefined ? +(atrArr[i]?.toFixed(4) ?? NaN) : NaN,
      bbUp: bbUp[i] !== undefined ? +(bbUp[i]?.toFixed(4) ?? NaN) : NaN,
      bbLow: bbLow[i] !== undefined ? +(bbLow[i]?.toFixed(4) ?? NaN) : NaN,
      bbMid: bbMid[i] !== undefined ? +(bbMid[i]?.toFixed(4) ?? NaN) : NaN,
    }))

    // ── 5. Parse Redis data ──
    const features = featRaw ? JSON.parse(featRaw) : null
    const signal = sigRaw ? JSON.parse(sigRaw) : null
    const verdict = verdictRaw ? JSON.parse(verdictRaw) : null
    const votes: { agent: string; signal: string; confidence: number; reasoning: string }[] = verdictsRaw
      ? JSON.parse(verdictsRaw)
      : []
    const context = contextRaw ? JSON.parse(contextRaw) : null

    // Per-symbol backtest stats
    let backtestStats: Record<string, unknown> | null = null
    if (btRaw) {
      const bt = JSON.parse(btRaw)
      if (bt.results?.[symbol]) backtestStats = bt.results[symbol]
    }

    // Latest ATR for SL/TP levels
    const latestATR = atrArr[atrArr.length - 1] ?? (features?.atr ?? 0)
    const latestClose = rawKlines[rawKlines.length - 1]?.close ?? ticker24h?.lastPrice ?? 0
    const signalDir = signal?.direction ?? 'flat'

    let slLevel: number | null = null
    let tpLevel: number | null = null
    if (latestClose && latestATR && signalDir !== 'flat') {
      slLevel = signalDir === 'long'
        ? +(latestClose - latestATR * 2.0).toFixed(4)
        : +(latestClose + latestATR * 2.0).toFixed(4)
      tpLevel = signalDir === 'long'
        ? +(latestClose + latestATR * 3.5).toFixed(4)
        : +(latestClose - latestATR * 3.5).toFixed(4)
    }

    // Leverage recommendation
    const atrPct = latestClose > 0 ? latestATR / latestClose : 0
    const crisisLevel = signal?.crisis_level ?? context?.crisis_level ?? 0
    const baseLev =
      atrPct < 0.005 ? 10 :
      atrPct < 0.010 ? 7 :
      atrPct < 0.015 ? 5 :
      atrPct < 0.020 ? 3 : 2
    const crisisMult = [1.0, 0.75, 0.5, 0.25, 0.0][Math.min(crisisLevel, 4)]
    const recommendedLeverage = Math.max(1, Math.round(baseLev * crisisMult))

    const shadowList: { shadow_id: string; sharpe: number; win_rate: number; trades: number; return: number }[] =
      shadowRaw ? JSON.parse(shadowRaw) : []

    return NextResponse.json({
      symbol,
      klines: enrichedKlines,
      ticker24h,
      features,
      signal,
      verdict,
      votes,
      context,
      backtestStats,
      shadowLeaderboard: shadowList,
      levels: { sl: slLevel, tp: tpLevel, currentPrice: latestClose, atr: latestATR, atrPct },
      leverageRec: {
        recommended: recommendedLeverage,
        baseLev,
        crisisMult,
        crisisLevel,
        atrPct: +(atrPct * 100).toFixed(2),
        kellyFraction: signal?.kelly_fraction ?? 0,
      },
    })
  } finally {
    await redis.quit()
  }
}
