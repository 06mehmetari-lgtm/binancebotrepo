import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const OLLAMA_URL   = process.env.OLLAMA_URL   ?? 'http://ollama:11434'
const BASE_MODEL   = process.env.OLLAMA_MODEL ?? 'llama3.1:8b'
const TRAINED_MODEL = 'prometheus-trading'
const TIMEOUT_MS   = 90_000

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    p,
    new Promise<T>((_, rej) => setTimeout(() => rej(new Error(`timeout ${ms}ms`)), ms)),
  ])
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const message = (body.message ?? '').trim()
  const symbol  = (body.symbol ?? '').toUpperCase().trim()
  if (!message) return NextResponse.json({ error: 'Mesaj boş olamaz' }, { status: 400 })

  const redis = createRedis()
  let context = ''
  let activeModel = BASE_MODEL

  try {
    // Check which model to use
    const trainedModelKey = await redis.get('ollama:trained_model')
    if (trainedModelKey) activeModel = TRAINED_MODEL

    // Gather context
    const parts: string[] = []

    // Symbol-specific features
    if (symbol) {
      const [featRaw, lessonsRaw, aiHistRaw] = await Promise.all([
        redis.get(`features:latest:${symbol}`),
        redis.lrange('training:lessons', 0, 499),
        redis.lrange(`ai:analysis:history:${symbol}`, 0, 4),
      ])

      if (featRaw) {
        try {
          const f = JSON.parse(featRaw)
          parts.push(`=== ${symbol} GÜNCEL VERİLER ===
RSI-14: ${Number(f.rsi_14 ?? 0).toFixed(1)}
MACD Histogramı: ${Number(f.macd_hist ?? 0).toFixed(4)}
BB Pozisyon: ${Number(f.bb_position ?? 0).toFixed(2)}
ATR-14: ${Number(f.atr_14 ?? 0).toFixed(4)}
ADX-14: ${Number(f.adx_14 ?? 0).toFixed(1)}
Funding Rate: ${(Number(f.funding_rate ?? 0) * 100).toFixed(4)}%
OI Değişim 1s: ${(Number(f.oi_change_1h ?? 0) * 100).toFixed(2)}%
Hacim Oranı: ${Number(f.volume_ratio ?? 0).toFixed(2)}x
VIX: ${Number(f.vix_level ?? 0).toFixed(1)}
Fear&Greed: ${Number(f.fear_greed_norm ?? 0).toFixed(2)}`)
        } catch { /* ignore */ }
      }

      // Lessons for this symbol
      try {
        const symbolLessons = lessonsRaw
          .map(r => { try { return JSON.parse(r) } catch { return null } })
          .filter(l => l && l.symbol === symbol)
          .slice(0, 5)
        if (symbolLessons.length > 0) {
          parts.push(`=== ${symbol} GEÇMIŞ DERSLER ===`)
          symbolLessons.forEach(l => {
            const outcome = l.outcome ?? (Number(l.pnl_pct) > 0 ? 'WIN' : 'LOSS')
            parts.push(`[${outcome} ${Number(l.pnl_pct ?? 0).toFixed(2)}%] ${l.lesson ?? l.text ?? ''}`)
          })
        }
      } catch { /* ignore */ }

      // Previous AI analyses
      if (aiHistRaw && aiHistRaw.length > 0) {
        try {
          const hist = aiHistRaw.slice(0, 2).map(r => {
            const h = JSON.parse(r)
            return `${h.direction?.toUpperCase() ?? '?'} %${Math.round((h.confidence ?? 0) * 100)} — ${(h.summary ?? h.reasoning ?? '').slice(0, 100)}`
          })
          if (hist.length > 0) {
            parts.push(`=== ÖNCEKİ ANALİZLER ===\n${hist.join('\n')}`)
          }
        } catch { /* ignore */ }
      }
    }

    // General lessons (latest 20)
    const allLessonsRaw = await redis.lrange('training:lessons', 0, 19)
    try {
      const recent = allLessonsRaw
        .map(r => { try { return JSON.parse(r) } catch { return null } })
        .filter(l => l && l.lesson)
        .slice(0, 10)
      if (recent.length > 0) {
        parts.push('=== SON ÖĞRENILEN DERSLER ===')
        recent.forEach(l => parts.push(`• [${l.symbol ?? '?'}] ${l.lesson}`))
      }
    } catch { /* ignore */ }

    // Training docs
    const docsRaw = await redis.get('training:docs')
    if (docsRaw) {
      try {
        const docs: Array<{ title: string; content: string }> = JSON.parse(docsRaw)
        if (docs.length > 0) {
          let charBudget = 20000
          parts.push('=== EĞİTİM DOKÜMANLARI ===')
          for (const d of docs) {
            const chunk = `[${d.title}]\n${d.content}`
            if (charBudget <= 0) break
            parts.push(chunk.slice(0, charBudget))
            charBudget -= chunk.length
          }
        }
      } catch { /* ignore */ }
    }

    context = parts.join('\n\n')

  } finally {
    redis.disconnect()
  }

  const systemPrompt = `Sen Prometheus Trading AI'sın — Binance USDM Futures kripto uzmanı.
Aşağıdaki gerçek piyasa verilerini, geçmiş derslerini ve eğitim dökümanlarını kullanarak soruları yanıtla.

${context}

YANIT KURALLARI:
- Somut verilerden konuş (RSI değerleri, yüzde oranlar, spesifik kural ve desenleri belirt)
- Türkçe veya İngilizce yanıt ver (kullanıcının diline göre)
- Kısa ve net ol — maksimum 300 kelime
- Güvenilir değilsen "Bu konuda yeterli verim yok." de
- Eğer sinyal üretiyorsan JSON formatını kullan: {"signal":"long|short|flat","confidence":0.0-1.0,"reasoning":"kısa açıklama"}`

  try {
    const res = await withTimeout(
      fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: activeModel,
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: message },
          ],
          stream: false,
          options: { temperature: 0.15, num_predict: 512 },
        }),
      }),
      TIMEOUT_MS,
    )

    if (!res.ok) {
      // Fallback to base model if trained model fails
      if (activeModel !== BASE_MODEL) {
        const res2 = await withTimeout(
          fetch(`${OLLAMA_URL}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model: BASE_MODEL,
              messages: [
                { role: 'system', content: systemPrompt },
                { role: 'user', content: message },
              ],
              stream: false,
              options: { temperature: 0.15, num_predict: 512 },
            }),
          }),
          TIMEOUT_MS,
        )
        if (res2.ok) {
          const d2 = await res2.json()
          return NextResponse.json({ reply: d2.message?.content ?? '', model: BASE_MODEL, context: symbol || 'genel' })
        }
      }
      const txt = await res.text()
      return NextResponse.json({ error: `Ollama ${res.status}: ${txt.slice(0, 200)}` }, { status: 502 })
    }

    const data = await res.json()
    const reply = data.message?.content ?? ''
    return NextResponse.json({ reply, model: activeModel, context: symbol || 'genel' })

  } catch (err: unknown) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
