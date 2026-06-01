import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const COIN_MAP: Record<string, string> = {
  BTC: 'BTCUSDT', BITCOIN: 'BTCUSDT',
  ETH: 'ETHUSDT', ETHEREUM: 'ETHUSDT', ETHER: 'ETHUSDT',
  SOL: 'SOLUSDT', SOLANA: 'SOLUSDT',
  BNB: 'BNBUSDT',
  XRP: 'XRPUSDT', RIPPLE: 'XRPUSDT',
  ADA: 'ADAUSDT', CARDANO: 'ADAUSDT',
  DOGE: 'DOGEUSDT', DOGECOIN: 'DOGEUSDT',
  AVAX: 'AVAXUSDT', AVALANCHE: 'AVAXUSDT',
  DOT: 'DOTUSDT', POLKADOT: 'DOTUSDT',
  LINK: 'LINKUSDT', CHAINLINK: 'LINKUSDT',
  MATIC: 'MATICUSDT', POLYGON: 'MATICUSDT',
  POL: 'POLUSDT',
  NEAR: 'NEARUSDT',
  ATOM: 'ATOMUSDT', COSMOS: 'ATOMUSDT',
  UNI: 'UNIUSDT', UNISWAP: 'UNIUSDT',
  LTC: 'LTCUSDT', LITECOIN: 'LTCUSDT',
  APT: 'APTUSDT', APTOS: 'APTUSDT',
  ARB: 'ARBUSDT', ARBITRUM: 'ARBUSDT',
  OP: 'OPUSDT', OPTIMISM: 'OPUSDT',
  SUI: 'SUIUSDT',
  TRX: 'TRXUSDT', TRON: 'TRXUSDT',
  TON: 'TONUSDT',
  PEPE: '1000PEPEUSDT',
  SHIB: '1000SHIBUSDT',
  BONK: '1000BONKUSDT',
  JUP: 'JUPUSDT', JUPITER: 'JUPUSDT',
  TAO: 'TAOUSDT',
  WIF: 'WIFUSDT',
  HYPE: 'HYPEUSDT',
  VIRTUAL: 'VIRTUALUSDT',
  RENDER: 'RENDERUSDT',
  INJ: 'INJUSDT',
  SEI: 'SEIUSDT',
  GRASS: 'GRASSUSDT',
  SUI: 'SUIUSDT',
  HBAR: 'HBARUSDT',
}

const AGENT_TR: Record<string, string> = {
  bull_agent: 'Boğa Ajanı',
  bear_agent: 'Ayı Ajanı',
  neutral_agent: 'Tarafsız Ajan',
  technical_agent: 'Teknik Ajan',
  news_agent: 'Haber Ajanı',
  macro_agent: 'Makro Ajan',
  on_chain_agent: 'On-Chain Ajan',
  risk_agent: 'Risk Ajanı',
  evolution_agent: 'Evrim Ajanı',
  debate_agent: 'Tartışma Ajanı',
}

