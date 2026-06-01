import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import Anthropic from '@anthropic-ai/sdk'
import { createRedis } from '../../_redis'
import { randomUUID } from 'crypto'

const REDIS_KEY = 'training:docs'

interface TrainingDoc {
  id: string
  title: string
  content: string
  source: 'pdf' | 'text'
  filename?: string
  created_at: number
}

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'ANTHROPIC_API_KEY tanımlı değil' }, { status: 500 })
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
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    return NextResponse.json({ error: 'Sadece PDF dosyaları kabul edilir' }, { status: 400 })
  }
  if (file.size > 20 * 1024 * 1024) {
    return NextResponse.json({ error: 'PDF boyutu 20 MB\'ı geçemez' }, { status: 400 })
  }

  // Convert to base64
  const arrayBuffer = await file.arrayBuffer()
  const base64 = Buffer.from(arrayBuffer).toString('base64')

  // Ask Claude to extract everything: text, charts, tables
  const client = new Anthropic({ apiKey })
  let extractedContent: string
  try {
    // document type is a beta feature — cast content to avoid TS overload mismatch
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const msgContent: any[] = [
      {
        type: 'document',
        source: { type: 'base64', media_type: 'application/pdf', data: base64 },
      },
      {
        type: 'text',
        text: `You are extracting content from a trading/financial analysis document for use as operator instructions in an automated crypto futures trading system.

Extract and describe EVERYTHING in the document:

1. ALL text content verbatim — strategies, rules, conditions, observations
2. EVERY chart or graph — describe: timeframe, indicators shown, key price levels, support/resistance, trend direction, patterns (head & shoulders, triangles, etc.), signals visible, what the author concludes from the chart
3. ALL tables — reproduce data and meaning
4. Specific numbers: entry/exit prices, percentage levels, stop-loss values, take-profit targets, indicator thresholds
5. Author's conclusions and trading recommendations

Write in clear English. Be thorough and specific — a trading AI will use this to decide when to buy and sell.`,
      },
    ]
    const message = await client.messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 4096,
      messages: [{ role: 'user', content: msgContent }],
    })
    extractedContent =
      message.content[0].type === 'text' ? message.content[0].text : '[Analiz alınamadı]'
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: `Claude analiz hatası: ${msg}` }, { status: 502 })
  }

  // Store in Redis
  const redis = createRedis()
  try {
    const raw = await redis.get(REDIS_KEY)
    const docs: TrainingDoc[] = raw ? JSON.parse(raw) : []
    const newDoc: TrainingDoc = {
      id: randomUUID(),
      title,
      content: extractedContent,
      source: 'pdf',
      filename: file.name,
      created_at: Date.now() / 1000,
    }
    docs.unshift(newDoc)
    await redis.set(REDIS_KEY, JSON.stringify(docs))
    return NextResponse.json({
      ok: true,
      id: newDoc.id,
      preview: extractedContent.slice(0, 600),
    })
  } finally {
    redis.disconnect()
  }
}
