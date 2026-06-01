import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

const GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'
const GROQ_MODEL = 'llama-3.3-70b-versatile'

interface TrainingDoc {
  id: string
  title: string
  content: string
  filename?: string
}

export async function POST(req: NextRequest) {
  const apiKey = process.env.GROQ_API_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'GROQ_API_KEY tanımlı değil' }, { status: 500 })
  }

  const body = await req.json()
  const message = (body.message ?? '').trim()
  if (!message) {
    return NextResponse.json({ error: 'Mesaj boş olamaz' }, { status: 400 })
  }

  // Load learned documents from Redis
  const redis = createRedis()
  let docs: TrainingDoc[] = []
  try {
    const raw = await redis.get('training:docs')
    if (raw) docs = JSON.parse(raw)
  } finally {
    redis.disconnect()
  }

  if (docs.length === 0) {
    return NextResponse.json({
      reply: 'Henüz öğrenilmiş döküman yok. Lütfen önce /training sayfasından PDF yükleyin.',
      sources: [],
    })
  }

  // Build context from docs (max ~10000 chars total)
  let contextBlock = ''
  const usedTitles: string[] = []
  let charCount = 0
  for (const doc of docs) {
    const chunk = `[${doc.title}]\n${doc.content}\n`
    if (charCount + chunk.length > 10000) break
    contextBlock += chunk + '---\n'
    usedTitles.push(doc.title)
    charCount += chunk.length
  }

  const systemPrompt = `You are an expert trading analyst AI assistant. You have been trained on the following trading analysis documents provided by the operator:

${contextBlock}

Rules:
- Answer ONLY based on the documents above
- If the answer is not in the documents, say clearly: "Bu dökümanlarımda bu bilgi yok."
- Be specific: cite price levels, indicators, rules from the documents
- Answer in the same language the user writes in (Turkish or English)
- Keep answers concise but complete`

  const res = await fetch(GROQ_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: GROQ_MODEL,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: message },
      ],
      temperature: 0.2,
      max_tokens: 1024,
    }),
  })

  if (!res.ok) {
    const errText = await res.text()
    return NextResponse.json({ error: `Groq hatası: ${res.status} — ${errText.slice(0, 120)}` }, { status: 502 })
  }

  const data = await res.json()
  const reply = data.choices?.[0]?.message?.content ?? 'Cevap alınamadı.'

  return NextResponse.json({ reply, sources: usedTitles })
}
