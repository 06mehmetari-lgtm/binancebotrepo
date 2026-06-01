import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { chatCompletion } from '../_llm'

interface TrainingDoc {
  id: string
  title: string
  content: string
  filename?: string
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const message = (body.message ?? '').trim()
  if (!message) {
    return NextResponse.json({ error: 'Mesaj boş olamaz' }, { status: 400 })
  }

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

  // Build context from docs (max ~10000 chars)
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

  const system = `You are an expert trading analyst AI assistant trained on the following documents:

${contextBlock}

Rules:
- Answer ONLY based on the documents above
- If the answer is not in the documents, say: "Bu dökümanlarımda bu bilgi yok."
- Cite specific price levels, indicators, rules from the documents
- Answer in the same language the user writes in (Turkish or English)
- Keep answers concise but complete`

  try {
    const { content, provider } = await chatCompletion(message, { system, temperature: 0.2, maxTokens: 1024 })
    return NextResponse.json({ reply: content, sources: usedTitles, provider })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 502 })
  }
}
