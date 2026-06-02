import { NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
import { createRedis } from '../_redis'

interface Lesson {
  ts?: number
  symbol?: string
  provider?: string
  pnl_pct?: number
  outcome?: string
  category?: string
  lesson?: string
  text?: string
}

interface Doc {
  id: string
  title: string
  filename?: string
  uploadedAt?: number
  size?: number
  pageCount?: number
}

export async function GET() {
  const redis = createRedis()
  try {
    const [
      trainedModel,
      lastTrainTs,
      knowledgeChars,
      lessonsRaw,
      docsRaw,
      patternRaw,
      perfRaw,
      statsRaw,
    ] = await Promise.all([
      redis.get('ollama:trained_model'),
      redis.get('ollama:last_train_ts'),
      redis.get('ollama:knowledge_chars'),
      redis.lrange('training:lessons', 0, 499),
      redis.get('training:docs'),
      redis.get('agent:learned_patterns'),
      redis.get('agents:performance_summary'),
      redis.get('signal_engine:stats'),
    ])

    // Parse lessons
    const lessons: Lesson[] = lessonsRaw
      .map(r => { try { return JSON.parse(r) } catch { return null } })
      .filter(Boolean)

    // Count by category
    const byCat: Record<string, number> = {}
    const byProvider: Record<string, number> = {}
    for (const l of lessons) {
      const cat = l.category ?? 'genel'
      byCat[cat] = (byCat[cat] ?? 0) + 1
      if (l.provider) {
        byProvider[l.provider] = (byProvider[l.provider] ?? 0) + 1
      }
    }

    // Recent lessons (last 10)
    const recentLessons = lessons.slice(0, 10).map(l => ({
      ts: Number(l.ts ?? 0),
      symbol: l.symbol ?? '—',
      provider: l.provider ?? '—',
      outcome: l.outcome ?? (Number(l.pnl_pct) > 0 ? 'WIN' : 'LOSS'),
      pnl_pct: Number(l.pnl_pct ?? 0),
      category: l.category ?? 'genel',
      lesson: (l.lesson ?? l.text ?? '').slice(0, 200),
    }))

    // Docs
    let docs: Doc[] = []
    try { if (docsRaw) docs = JSON.parse(docsRaw) } catch { /* ignore */ }

    // Patterns
    let patternCount = 0
    try {
      if (patternRaw) {
        const p = JSON.parse(patternRaw)
        patternCount = Object.keys(p).filter(k => !k.endsWith(':n')).length
      }
    } catch { /* ignore */ }

    // Agent accuracy
    let agentAccuracy: { name: string; accuracy: number; calls: number }[] = []
    try {
      if (perfRaw) {
        const perf = JSON.parse(perfRaw)
        agentAccuracy = Object.entries(perf).map(([name, s]: [string, unknown]) => {
          const stats = s as Record<string, number>
          return { name, accuracy: Number(stats.accuracy ?? 0), calls: Number(stats.calls ?? 0) }
        }).filter(a => a.calls > 0).sort((a, b) => b.accuracy - a.accuracy)
      }
    } catch { /* ignore */ }

    // System stats
    let totalTrades = 0, overallWinRate = 0
    try {
      if (statsRaw) {
        const s = JSON.parse(statsRaw)
        totalTrades = Number(s.total_trades ?? 0)
        overallWinRate = Number(s.overall_win_rate ?? 0)
      }
    } catch { /* ignore */ }

    const baseModel = process.env.OLLAMA_MODEL ?? 'llama3.1:8b'
    const activeModel = trainedModel ?? baseModel
    const isCustom = trainedModel != null && trainedModel !== baseModel

    return NextResponse.json({
      activeModel,
      isCustom,
      baseModel,
      lastTrainTs: lastTrainTs ? Number(lastTrainTs) : null,
      knowledgeChars: knowledgeChars ? Number(knowledgeChars) : 0,
      lessonsTotal: lessons.length,
      byCat,
      byProvider,
      recentLessons,
      docs: docs.map(d => ({
        id: d.id,
        title: d.title,
        filename: d.filename,
        uploadedAt: d.uploadedAt,
        size: d.size,
        pageCount: d.pageCount,
      })),
      patternCount,
      agentAccuracy,
      totalTrades,
      overallWinRate: Math.round(overallWinRate * 100),
    })
  } finally {
    redis.disconnect()
  }
}