function extractSymbol(q: string): string | null {
  const upper = q.toUpperCase().trim()

  // Direct USDT pair
  const usdtMatch = upper.match(/\b([A-Z0-9]{1,20}USDT)\b/)
  if (usdtMatch) return usdtMatch[1]

  // Word-by-word match in coin map
  const words = upper.split(/[\s,\.;!?]+/)
  for (const w of words) {
    if (COIN_MAP[w]) return COIN_MAP[w]
  }

  // Raw ticker guess (2-10 uppercase letters)
  for (const w of words) {
    if (/^[A-Z]{2,10}$/.test(w)) return w + 'USDT'
  }

  return null
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const q = searchParams.get('q') ?? ''
  const symParam = (searchParams.get('symbol') ?? '').toUpperCase()

  const symbol = symParam || extractSymbol(q)
  if (!symbol) {
    return NextResponse.json({ error: 'no_symbol' })
  }

  const redis = createRedis()
  try {
    const [featRaw, sigRaw, verdictRaw, verdictsRaw, contextRaw, rlRaw, tickerRaw] =
      await Promise.all([
        redis.get(`features:latest:${symbol}`),
        redis.get(`signal:latest:${symbol}`),
        redis.get(`agents:verdict:${symbol}`),
        redis.get(`agents:verdicts:${symbol}`),
        redis.get(`context:latest:${symbol}`),
        redis.get(`rl:signal:${symbol}`),
        redis.get(`binance:ticker:${symbol.toLowerCase()}`),
      ])

    const features = featRaw ? JSON.parse(featRaw) : null
    const signal = sigRaw ? JSON.parse(sigRaw) : null
    const rawVerdict = verdictRaw ? JSON.parse(verdictRaw) : null
    const rawVotes: any[] = verdictsRaw ? JSON.parse(verdictsRaw) : []
    const context = contextRaw ? JSON.parse(contextRaw) : null
    const rlSignal = rlRaw ? JSON.parse(rlRaw) : null

    let price = 0
    if (tickerRaw) {
      try {
        const td = (JSON.parse(tickerRaw) as any)
        const d = td.data ?? td
        const bid = parseFloat(d.b ?? d.bid ?? 0)
        const ask = parseFloat(d.a ?? d.ask ?? bid)
        price = bid > 0 && ask > 0 ? (bid + ask) / 2 : bid || ask
      } catch {}
    }
    if (!price && features?.close) price = features.close

    const votes = rawVotes.map((v: any) => ({
      agent: v.agent ?? v.name ?? 'unknown',
      agent_tr: AGENT_TR[v.agent ?? v.name ?? ''] ?? (v.agent ?? v.name ?? 'Ajan'),
      vote: (v.signal ?? v.direction ?? 'flat').toLowerCase(),
      confidence: Number(v.confidence ?? 0),
      reasoning: ((v.reasoning ?? v.response ?? '') as string).slice(0, 400),
    }))

    let verdict = null
    if (rawVerdict) {
      let vd: any = rawVerdict
      if (typeof vd.verdict === 'string') {
        try { vd = { ...vd, ...JSON.parse(vd.verdict) } } catch {}
      }
      verdict = {
        direction: (vd.direction ?? 'flat').toLowerCase(),
        confidence: Number(vd.confidence ?? 0),
        reasoning: ((vd.consensus_reasoning ?? vd.reasoning ?? '') as string).slice(0, 600),
        dissent_risk: ((vd.dissent_risk ?? '') as string).slice(0, 250),
      }
    }

    const indicators = features ? {
      rsi: features.rsi_14 ?? null,
      macd_hist: features.macd_hist ?? null,
      bb_pct: features.bb_pct ?? null,
      atr_pct: features.atr_pct != null ? +(features.atr_pct * 100).toFixed(3) : null,
      funding_rate: features.funding_rate ?? null,
      oi_change: features.oi_change ?? null,
      fear_greed: features.fear_greed ?? null,
      vix: features.vix_level ?? null,
      ls_ratio: features.long_short_ratio ?? null,
      drift_status: features.drift_status ?? 'STABLE',
      ml_score: features.ml_score ?? null,
      volume_ratio: features.volume_ratio ?? null,
    } : null

    return NextResponse.json({
      symbol,
      price,
      has_features: !!features,
      features_age_s: features?.timestamp
        ? Math.round(Date.now() / 1000 - features.timestamp)
        : null,
      regime: context?.regime ?? features?.regime ?? null,
      crisis_level: context?.crisis_level ?? signal?.crisis_level ?? 0,
      indicators,
      votes,
      verdict,
      signal: signal ? {
        direction: (signal.direction ?? 'flat').toLowerCase(),
        confidence: Number(signal.confidence ?? 0),
        kelly: Number(signal.kelly_fraction ?? 0),
        stop_pct: signal.stop_pct ?? null,
        tp_pct: signal.tp_pct ?? null,
        risk_reward: signal.risk_reward ?? null,
        age_s: signal.timestamp
          ? Math.round(Date.now() / 1000 - signal.timestamp)
          : null,
      } : null,
      rl: rlSignal ? {
        direction: (rlSignal.direction ?? 'flat').toLowerCase(),
        confidence: Number(rlSignal.confidence ?? 0),
      } : null,
    })
  } finally {
    await redis.quit()
  }
}
