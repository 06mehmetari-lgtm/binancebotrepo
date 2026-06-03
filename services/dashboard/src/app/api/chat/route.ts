import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://ollama:11434'
const QDRANT_URL = process.env.QDRANT_URL || 'http://qdrant:6333'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

async function ragSearch(symbol: string, query: string, limit = 5) {
  try {
    const res = await fetch(`${QDRANT_URL}/collections/trade_memories/points/scroll`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 20, with_payload: true, with_vector: false }),
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) return []
    const data = (await res.json()) as {
      result?: { points?: { payload?: Record<string, unknown> }[] }
    }
    const points = data.result?.points ?? []
    const q = query.toLowerCase()
    return points
      .map(p => p.payload ?? {})
      .filter(p => {
        const sym = String(p.symbol ?? '')
        if (symbol && sym && sym !== symbol) return false
        const text = JSON.stringify(p).toLowerCase()
        return !q || text.includes(q) || sym.toLowerCase().includes(q)
      })
      .slice(0, limit)
  } catch {
    return []
  }
}

async function ollamaReply(prompt: string): Promise<string | null> {
  try {
    const res = await fetch(`${OLLAMA_URL}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: process.env.OLLAMA_MODEL ?? 'llama3.1:8b',
        prompt,
        stream: false,
        options: { temperature: 0.3, num_predict: 400 },
      }),
      signal: AbortSignal.timeout(60000),
    })
    if (!res.ok) return null
    const data = (await res.json()) as { response?: string }
    return data.response?.trim() ?? null
  } catch {
    return null
  }
}

export async function POST(req: Request) {
  const redis = createRedis()
  try {
    const body = (await req.json()) as {
      message?: string
      symbol?: string
      use_llm?: boolean
    }
    const message = (body.message ?? '').trim()
    const symbol = (body.symbol ?? 'BTCUSDT').toUpperCase()
    if (!message) {
      return NextResponse.json({ error: 'message required' }, { status: 400 })
    }

    const [profileRaw, signalRaw, verdictRaw, lessonsRaw, globalRaw] = await Promise.all([
      redis.get(`learn:profile:${symbol}`),
      redis.get(`signal:latest:${symbol}`),
      redis.get(`agents:verdict:${symbol}`),
      redis.lrange(`trade:lessons:${symbol}`, 0, 5),
      redis.get('learn:global:v1'),
    ])

    const profile = safeJson(profileRaw) as Record<string, unknown> | null
    const signal = safeJson(signalRaw) as Record<string, unknown> | null
    const verdict = safeJson(verdictRaw) as Record<string, unknown> | null
    const lessons = lessonsRaw.map(r => safeJson(r)).filter(Boolean)
    const globalLearn = safeJson(globalRaw)
    const memories = await ragSearch(symbol, message, 5)

    const contextBlock = [
      `Kullanıcı sorusu: ${message}`,
      `Sembol: ${symbol}`,
      profile
        ? `Öğrenme: stage=${profile.learning_stage} rejim=${profile.current_regime} giriş=${profile.best_entry_hint} kaçın=${profile.avoid_hint}`
        : 'Öğrenme profili yok',
      signal
        ? `Sinyal: ${signal.direction} conf=${signal.confidence} action=${signal.trade_action} valid=${signal.is_valid}`
        : 'Sinyal yok',
      verdict
        ? `AI verdict: ${verdict.direction} conf=${verdict.confidence}`
        : 'Verdict yok',
      lessons.length ? `Son dersler: ${lessons.map(l => (l as { text?: string }).text).join(' | ')}` : '',
      memories.length ? `RAG: ${memories.length} trade memory` : '',
    ]
      .filter(Boolean)
      .join('\n')

    let answer: string
    let provider = 'rules'

    if (body.use_llm !== false) {
      const llm = await ollamaReply(
        `Sen Prometheus kripto trading asistanısın. Türkçe, net, risk odaklı yanıt ver (max 8 cümle).\n${contextBlock}\n\nYanıt:`,
      )
      if (llm) {
        answer = llm
        provider = 'ollama'
      } else {
        provider = 'rules_fallback'
        answer = buildRuleAnswer(symbol, profile, signal, verdict, message)
      }
    } else {
      answer = buildRuleAnswer(symbol, profile, signal, verdict, message)
    }

    await redis.lpush(
      'chat:history:v1',
      JSON.stringify({
        ts: Date.now() / 1000,
        symbol,
        message,
        answer: answer.slice(0, 2000),
        provider,
      }),
    )
    await redis.ltrim('chat:history:v1', 0, 199)

    return NextResponse.json({
      symbol,
      answer,
      provider,
      context: { profile, signal, verdict, lessons_count: lessons.length, memories_count: memories.length },
      global: globalLearn,
    })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}

function buildRuleAnswer(
  symbol: string,
  profile: Record<string, unknown> | null,
  signal: Record<string, unknown> | null,
  verdict: Record<string, unknown> | null,
  message: string,
): string {
  const m = message.toLowerCase()
  if (m.includes('al') || m.includes('long') || m.includes('buy')) {
    const dir = signal?.direction ?? verdict?.direction ?? 'flat'
    const conf = Number(signal?.confidence ?? verdict?.confidence ?? 0)
    if (dir === 'long' && conf >= 0.6) {
      return `${symbol}: Sinyal LONG (%${Math.round(conf * 100)}). Paper modda Emir Merkezi veya sinyal döngüsü işler. ${profile?.best_entry_hint ?? ''}`
    }
    return `${symbol}: Şu an güçlü LONG yok (yön=${dir}, güven %${Math.round(conf * 100)}). Scanner SQS ve AI Analiz sayfasına bakın.`
  }
  if (m.includes('sat') || m.includes('kapat') || m.includes('close')) {
    return `${symbol}: FLAT/close sinyali veya Emir Merkezi → Kapat kullanın. Guard ~1s izler.`
  }
  return `${symbol} özeti: Sinyal ${signal?.direction ?? '—'} | AI ${verdict?.direction ?? '—'} %${Math.round(Number(verdict?.confidence ?? 0) * 100)} | Öğrenme ${profile?.learning_stage ?? 'L0'}. Kaçın: ${profile?.avoid_hint ?? '—'}`
}
