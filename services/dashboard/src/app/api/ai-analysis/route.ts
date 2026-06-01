import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { chatCompletion } from '../_llm'

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
  HBAR: 'HBARUSDT',
}

const AGENT_TR: Record<string, string> = {
  bull_agent:      'Boğa Ajanı',
  bear_agent:      'Ayı Ajanı',
  neutral_agent:   'Tarafsız Ajan',
  technical_agent: 'Teknik Ajan',
  news_agent:      'Haber Ajanı',
  macro_agent:     'Makro Ajan',
  on_chain_agent:  'On-Chain Ajan',
  risk_agent:      'Risk Ajanı',
  evolution_agent: 'Evrim Ajanı',
  debate_agent:    'Tartışma Ajanı',
}

function extractSymbol(q: string): string | null {
  const upper = q.toUpperCase().trim()
  const usdtMatch = upper.match(/\b([A-Z0-9]{1,20}USDT)\b/)
  if (usdtMatch) return usdtMatch[1]
  const words = upper.split(/[\s,\.;!?]+/)
  for (const w of words) {
    if (COIN_MAP[w]) return COIN_MAP[w]
  }
  for (const w of words) {
    if (/^[A-Z]{2,10}$/.test(w)) return w + 'USDT'
  }
  return null
}

interface DocInsights {
  score: number
  rating: string
  commentary: string
  matched_rules: string[]
  docs_used: number
  provider: string
}

