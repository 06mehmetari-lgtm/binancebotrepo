import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'
import { randomUUID } from 'crypto'

const REDIS_KEY = 'training:docs'
const GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'
const GROQ_MODEL = 'llama-3.1-70b-versatile'

interface TrainingDoc {
  id: string
  title: string
  content: string
  source: 'pdf' | 'text'
  filename?: string
  created_at: number
}

async function extractPdfText(buffer: Buffer): Promise<string> {
  // Dynamically import pdf-parse to avoid SSR issues
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const pdfParse = require('pdf-parse')
  const data = await pdfParse(buffer)
  return data.text ?? ''
}

async function groqAnalyze(apiKey: string, rawText: string, filename: string): Promise<string> {
  const truncated = rawText.slice(0, 12000) // Groq context limit safety
  const prompt = `You are analyzing raw text extracted from a trading/financial PDF document ("${filename}") for use as operator instructions in an automated crypto futures trading system.

RAW EXTRACTED TEXT:
---
${truncated}
---

Based on this text, produce a comprehensive structured summary that includes:

1. **Trading Rules & Conditions** — exact entry/exit rules, when to buy/sell/stay flat
2. **Key Price Levels** — support, resistance, targets, stop-loss values mentioned
3. **Indicators & Signals** — RSI levels, MACD conditions, moving averages, any thresholds cited
4. **Chart Analysis** (from text labels, captions, axis values near charts if present)
5. **Risk Parameters** — position sizing, max loss, leverage guidance
6. **Market Conditions** — regimes, trends, timeframes the strategy applies to
7. **Author's Conclusions** — final recommendations

Write clearly in English. Be specific with numbers. A trading AI will use this to decide when to buy and sell.`

  const res = await fetch(GROQ_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: GROQ_MODEL,
      messages: [{ role: 'user', content: prompt }],
      temperature: 0.1,
      max_tokens: 4096,
    }),
  })

  if (!res.ok) {
    const body = await res.text()
    throw new Error(`Groq API ${res.status}: ${body.slice(0, 200)}`)
  }

  const data = await res.json()
  return data.choices?.[0]?.message?.content ?? '[Analiz alınamadı]'
}

export async function POST(req: NextRequest) {
  const apiKey = process.env.GROQ_API_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'GROQ_API_KEY tanımlı değil' }, { status: 500 })
  }

  let formData: FormData
  try {
    formData = await req.formData()
  } catch {
    return NextResponse.json({ error: 'Form verisi okunamadı' }, { status: 400 })
  }

  const file = formData.get('pdf') as File | null
  const rawTitle = formData.get('title') as string | null
  const title = rawTitle?.trim() || file?.name?.replace(/\.pdf$/i, '') || 'PDF Döküman'

  if (!file) {
    return NextResponse.json({ error: 'PDF dosyası gerekli' }, { status: 400 })
  }
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    return NextResponse.json({ error: 'Sadece PDF dosyaları kabul edilir' }, { status: 400 })
  }
  if (file.size > 20 * 1024 * 1024) {
    return NextResponse.json({ error: "PDF boyutu 20 MB'ı geçemez" }, { status: 400 })
  }

  // Convert to Buffer
  const arrayBuffer = await file.arrayBuffer()
  const buffer = Buffer.from(arrayBuffer)

  // Extract text from PDF
  let rawText: string
  try {
    rawText = await extractPdfText(buffer)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: `PDF metin çıkarma hatası: ${msg}` }, { status: 422 })
  }

  if (!rawText.trim()) {
    return NextResponse.json(
      { error: 'PDF metin içeriği bulunamadı (taranmış görsel PDF olabilir)' },
      { status: 422 },
    )
  }

  // Send to Groq for analysis
  let analysedContent: string
  try {
    analysedContent = await groqAnalyze(apiKey, rawText, file.name)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: `Groq analiz hatası: ${msg}` }, { status: 502 })
  }

  // Store in Redis
  const redis = createRedis()
  try {
    const existing = await redis.get(REDIS_KEY)
    const docs: TrainingDoc[] = existing ? JSON.parse(existing) : []
    const newDoc: TrainingDoc = {
      id: randomUUID(),
      title,
      content: analysedContent,
      source: 'pdf',
      filename: file.name,
      created_at: Date.now() / 1000,
    }
    docs.unshift(newDoc)
    await redis.set(REDIS_KEY, JSON.stringify(docs))
    return NextResponse.json({ ok: true, id: newDoc.id, preview: analysedContent.slice(0, 600) })
  } finally {
    redis.disconnect()
  }
}
