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

  // Always list ALL doc titles so the AI knows total count
  const allTitles = docs.map((d, i) => `${i + 1}. ${d.title}${d.filename ? ` (${d.filename})` : ''}`).join('\n')

  // Include full content up to 80k chars (~20k tokens, well within 128k context)
  let contentBlock = ''
  const includedTitles: string[] = []
  let charCount = 0
  for (const doc of docs) {
    const chunk = `[${doc.title}]\n${doc.content}\n---\n`
    if (charCount + chunk.length > 80000) break
    contentBlock += chunk
    includedTitles.push(doc.title)
    charCount += chunk.length
  }

  const skipped = docs.length - includedTitles.length

  const system = `You are an expert trading analyst AI assistant.

TOTAL DOCUMENTS IN YOUR KNOWLEDGE BASE: ${docs.length}
COMPLETE DOCUMENT LIST:
${allTitles}

${skipped > 0 ? `NOTE: ${skipped} document(s) could not fit in this context due to length. The documents above are the ones with full content available.\n` : ''}
FULL DOCUMENT CONTENTS:
${contentBlock}

Rules:
- You have ${docs.length} documents total as listed above — always report this correct count when asked
- Answer based on the document contents above
- If the answer is not in the documents, say: "Bu dökümanlarımda bu bilgi yok."
- Cite specific price levels, indicators, rules from the documents
- Answer in the same language the user writes in (Turkish or English)
- Keep answers concise but complete`

  try {
    const { content, provider } = await chatCompletion(message, { system, temperature: 0.2, maxTokens: 1024 })
    return NextResponse.json({ reply: content, sources: includedTitles, provider, totalDocs: docs.length })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: msg }, { status: 502 })
  }
}
