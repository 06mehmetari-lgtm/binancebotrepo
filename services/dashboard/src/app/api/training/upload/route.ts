import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../../_redis'
import { randomUUID } from 'crypto'

const MAX_SIZE = 50 * 1024 * 1024  // 50 MB (ZIP içinde birden fazla PDF olabilir)

async function extractPdfText(buffer: Buffer): Promise<string> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const pdfParse = require('pdf-parse')
  const data = await pdfParse(buffer)
  return data.text ?? ''
}

async function queuePdf(
  redis: ReturnType<typeof createRedis>,
  filename: string,
  title: string,
  buffer: Buffer,
): Promise<{ id: string; error?: string }> {
  let rawText = ''
  try {
    rawText = await extractPdfText(buffer)
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return { id: '', error: `PDF metin çıkarma hatası (${filename}): ${msg}` }
  }
  if (!rawText.trim()) {
    return { id: '', error: `${filename}: metin bulunamadı (taranmış görsel PDF)` }
  }
  const id = randomUUID()
  const item = {
    id,
    title,
    filename,
    raw_text: rawText,
    created_at: Date.now() / 1000,
  }
  await redis.rpush('training:queue', JSON.stringify(item))
  await redis.set(
    `training:queue:status:${id}`,
    JSON.stringify({ status: 'pending', created_at: item.created_at }),
    'EX', 86400 * 7,
  )
  return { id }
}

export async function POST(req: NextRequest) {
  let formData: FormData
  try {
    formData = await req.formData()
  } catch {
    return NextResponse.json({ error: 'Form verisi okunamadı' }, { status: 400 })
  }

  const file = formData.get('pdf') as File | null
  const rawTitle = (formData.get('title') as string | null)?.trim() || ''

  if (!file) return NextResponse.json({ error: 'Dosya gerekli' }, { status: 400 })
  if (file.size > MAX_SIZE)
    return NextResponse.json({ error: `Dosya boyutu ${MAX_SIZE / 1024 / 1024} MB'ı geçemez` }, { status: 400 })

  const name = file.name.toLowerCase()
  const arrayBuffer = await file.arrayBuffer()
  const buffer = Buffer.from(arrayBuffer)

  const redis = createRedis()
  try {
    // ── Single PDF ────────────────────────────────────────────────────────────
    if (name.endsWith('.pdf')) {
      const title = rawTitle || file.name.replace(/\.pdf$/i, '')
      const result = await queuePdf(redis, file.name, title, buffer)
      if (result.error) return NextResponse.json({ error: result.error }, { status: 422 })
      return NextResponse.json({ ok: true, queued: true, id: result.id, count: 1 })
    }

    // ── ZIP archive — extract all PDFs ────────────────────────────────────────
    if (name.endsWith('.zip')) {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const JSZip = require('jszip')
      let zip: ReturnType<typeof JSZip>
      try {
        zip = await JSZip.loadAsync(buffer)
      } catch {
        return NextResponse.json({ error: 'ZIP dosyası okunamadı veya bozuk' }, { status: 422 })
      }

      const pdfFiles = Object.entries(zip.files as Record<string, { name: string; dir: boolean; async: (type: string) => Promise<Buffer> }>)
        .filter(([, f]) => !f.dir && f.name.toLowerCase().endsWith('.pdf'))

      if (pdfFiles.length === 0)
        return NextResponse.json({ error: 'ZIP içinde PDF bulunamadı' }, { status: 422 })

      const ids: string[] = []
      const errors: string[] = []

      for (const [, zipFile] of pdfFiles) {
        const pdfBuf = Buffer.from(await zipFile.async('arraybuffer'))
        const pdfName = zipFile.name.split('/').pop() ?? zipFile.name
        const title = pdfName.replace(/\.pdf$/i, '')
        const result = await queuePdf(redis, pdfName, title, pdfBuf)
        if (result.error) errors.push(result.error)
        else ids.push(result.id)
      }

      return NextResponse.json({
        ok: ids.length > 0,
        queued: ids.length > 0,
        count: ids.length,
        ids,
        errors: errors.length > 0 ? errors : undefined,
        message: `${ids.length}/${pdfFiles.length} PDF kuyruğa eklendi`,
      })
    }

    return NextResponse.json(
      { error: 'Sadece .pdf veya .zip dosyaları kabul edilir (RAR için önce ZIP\'e çevirin)' },
      { status: 400 },
    )
  } finally {
    redis.disconnect()
  }
}
