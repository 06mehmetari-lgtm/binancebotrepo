import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'
import { randomUUID } from 'crypto'

export async function POST(req: NextRequest) {
  let formData: FormData
  try {
    formData = await req.formData()
  } catch {
    return NextResponse.json({ error: 'Form verisi okunamadı' }, { status: 400 })
  }

  const file = formData.get('pdf') as File | null
  const rawTitle = formData.get('title') as string | null
  const title = rawTitle?.trim() || file?.name?.replace(/\.pdf$/i, '') || 'PDF Döküman'

  if (!file) return NextResponse.json({ error: 'PDF dosyası gerekli' }, { status: 400 })
  if (!file.name.toLowerCase().endsWith('.pdf'))
    return NextResponse.json({ error: 'Sadece PDF dosyaları kabul edilir' }, { status: 400 })
  if (file.size > 20 * 1024 * 1024)
    return NextResponse.json({ error: "PDF boyutu 20 MB'ı geçemez" }, { status: 400 })

  const arrayBuffer = await file.arrayBuffer()
  const buffer = Buffer.from(arrayBuffer)

  // Extract text immediately — no API call
  let rawText = ''
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const pdfParse = require('pdf-parse')
    const data = await pdfParse(buffer)
    rawText = data.text ?? ''
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json({ error: `PDF metin çıkarma hatası: ${msg}` }, { status: 422 })
  }

  if (!rawText.trim())
    return NextResponse.json(
      { error: 'PDF metin içeriği bulunamadı (taranmış görsel PDF olabilir)' },
      { status: 422 },
    )

  const id = randomUUID()
  const item = {
    id,
    title,
    filename: file.name,
    raw_text: rawText,
    created_at: Date.now() / 1000,
  }

  const redis = createRedis()
  try {
    // Add to queue (RPUSH = append to tail, agent processes from head)
    await redis.rpush('training:queue', JSON.stringify(item))
    // Set initial status
    await redis.set(
      `training:queue:status:${id}`,
      JSON.stringify({ status: 'pending', created_at: item.created_at }),
      'EX',
      86400 * 7,
    )
    return NextResponse.json({ ok: true, queued: true, id })
  } finally {
    redis.disconnect()
  }
}
