'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useStreamInvalidate } from '@/hooks/useStream'

type Row = {
  symbol: string
  direction: string
  confidence: number
  sqs: number
  regime: string | null
  drift: string
  depth_label: string
  imbalance_5: number | null
  ai_verdict: string
  ai_confidence: number
  learn_stage: string
  trade_action?: string
  avoid_hint?: string
}

export default function AnalizPage() {
  const [top, setTop] = useState<Row[]>([])
  const [longOp, setLongOp] = useState<Row[]>([])
  const [shortOp, setShortOp] = useState<Row[]>([])
  const [minSqs, setMinSqs] = useState(55)

  const load = useCallback(() => {
    fetch(`/api/analiz?limit=80&min_sqs=${minSqs}`)
      .then(r => r.json())
      .then(d => {
        setTop(d.top ?? [])
        setLongOp(d.long_opportunities ?? [])
        setShortOp(d.short_opportunities ?? [])
      })
      .catch(() => {})
  }, [minSqs])

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [load])

  useStreamInvalidate({
    hints: ['signal', 'features', 'agents'],
    debounceMs: 800,
    onEvent: () => load(),
  })

  const Table = ({ rows, title }: { rows: Row[]; title: string }) => (
    <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex justify-between">
        <h2 className="text-orange-400 font-semibold text-sm">{title}</h2>
        <span className="text-xs text-gray-600">{rows.length} coin</span>
      </div>
      <div className="overflow-x-auto max-h-[420px]">
        <table className="w-full text-xs">
          <thead className="text-gray-500 bg-gray-950 sticky top-0">
            <tr>
              <th className="text-left p-2">Symbol</th>
              <th>SQS</th>
              <th>Dir</th>
              <th>Conf</th>
              <th>Depth</th>
              <th>AI</th>
              <th>L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.symbol + r.direction} className="border-t border-gray-800/40 hover:bg-gray-800/30">
                <td className="p-2">
                  <Link href={`/coin/${r.symbol}`} className="text-white font-bold hover:text-orange-400">
                    {r.symbol}
                  </Link>
                </td>
                <td className={`p-2 font-bold ${r.sqs >= 70 ? 'text-green-400' : 'text-yellow-400'}`}>
                  {r.sqs}
                </td>
                <td className={`p-2 ${r.direction === 'long' ? 'text-green-400' : r.direction === 'short' ? 'text-red-400' : 'text-gray-500'}`}>
                  {r.direction}
                </td>
                <td className="p-2">{Math.round(r.confidence * 100)}%</td>
                <td className="p-2 text-cyan-600">{r.depth_label}</td>
                <td className="p-2 text-gray-400">
                  {r.ai_verdict} {Math.round((r.ai_confidence ?? 0) * 100)}%
                </td>
                <td className="p-2 text-purple-400">{r.learn_stage}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap justify-between gap-3">
        <div>
          <h1 className="text-2xl font-black text-white">🤖 AI Analiz</h1>
          <p className="text-gray-500 text-sm mt-1">
            SQS + order book imbalance + öğrenme stage + backtest — en iyi fırsatlar üstte
          </p>
        </div>
        <label className="text-sm text-gray-400 flex items-center gap-2">
          Min SQS
          <input
            type="range"
            min={40}
            max={85}
            value={minSqs}
            onChange={e => setMinSqs(Number(e.target.value))}
            className="w-32"
          />
          <span className="text-white font-mono">{minSqs}</span>
        </label>
      </header>
      <Table rows={top.slice(0, 30)} title="🏆 En yüksek SQS (tüm yönler)" />
      <div className="grid lg:grid-cols-2 gap-4">
        <Table rows={longOp} title="▲ LONG fırsatları" />
        <Table rows={shortOp} title="▼ SHORT fırsatları" />
      </div>
    </div>
  )
}
