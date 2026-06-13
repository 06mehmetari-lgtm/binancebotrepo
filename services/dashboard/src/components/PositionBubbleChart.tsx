'use client'

import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'

export type BubblePoint = {
  id: string
  symbol: string
  x: number
  y: number
  z: number
  status: 'open' | 'closed'
  direction: string
  pnl_usdt?: number
  hold_min?: number
}

function fmtHold(min: number) {
  if (min < 60) return `${Math.round(min)}dk`
  return `${(min / 60).toFixed(1)}sa`
}

function BubbleTooltip({ active, payload }: { active?: boolean; payload?: { payload: BubblePoint }[] }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  const isOpen = d.status === 'open'
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-2.5 text-xs shadow-xl max-w-[200px]">
      <p className="text-white font-bold">{d.symbol}</p>
      <p className="text-gray-400">
        {d.direction === 'long' ? '▲ LONG' : '▼ SHORT'} · {isOpen ? '🟢 Açık' : '⚫ Kapalı'}
      </p>
      <p className={`font-mono font-bold ${d.y >= 0 ? 'text-green-400' : 'text-red-400'}`}>
        {d.y >= 0 ? '+' : ''}{d.y.toFixed(2)}%
        {d.pnl_usdt != null && (
          <span className="text-gray-400 font-normal"> ({d.pnl_usdt >= 0 ? '+' : ''}${d.pnl_usdt.toFixed(2)})</span>
        )}
      </p>
      <p className="text-gray-500">
        Boyut: ${d.z.toFixed(0)}
        {isOpen && d.hold_min != null ? ` · ${fmtHold(d.hold_min)}` : ''}
      </p>
    </div>
  )
}

export function buildBubblePoints(
  positions: {
    symbol: string
    direction: string
    size_usd: number
    unrealized_pct?: number
    unrealized_usdt?: number
    age_hours?: number
    entry_time?: number
  }[],
  trades: {
    symbol: string
    direction: string
    size_usd?: number
    pnl_pct: number
    pnl_usdt?: number
    closed_at?: number
  }[],
  maxClosed = 40,
): BubblePoint[] {
  const now = Date.now() / 1000
  const open: BubblePoint[] = positions.map((p, i) => {
    const holdMin = p.age_hours != null
      ? p.age_hours * 60
      : p.entry_time
        ? (now - p.entry_time) / 60
        : i * 2
    return {
      id: `open-${p.symbol}`,
      symbol: p.symbol,
      x: Math.max(1, holdMin),
      y: p.unrealized_pct ?? 0,
      z: Math.max(50, p.size_usd || 100),
      status: 'open' as const,
      direction: p.direction,
      pnl_usdt: p.unrealized_usdt,
      hold_min: holdMin,
    }
  })

  const sorted = [...trades]
    .filter(t => t.closed_at)
    .sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0))
    .slice(0, maxClosed)

  const closed: BubblePoint[] = sorted.map((t, i) => {
    const ageMin = t.closed_at ? (now - t.closed_at) / 60 : i * 5
    return {
      id: `closed-${t.symbol}-${t.closed_at}`,
      symbol: t.symbol,
      x: Math.max(1, ageMin),
      y: (t.pnl_pct ?? 0) * 100,
      z: Math.max(50, t.size_usd || 100),
      status: 'closed' as const,
      direction: t.direction,
      pnl_usdt: t.pnl_usdt,
    }
  })

  return [...open, ...closed]
}

export function PositionBubbleChart({
  points,
  height = 220,
}: {
  points: BubblePoint[]
  height?: number
}) {
  const openPts = points.filter(p => p.status === 'open')
  const closedPts = points.filter(p => p.status === 'closed')

  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center text-gray-600 text-sm" style={{ height }}>
        Açık veya kapanmış pozisyon olunca balon grafiği görünür
      </div>
    )
  }

  const zRange = points.map(p => p.z)
  const zMin = Math.min(...zRange)
  const zMax = Math.max(...zRange, zMin + 1)

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-4 text-[10px] text-gray-500 px-1">
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-full bg-green-500/80 animate-pulse" /> Açık ({openPts.length})
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-full bg-gray-500/70" /> Kapalı ({closedPts.length})
        </span>
        <span className="text-gray-600">X: süre (dk) · Y: PnL% · Boyut: $</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            type="number"
            dataKey="x"
            name="Süre"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={v => fmtHold(Number(v))}
            label={{ value: 'Süre', position: 'insideBottom', offset: -2, fill: '#4b5563', fontSize: 10 }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="PnL%"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={v => `${Number(v).toFixed(1)}%`}
            width={44}
          />
          <ZAxis type="number" dataKey="z" range={[40, 400]} domain={[zMin, zMax]} />
          <Tooltip content={<BubbleTooltip />} cursor={{ strokeDasharray: '3 3' }} />
          <ReferenceLine y={0} stroke="#374151" strokeDasharray="4 4" />
          {closedPts.length > 0 && (
            <Scatter name="Kapalı" data={closedPts} fill="#6b7280" fillOpacity={0.55}>
              {closedPts.map(p => (
                <Cell
                  key={p.id}
                  fill={(p.y >= 0 ? '#22c55e' : '#ef4444') + '99'}
                  stroke={(p.y >= 0 ? '#16a34a' : '#dc2626')}
                  strokeWidth={1}
                />
              ))}
            </Scatter>
          )}
          {openPts.length > 0 && (
            <Scatter name="Açık" data={openPts} fill="#22c55e" fillOpacity={0.75}>
              {openPts.map(p => (
                <Cell
                  key={p.id}
                  fill={(p.y >= 0 ? '#22c55e' : '#ef4444') + 'cc'}
                  stroke={(p.y >= 0 ? '#4ade80' : '#f87171')}
                  strokeWidth={2}
                />
              ))}
            </Scatter>
          )}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}
