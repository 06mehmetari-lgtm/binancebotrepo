import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'
import { randomUUID } from 'crypto'

const REDIS_KEY = 'training:docs'

interface TrainingDoc {
  id: string
  title: string
  content: string
  created_at: number
}

async function loadDocs(redis: ReturnType<typeof createRedis>): Promise<TrainingDoc[]> {
  const raw = await redis.get(REDIS_KEY)
  if (!raw) return []
  try { return JSON.parse(raw) } catch { return [] }
}

async function saveDocs(redis: ReturnType<typeof createRedis>, docs: TrainingDoc[]) {
  await redis.set(REDIS_KEY, JSON.stringify(docs))
}

export async function GET() {
  const redis = createRedis()
  try {
    const docs = await loadDocs(redis)
    // Return full content for agent use, trimmed preview for UI
    const preview = docs.map(d => ({
      ...d,
      preview: d.content.slice(0, 300) + (d.content.length > 300 ? '…' : ''),
    }))
    return NextResponse.json(preview)
  } finally {
    redis.disconnect()
  }
}

export async function POST(req: NextRequest) {
  const redis = createRedis()
  try {
    const body = await req.json()
    const title = (body.title ?? '').trim()
    const content = (body.content ?? '').trim()
    if (!title || !content) {
      return NextResponse.json({ error: 'title ve content zorunlu' }, { status: 400 })
    }
    const docs = await loadDocs(redis)
    const newDoc: TrainingDoc = {
      id: randomUUID(),
      title,
      content,
      created_at: Date.now() / 1000,
    }
    docs.unshift(newDoc) // newest first
    await saveDocs(redis, docs)
    return NextResponse.json({ ok: true, id: newDoc.id })
  } finally {
    redis.disconnect()
  }
}

export async function DELETE(req: NextRequest) {
  const redis = createRedis()
  try {
    const id = new URL(req.url).searchParams.get('id')
    if (!id) return NextResponse.json({ error: 'id gerekli' }, { status: 400 })
    const docs = await loadDocs(redis)
    const filtered = docs.filter(d => d.id !== id)
    await saveDocs(redis, filtered)
    return NextResponse.json({ ok: true })
  } finally {
    redis.disconnect()
  }
}
