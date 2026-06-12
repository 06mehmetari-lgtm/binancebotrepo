'use client'

import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, Area, AreaChart,
} from 'recharts'

export type CurvePoint = {
  ts: number
  equity: number
  pnl?: number
  symbol?: string
  direction?: string
  kind?: string
}

function fmtTs(ts: number) {
  const d = new Date(ts * 1000)
  if (Date.now() / 1000 - ts < 120) {
    return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }
  return d.toLocaleDateString('tr-TR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function CustomTooltip({
  active,
  payload,
  startEquity,
}: {
  active?: boolean
  payload?: { payload: CurvePoint }[]
  startEquity: number
}) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  const pnl = d.equity - startEquity
  const kindLabel =
    d.kind === 'live' ? '● Canlı' : d.kind === 'snapshot' ? '○ Saatlik' : d.kind === 'trade' ? '◆ Kapanış' : ''
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-2.5 text-xs shadow-xl">
      <p className="text-gray-400">{fmtTs(d.ts)} {kindLabel && <span className="text-blue-400">{kindLabel}</span>}</p>
      <p className="text-white font-bold font-mono">
        ${d.equity.toLocaleString('en-US', { maximumFractionDigits: 2 })}
      </p>
      <p className={`font-mono font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
        {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
      </p>
      {d.symbol && (
        <p className="text-gray-500 mt-0.5">
          {d.symbol} {d.direction}
          {d.pnl != null && (
            <span className={d.pnl >= 0 ? ' text-green-500' : ' text-red-500'}>
              {' '}
              ({d.pnl >= 0 ? '+' : ''}${d.pnl.toFixed(2)})
            </span>
          )}
        </p>
      )}
    </div>
  )
}

export function LiveEquityChart({
  curve,
  startEquity = 10000,
  height = 180,
  emptyMessage = 'İlk kapanan işlemden sonra equity eğrisi görünür',
}: {
  curve: CurvePoint[]
  startEquity?: number
  height?: number
  emptyMessage?: string
}) {
  if (curve.length < 2) {
    return (
      <div className="flex items-center justify-center text-gray-600 text-sm" style={{ height }}>
        {emptyMessage}
      </div>
    )
  }

  const lastEquity = curve[curve.length - 1]?.equity ?? startEquity
  const isPositive = lastEquity >= startEquity
  const gradId = `eqGrad-${height}`

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={curve} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={isPositive ? '#16a34a' : '#dc2626'} stopOpacity={0.25} />
            <stop offset="95%" stopColor={isPositive ? '#16a34a' : '#dc2626'} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
        <XAxis
          dataKey="ts"
          tickFormatter={fmtTs}
          tick={{ fill: '#6b7280', fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          minTickGap={40}
        />
        <YAxis
          tick={{ fill: '#6b7280', fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={v => `$${(v / 1000).toFixed(1)}K`}
          width={52}
          domain={['auto', 'auto']}
        />
        <Tooltip content={<CustomTooltip startEquity={startEquity} />} />
        <ReferenceLine y={startEquity} stroke="#374151" strokeDasharray="4 4" strokeWidth={1} />
        <Area
          type="monotone"
          dataKey="equity"
          stroke={isPositive ? '#16a34a' : '#dc2626'}
          strokeWidth={2}
          fill={`url(#${gradId})`}
          dot={(props: { cx?: number; cy?: number; payload?: CurvePoint }) => {
            const p = props.payload
            if (!p || p.kind !== 'trade') return <g key={`dot-${p?.ts}`} />
            const fill = (p.pnl ?? 0) >= 0 ? '#16a34a' : '#dc2626'
            return <circle key={`dot-${p.ts}`} cx={props.cx} cy={props.cy} r={3} fill={fill} stroke="#111" strokeWidth={1} />
          }}
          activeDot={{ r: 5, fill: isPositive ? '#16a34a' : '#dc2626' }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