async function buildDocInsights(
  symbol: string,
  price: number,
  features: Record<string, unknown> | null,
  signal: Record<string, unknown> | null,
  context: Record<string, unknown> | null,
  rawVerdict: Record<string, unknown> | null,
  trainingRaw: string,
): Promise<DocInsights | null> {
  try {
    const docs: { title: string; content: string }[] = JSON.parse(trainingRaw)
    if (!docs || docs.length === 0) return null

    const coin = symbol.replace('USDT', '').replace('1000', '')

    // Prioritise docs that mention this coin; fall back to all docs
    const relevant = docs.filter(d =>
      d.content?.toUpperCase().includes(coin) ||
      d.title?.toUpperCase().includes(coin)
    )
    const pool = relevant.length > 0 ? relevant : docs

    // Build concise doc block (max ~3000 chars)
    let docBlock = ''
    for (const d of pool.slice(0, 5)) {
      const chunk = `[${d.title}]\n${(d.content ?? '').slice(0, 800)}\n---\n`
      if (docBlock.length + chunk.length > 3500) break
      docBlock += chunk
    }

    const rsi     = features?.rsi_14 != null ? Number(features.rsi_14).toFixed(1) : 'N/A'
    const macd    = features?.macd_hist != null ? Number(features.macd_hist).toFixed(4) : 'N/A'
    const bbPct   = features?.bb_pct != null ? (Number(features.bb_pct) * 100).toFixed(0) + '%' : 'N/A'
    const atrPct  = features?.atr_pct != null ? (Number(features.atr_pct) * 100).toFixed(2) + '%' : 'N/A'
    const funding = features?.funding_rate != null ? (Number(features.funding_rate) * 100).toFixed(4) + '%' : 'N/A'
    const fg      = features?.fear_greed != null ? String(features.fear_greed) + '/100' : 'N/A'
    const vol     = features?.volume_ratio != null ? Number(features.volume_ratio).toFixed(2) + 'x' : 'N/A'
    const regime  = (context?.regime as string) ?? (features?.regime as string) ?? 'unknown'
    const conf    = signal?.confidence != null ? (Number(signal.confidence) * 100).toFixed(0) + '%' : 'N/A'
    const dir     = (signal?.direction as string) ?? 'flat'
    const consensus = rawVerdict?.consensus != null ? (Number(rawVerdict.consensus) * 100).toFixed(0) + '%' : 'N/A'
    const stopPct = signal?.stop_pct != null ? Math.abs(Number(signal.stop_pct)).toFixed(2) + '%' : 'N/A'
    const tpPct   = signal?.tp_pct   != null ? Math.abs(Number(signal.tp_pct)).toFixed(2)   + '%' : 'N/A'
    const rr      = signal?.risk_reward != null ? '1:' + Number(signal.risk_reward).toFixed(2) : 'N/A'

    const prompt = `You are analyzing a crypto futures trade opportunity for ${symbol} using operator training documents.

CURRENT MARKET DATA:
Symbol: ${symbol} | Price: $${price > 0 ? price.toFixed(4) : 'N/A'}
RSI(14): ${rsi} | MACD Histogram: ${macd} | Bollinger %B: ${bbPct}
ATR Volatility: ${atrPct} | Volume Ratio: ${vol} | Funding Rate: ${funding}
Fear & Greed: ${fg} | Market Regime: ${regime}
Signal Direction: ${dir.toUpperCase()} | Confidence: ${conf} | Agent Consensus: ${consensus}
Stop Loss: ${stopPct} | Take Profit: ${tpPct} | Risk/Reward: ${rr}

OPERATOR TRAINING DOCUMENTS:
${docBlock}

Based ONLY on what the training documents say, evaluate this coin right now.
Return ONLY valid JSON, no markdown, no extra text:
{"score":<0-100>,"rating":"<GÜÇLÜ AL|AL|BEKLE|SAT|GÜÇLÜ SAT>","commentary":"<2-3 Türkçe cümle — dokümanlara göre mevcut durumun değerlendirmesi>","matched_rules":["<dokümanlardan spesifik kural 1>","<kural 2>","<kural 3>"]}`

    const { content, provider } = await chatCompletion(prompt, { temperature: 0.1, maxTokens: 400 })
    const start = content.indexOf('{')
    const end   = content.lastIndexOf('}') + 1
    if (start < 0 || end <= start) return null

    const parsed = JSON.parse(content.slice(start, end))
    return {
      score:         Number(parsed.score ?? 50),
      rating:        String(parsed.rating ?? 'BEKLE'),
      commentary:    String(parsed.commentary ?? ''),
      matched_rules: Array.isArray(parsed.matched_rules) ? parsed.matched_rules.slice(0, 4) : [],
      docs_used:     pool.length,
      provider,
    }
  } catch {
    return null
  }
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const q        = searchParams.get('q') ?? ''
  const symParam = (searchParams.get('symbol') ?? '').toUpperCase()

  const symbol = symParam || extractSymbol(q)
  if (!symbol) return NextResponse.json({ error: 'no_symbol' })

  const redis = createRedis()
  try {
    const [featRaw, sigRaw, verdictRaw, verdictsRaw, contextRaw, rlRaw, tickerRaw, trainingRaw] =
      await Promise.all([
        redis.get(`features:latest:${symbol}`),
        redis.get(`signal:latest:${symbol}`),
        redis.get(`agents:verdict:${symbol}`),
        redis.get(`agents:verdicts:${symbol}`),
        redis.get(`context:latest:${symbol}`),
        redis.get(`rl:signal:${symbol}`),
        redis.get(`binance:ticker:${symbol.toLowerCase()}`),
        redis.get('training:docs'),
      ])

    const features   = featRaw     ? JSON.parse(featRaw)     : null
    const signal     = sigRaw      ? JSON.parse(sigRaw)      : null
    const rawVerdict = verdictRaw  ? JSON.parse(verdictRaw)  : null
    const rawVotes   = verdictsRaw ? JSON.parse(verdictsRaw) : []
    const context    = contextRaw  ? JSON.parse(contextRaw)  : null
    const rlSignal   = rlRaw       ? JSON.parse(rlRaw)       : null

    let price = 0
    if (tickerRaw) {
      try {
        const td = JSON.parse(tickerRaw) as Record<string, unknown>
        const d  = (td.data ?? td) as Record<string, unknown>
        const bid = parseFloat(d.b as string ?? d.bid as string ?? '0')
        const ask = parseFloat(d.a as string ?? d.ask as string ?? String(bid))
        price = bid > 0 && ask > 0 ? (bid + ask) / 2 : bid || ask
      } catch { /* ignore */ }
    }
    if (!price && features?.close) price = features.close as number

    const votes = (rawVotes as Record<string, unknown>[]).map(v => ({
      agent:    String(v.agent ?? v.name ?? 'unknown'),
      agent_tr: AGENT_TR[String(v.agent ?? v.name ?? '')] ?? String(v.agent ?? v.name ?? 'Ajan'),
      vote:     String(v.signal ?? v.direction ?? 'flat').toLowerCase(),
      confidence: Number(v.confidence ?? 0),
      reasoning:  String(v.reasoning ?? v.response ?? '').slice(0, 400),
    }))

    let verdict = null
    if (rawVerdict) {
      let vd = rawVerdict as Record<string, unknown>
      if (typeof vd.verdict === 'string') {
        try { vd = { ...vd, ...JSON.parse(vd.verdict as string) } } catch { /* ignore */ }
      }
      verdict = {
        direction:   String(vd.direction ?? 'flat').toLowerCase(),
        confidence:  Number(vd.confidence ?? 0),
        reasoning:   String(vd.consensus_reasoning ?? vd.reasoning ?? '').slice(0, 600),
        dissent_risk: String(vd.dissent_risk ?? '').slice(0, 250),
      }
    }

    const indicators = features ? {
      rsi:          features.rsi_14       ?? null,
      macd_hist:    features.macd_hist    ?? null,
      bb_pct:       features.bb_pct       ?? null,
      atr_pct:      features.atr_pct != null ? +(Number(features.atr_pct) * 100).toFixed(3) : null,
      funding_rate: features.funding_rate ?? null,
      oi_change:    features.oi_change    ?? null,
      fear_greed:   features.fear_greed   ?? null,
      vix:          features.vix_level    ?? null,
      ls_ratio:     features.long_short_ratio ?? null,
      drift_status: features.drift_status ?? 'STABLE',
      ml_score:     features.ml_score     ?? null,
      volume_ratio: features.volume_ratio ?? null,
    } : null

    // Doc-based insights (runs only when training docs available)
    let doc_insights: DocInsights | null = null
    if (trainingRaw && (features || signal)) {
      doc_insights = await buildDocInsights(
        symbol, price, features, signal, context, rawVerdict, trainingRaw,
      )
    }

    return NextResponse.json({
      symbol,
      price,
      has_features:    !!features,
      features_age_s:  features?.timestamp
        ? Math.round(Date.now() / 1000 - Number(features.timestamp))
        : null,
      regime:       context?.regime ?? features?.regime ?? null,
      crisis_level: context?.crisis_level ?? signal?.crisis_level ?? 0,
      indicators,
      votes,
      verdict,
      signal: signal ? {
        direction:   String(signal.direction ?? 'flat').toLowerCase(),
        confidence:  Number(signal.confidence ?? 0),
        kelly:       Number(signal.kelly_fraction ?? 0),
        stop_pct:    signal.stop_pct  ?? null,
        tp_pct:      signal.tp_pct    ?? null,
        risk_reward: signal.risk_reward ?? null,
        age_s:       signal.timestamp
          ? Math.round(Date.now() / 1000 - Number(signal.timestamp))
          : null,
      } : null,
      rl: rlSignal ? {
        direction:  String(rlSignal.direction ?? 'flat').toLowerCase(),
        confidence: Number(rlSignal.confidence ?? 0),
      } : null,
      doc_insights,
    })
  } finally {
    await redis.quit()
  }
}
