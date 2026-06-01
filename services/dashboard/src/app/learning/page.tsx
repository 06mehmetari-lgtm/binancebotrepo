'use client'
import { useState, useEffect, useCallback } from 'react'

interface Lesson {
  lesson: string
  symbol: string
  side: string
  pnl_pct: number
  outcome: 'WIN' | 'LOSS'
  close_reason: string
  confidence: number
  ts: number
}

function fmtPnl(p: number) {
  const sign = p >= 0 ? '+' : ''
  return `${sign}${(p * 100).toFixed(2)}%`
}

function fmtTs(ts: number) {
  return new Date(ts * 1000).toLocaleString('tr-TR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function LessonCard({ lesson }: { lesson: Lesson }) {
  const isWin = lesson.outcome === 'WIN'
  return (
    <div className={`border rounded-xl p-4 space-y-2 ${
      isWin
        ? 'border-green-700/40 bg-green-900/10'
        : 'border-red-700/40 bg-red-900/10'
    }`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-xs font-bold px-2 py-0.5 rounded ${
          isWin ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
        }`}>
          {isWin ? '▲ WIN' : '▼ LOSS'}
        </span>
        <span className="text-white font-semibold text-sm">{lesson.symbol}</span>
        <span className={`text-sm font-mono font-bold ${isWin ? 'text-green-400' : 'text-red-400'}`}>
          {fmtPnl(lesson.pnl_pct)}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded border ${
          lesson.side === 'long'
            ? 'border-blue-700/40 bg-blue-900/20 text-blue-400'
            : 'border-purple-700/40 bg-purple-900/20 text-purple-400'
        }`}>
          {lesson.side.toUpperCase()}
        </span>
        <span className="text-xs text-gray-600 ml-auto">{fmtTs(lesson.ts)}</span>
      </div>

      <div className="flex items-center gap-3 text-xs text-gray-500">
        <span>Güven: <span className="text-gray-300">{(lesson.confidence * 100).toFixed(0)}%</span></span>
        <span>Kapanış: <span className="text-gray-300">{lesson.close_reason}</span></span>
      </div>

      <p className="text-gray-300 text-sm leading-relaxed border-t border-gray-700/40 pt-2">
        {lesson.lesson}
      </p>
    </div>
  )
}

export default function LearningPage() {
  const [lessons, setLessons] = useState<Lesson[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'WIN' | 'LOSS'>('all')
  const [symbolFilter, setSymbolFilter] = useState('')

  const fetchLessons = useCallback(async () => {
    try {
      const data = await fetch('/api/learning').then(r => r.json())
      if (Array.isArray(data)) setLessons(data)
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchLessons()
    const t = setInterval(fetchLessons, 30000)
    return () => clearInterval(t)
  }, [fetchLessons])

  const symbols = Array.from(new Set(lessons.map(l => l.symbol))).sort()

  const filtered = lessons.filter(l => {
    if (filter !== 'all' && l.outcome !== filter) return false
    if (symbolFilter && l.symbol !== symbolFilter) return false
    return true
  })

  const wins = lessons.filter(l => l.outcome === 'WIN').length
  const losses = lessons.filter(l => l.outcome === 'LOSS').length
  const winRate = lessons.length > 0 ? (wins / lessons.length * 100).toFixed(0) : '—'
  const avgPnl = lessons.length > 0
    ? (lessons.reduce((s, l) => s + l.pnl_pct, 0) / lessons.length * 100).toFixed(2)
    : '—'

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* Header */}
      <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/60">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📈</span>
          <div>
            <h1 className="text-white font-bold text-base">AI Öğrenme Günlüğü</h1>
            <p className="text-gray-500 text-xs">Her kapanan trade&apos;den yapay zeka ders çıkarır, gelecek kararları iyileştirir</p>
          </div>
          <button
            onClick={fetchLessons}
            className="ml-auto text-xs text-orange-400 hover:text-orange-300 border border-orange-500/30 px-3 py-1.5 rounded-lg transition-colors"
          >
            Yenile
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Toplam Ders', value: lessons.length.toString(), color: 'text-white' },
          { label: 'Kazanan', value: wins.toString(), color: 'text-green-400' },
          { label: 'Kaybeden', value: losses.toString(), color: 'text-red-400' },
          { label: 'Ort. P&L', value: avgPnl !== '—' ? `${Number(avgPnl) >= 0 ? '+' : ''}${avgPnl}%` : '—', color: Number(avgPnl) >= 0 ? 'text-green-400' : 'text-red-400' },
        ].map(s => (
          <div key={s.label} className="border border-gray-800 rounded-xl p-3 bg-gray-900/40 text-center">
            <p className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</p>
            <p className="text-gray-500 text-xs mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Win rate bar */}
      {lessons.length > 0 && (
        <div className="border border-gray-800 rounded-xl p-3 bg-gray-900/40">
          <div className="flex items-center justify-between mb-1.5 text-xs text-gray-500">
            <span>Kazanma Oranı</span>
            <span className="font-bold text-white">{winRate}%</span>
          </div>
          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-green-600 to-green-400 rounded-full transition-all"
              style={{ width: `${winRate}%` }}
            />
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {(['all', 'WIN', 'LOSS'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              filter === f
                ? f === 'WIN' ? 'bg-green-900/40 border-green-600/50 text-green-400'
                  : f === 'LOSS' ? 'bg-red-900/40 border-red-600/50 text-red-400'
                  : 'bg-orange-900/40 border-orange-600/50 text-orange-400'
                : 'border-gray-700 text-gray-500 hover:text-gray-300'
            }`}
          >
            {f === 'all' ? 'Tümü' : f === 'WIN' ? '▲ Kazanan' : '▼ Kaybeden'}
          </button>
        ))}
        {symbols.length > 0 && (
          <select
            value={symbolFilter}
            onChange={e => setSymbolFilter(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-900 text-gray-400 focus:outline-none focus:border-orange-500"
          >
            <option value="">Tüm Semboller</option>
            {symbols.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </div>

      {/* Lessons list */}
      {loading ? (
        <div className="text-center py-16 text-gray-600">Dersler yükleniyor...</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 space-y-3">
          <p className="text-gray-600 text-sm">
            {lessons.length === 0
              ? 'Henüz ders yok — sistem trade kapattıkça burada görünür'
              : 'Bu filtreye uyan ders bulunamadı'}
          </p>
          {lessons.length === 0 && (
            <p className="text-gray-700 text-xs max-w-sm mx-auto">
              Her kapanan trade&apos;den sonra AI neden kazandığını/kaybettiğini analiz eder ve gelecek kararlar için kural üretir.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((l, i) => <LessonCard key={i} lesson={l} />)}
        </div>
      )}
    </div>
  )
}
