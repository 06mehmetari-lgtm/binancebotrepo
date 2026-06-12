'use client'

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'

export type ShadowCurve = { ts: number; equity: number; pnl?: number; symbol?: string; direction?: string }

const COLORS: Record<string, string> = {
  SHADOW_A: '#22c55e',
  SHADOW_B: '#3b82f6',
  SHADOW_C: '#f97316',
}

function fmtTs(ts: number) {
  return new Date(ts * 1000).toLocaleDateString('tr-TR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

type ChartRow = { ts: number; [key: string]: number }

function mergeCurves(curves: Record<string, ShadowCurve[]>, startEquity: number): ChartRow[] {
  const tsSet = new Set<number>()
  for (const pts of Object.values(curves)) {
    for (const p of pts) tsSet.add(p.ts)
  }
  const sortedTs = Array.from(tsSet).sort((a, b) => a - b)
  const last: Record<string, number> = {}
  for (const id of Object.keys(curves)) last[id] = startEquity

  return sortedTs.map(ts => {
    const row: ChartRow = { ts }
    for (const [id, pts] of Object.entries(curves)) {
      const hit = pts.filter(p => p.ts <= ts).pop()
      if (hit) last[id] = hit.equity
      row[id] = last[id]
    }
    return row
  })
}

export function ShadowEquityChart({
  curves,
  startEquity = 10000,
  height = 220,
}: {
  curves: Record<string, ShadowCurve[]>
  startEquity?: number
  height?: number
}) {
  const ids = Object.keys(curves).filter(id => (curves[id]?.length ?? 0) > 1)
  if (!ids.length) {
    return (
      <div className="flex items-center justify-center text-gray-600 text-sm" style={{ height }}>
        Shadow işlem kapanışlarından sonra equity eğrisi görünür
      </div>
    )
  }

  const data = mergeCurves(
    Object.fromEntries(ids.map(id => [id, curves[id]])),
    startEquity,
  )

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
        <XAxis dataKey="ts" tickFormatter={fmtTs} tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={50} />
        <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={v => `$${(v / 1000).toFixed(1)}K`} width={52} domain={['auto', 'auto']} />
        <Tooltip
          contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
          labelFormatter={fmtTs}
          formatter={(v: number, name: string) => [`$${v.toFixed(2)}`, name]}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine y={startEquity} stroke="#374151" strokeDasharray="4 4" />
        {ids.map(id => (
          <Line key={id} type="monotone" dataKey={id} name={id} stroke={COLORS[id] ?? '#94a3b8'} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
