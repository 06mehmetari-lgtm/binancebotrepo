'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  CartesianGrid,
} from 'recharts'
import {
  type PositionChartPayload,
  MISMATCH_COLORS,
  severityLabel,
} from '@/lib/position-charts'

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString('tr-TR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function fmtPrice(p: number) {
  if (p >= 1000) return p.toFixed(2)
  if (p >= 1) return p.toFixed(4)
  return p.toFixed(6)
}

type MiniChartProps = {
  title: string
  subtitle: string
  data: { ts: number; value: number; tsLabel: string }[]
  color: string
  refLines?: { y: number; stroke: string; label: string }[]
  height?: number
  valueFormatter?: (v: number) => string
}

function MiniChart({
  title,
  subtitle,
  data,
  color,
  refLines = [],
  height = 140,
  valueFormatter = fmtPrice,
}: MiniChartProps) {
  return (
    <div className="bg-gray-900/80 border border-gray-800 rounded-lg p-2.5">
      <div className="flex items-center justify-between mb-1">
        <p className="text-[10px] uppercase tracking-wider font-bold text-gray-400">{title}</p>
        <p className="text-[9px] text-gray-600">{subtitle}</p>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#1f2937" />
          <XAxis dataKey="tsLabel" tick={{ fontSize: 9, fill: '#6b7280' }} interval="preserveStartEnd" />
          <YAxis
            tick={{ fontSize: 9, fill: '#6b7280' }}
            width={52}
            tickFormatter={v => valueFormatter(Number(v))}
          />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
            formatter={(v: number) => [valueFormatter(v), '']}
            labelFormatter={(_, p) => (p?.[0]?.payload?.tsLabel as string) ?? ''}
          />
          {refLines.map(r => (
            <ReferenceLine
              key={r.label}
              y={r.y}
              stroke={r.stroke}
              strokeDasharray="4 4"
              label={{ value: r.label, fontSize: 8, fill: r.stroke }}
            />
          ))}
          <Area type="monotone" dataKey="value" stroke={color} fill={color} fillOpacity={0.12} strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function PositionTripleChart({ symbol }: { symbol: string }) {
  const [chart, setChart] = useState<PositionChartPayload | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)

  const fetchChart = useCallback(async () => {
    try {
      const res = await fetch(`/api/positions/${symbol}/chart`, { cache: 'no-store' })
      if (!res.ok) {
        setError(res.status === 404 ? 'Pozisyon kapalı' : `HTTP ${res.status}`)
        return
      }
      setChart(await res.json())
      setError('')
    } catch (e) {
      setError(String(e))
    }
  }, [symbol])

  useEffect(() => {
    fetchChart()
    const fast = setInterval(fetchChart, 400)
    const beat = setInterval(() => setTick(t => t + 1), 400)
    return () => {
      clearInterval(fast)
      clearInterval(beat)
    }
  }, [fetchChart])

  const sev = chart?.mismatch.severity ?? 'ok'
  const borderColor = MISMATCH_COLORS[sev] ?? MISMATCH_COLORS.ok

  const liveData = useMemo(
    () =>
      (chart?.live ?? []).map(p => ({
        ts: p.ts,
        value: p.price,
        tsLabel: fmtTime(p.ts),
      })),
    [chart?.live, tick],
  )

  const plannedData = useMemo(() => {
    const now = Date.now() / 1000
    return (chart?.planned ?? [])
      .filter(p => p.ts <= now + 60)
      .map(p => ({
        ts: p.ts,
        value: p.price,
        tsLabel: fmtTime(p.ts),
      }))
  }, [chart?.planned])

  const forecastData = useMemo(
    () =>
      (chart?.forecast ?? []).map(p => ({
        ts: p.ts,
        value: p.price,
        tsLabel: fmtTime(p.ts),
      })),
    [chart?.forecast, tick],
  )

  const deltaData = useMemo(
    () =>
      (chart?.delta ?? []).map(p => ({
        ts: p.ts,
        value: p.pnl_pct ?? 0,
        tsLabel: fmtTime(p.ts),
      })),
    [chart?.delta, tick],
  )

  if (error) {
    return <p className="text-xs text-gray-500 py-2">{error}</p>
  }

  if (!chart) {
    return (
      <div className="text-xs text-gray-500 animate-pulse py-4 text-center">
        Grafik yükleniyor… (400ms canlı)
      </div>
    )
  }

  const refEntry = chart.entry_price
  const refLines = [
    { y: refEntry, stroke: '#94a3b8', label: 'Giriş' },
    ...(chart.stop_loss ? [{ y: chart.stop_loss, stroke: '#ef4444', label: 'Stop' }] : []),
    ...(chart.take_profit_prices?.[0]
      ? [{ y: chart.take_profit_prices[0], stroke: '#22c55e', label: 'TP1' }]
      : []),
  ]

  return (
    <div
      className="space-y-3 rounded-xl border-2 p-3 transition-colors duration-300"
      style={{ borderColor: `${borderColor}55` }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-white font-bold text-sm">3'lü Anlık Analiz — {symbol}</p>
          <p className="text-[10px] text-gray-500">Planlı · Canlı · Fark · Tahmin — 400ms güncelleme</p>
        </div>
        <div className="text-right text-xs">
          <p className="font-mono text-white">{fmtPrice(chart.current_price)}</p>
          <p className={chart.unrealized_pct >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
            {chart.unrealized_pct >= 0 ? '+' : ''}
            {chart.unrealized_pct.toFixed(3)}%
          </p>
          <p className="text-[10px]" style={{ color: borderColor }}>
            {severityLabel(sev)} ({chart.mismatch.pct.toFixed(2)}%)
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
        <MiniChart
          title="① Planlı (giriş planı)"
          subtitle="Alırken hedeflenen yol"
          data={plannedData}
          color="#38bdf8"
          refLines={refLines}
        />
        <MiniChart
          title="② Canlı (salise)"
          subtitle={`${liveData.length} tick`}
          data={liveData}
          color="#a78bfa"
          refLines={refLines}
        />
        <MiniChart
          title="③ Fark (canlı − plan)"
          subtitle="Sapma % — kırmızı = risk"
          data={deltaData}
          color={borderColor}
          valueFormatter={v => `${v >= 0 ? '+' : ''}${v.toFixed(3)}%`}
        />
      </div>

      <MiniChart
        title="④ Gelecek tahmin modeli (sistem)"
        subtitle="Outcome + rejim — uyumsuzlukta renk güncellenir"
        data={forecastData}
        color={sev === 'ok' ? '#4ade80' : sev === 'drift' ? '#facc15' : '#fb923c'}
        refLines={[{ y: chart.current_price, stroke: '#e5e7eb', label: 'Şimdi' }]}
        height={120}
      />

      {chart.fills && chart.fills.length > 0 && (
        <div className="text-[10px] text-gray-500">
          Kademeler:{' '}
          {chart.fills.map((f, i) => (
            <span key={i} className="text-gray-400 mr-2">
              T{f.tier ?? i + 1} @{fmtPrice(f.price)} ({f.reason})
            </span>
          ))}
        </div>
      )}

      {chart.tiers_pct && chart.tiers_pct.length > 0 && (
        <div className="flex flex-wrap gap-2 text-[10px]">
          {chart.tiers_pct.map((t, i) => (
            <span key={i} className="px-2 py-0.5 rounded bg-green-950/40 text-green-400 border border-green-800/40">
              TP{i + 1}: %{t}
              {chart.take_profit_prices?.[i] ? ` → ${fmtPrice(chart.take_profit_prices[i])}` : ''}
            </span>
          ))}
          {chart.stop_loss != null && (
            <span className="px-2 py-0.5 rounded bg-red-950/40 text-red-400 border border-red-800/40">
              Stop: {fmtPrice(chart.stop_loss)}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
