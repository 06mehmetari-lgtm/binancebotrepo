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
  Legend,
} from 'recharts'
import {
  type PositionChartPayload,
  MISMATCH_COLORS,
  ACTION_COLORS,
  severityLabel,
  actionLabel,
} from '@/lib/position-charts'

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString('tr-TR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function fmtPrice(p: number) {
  if (!Number.isFinite(p)) return '—'
  if (Math.abs(p) >= 1000) return p.toFixed(2)
  if (Math.abs(p) >= 1) return p.toFixed(4)
  return p.toFixed(6)
}

/** Blueprint + canlı aynı grafikte — birbirini konuşturur */
function SyncedPriceChart({
  live,
  blueprint,
  forecast,
  entry,
  stop,
  tp,
  mismatchColor,
}: {
  live: { tsLabel: string; live: number; blueprint: number | null }[]
  blueprint: { tsLabel: string; blueprint: number }[]
  forecast: { tsLabel: string; forecast: number }[]
  entry: number
  stop: number | null
  tp: number | null
  mismatchColor: string
}) {
  const merged = useMemo(() => {
    const map = new Map<string, Record<string, number | string | undefined>>()
    for (const r of live) {
      const row: Record<string, number | string | undefined> = { tsLabel: r.tsLabel, live: r.live }
      if (r.blueprint != null) row.blueprint = r.blueprint
      map.set(r.tsLabel, row)
    }
    for (const r of blueprint.slice(-30)) {
      const row = map.get(r.tsLabel) ?? { tsLabel: r.tsLabel }
      row.blueprint = r.blueprint
      map.set(r.tsLabel, row)
    }
    for (const r of forecast.slice(0, 20)) {
      const row = map.get(r.tsLabel) ?? { tsLabel: r.tsLabel }
      row.forecast = r.forecast
      map.set(r.tsLabel, row)
    }
    return Array.from(map.values()).slice(-80)
  }, [live, blueprint, forecast])

  return (
    <div className="bg-gray-900/90 border border-gray-800 rounded-xl p-3">
      <p className="text-[10px] uppercase tracking-wider font-bold text-cyan-400 mb-2">
        ① AL BLUEPRINT + ② CANLI (senkron)
      </p>
      <p className="text-[9px] text-gray-600 mb-2">Mavi donmuş plan · Mor canlı · Yeşil tahmin</p>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={merged} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#1f2937" />
          <XAxis dataKey="tsLabel" tick={{ fontSize: 8, fill: '#6b7280' }} interval="preserveEnd" />
          <YAxis tick={{ fontSize: 8, fill: '#6b7280' }} width={56} tickFormatter={v => fmtPrice(Number(v))} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: `1px solid ${mismatchColor}`, fontSize: 10 }}
            formatter={(v: number, name: string) => [fmtPrice(v), name]}
          />
          <Legend wrapperStyle={{ fontSize: 9 }} />
          <ReferenceLine y={entry} stroke="#94a3b8" strokeDasharray="4 4" label={{ value: 'Giriş', fontSize: 8 }} />
          {stop != null && <ReferenceLine y={stop} stroke="#ef4444" strokeDasharray="4 4" />}
          {tp != null && <ReferenceLine y={tp} stroke="#22c55e" strokeDasharray="4 4" />}
          <Line type="monotone" dataKey="blueprint" name="Blueprint" stroke="#38bdf8" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
          <Line type="monotone" dataKey="live" name="Canlı" stroke="#a78bfa" strokeWidth={2.5} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="forecast" name="Tahmin" stroke="#4ade80" strokeWidth={1.5} strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function AnalysisChart({
  data,
  color,
}: {
  data: { tsLabel: string; delta: number; upnl: number }[]
  color: string
}) {
  return (
    <div className="bg-gray-900/90 border border-gray-800 rounded-xl p-3">
      <p className="text-[10px] uppercase tracking-wider font-bold text-orange-400 mb-2">
        ③ SÜREKLİ ANALİZ (alındıktan sonra)
      </p>
      <p className="text-[9px] text-gray-600 mb-2">Canlı − blueprint sapması % · Al/sat kararı buradan</p>
      <ResponsiveContainer width="100%" height={150}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#1f2937" />
          <XAxis dataKey="tsLabel" tick={{ fontSize: 8, fill: '#6b7280' }} interval="preserveEnd" />
          <YAxis tick={{ fontSize: 8, fill: '#6b7280' }} width={48} tickFormatter={v => `${Number(v).toFixed(2)}%`} />
          <Tooltip contentStyle={{ background: '#111827', fontSize: 10 }} />
          <ReferenceLine y={0} stroke="#4b5563" />
          <Area type="monotone" dataKey="delta" stroke={color} fill={color} fillOpacity={0.2} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="upnl" name="PnL%" stroke="#a78bfa" strokeWidth={1} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function PositionTripleChart({ symbol }: { symbol: string }) {
  const [chart, setChart] = useState<PositionChartPayload | null>(null)
  const [error, setError] = useState('')
  const [, setTick] = useState(0)

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
    const id = setInterval(() => {
      fetchChart()
      setTick(t => t + 1)
    }, 350)
    return () => clearInterval(id)
  }, [fetchChart])

  const sev = chart?.mismatch.severity ?? 'ok'
  const borderColor = MISMATCH_COLORS[sev]
  const action = chart?.consensus?.action ?? 'hold'
  const actionColor = ACTION_COLORS[action] ?? '#6b7280'

  const liveOverlay = useMemo(() => {
    if (!chart) return []
    return chart.live.map(p => {
      const bp = chart.blueprint_curve.find(b => Math.abs(b.ts - p.ts) < 120)?.price
        ?? chart.analysis.find(a => Math.abs(a.ts - p.ts) < 2)?.blueprint_price
      return {
        tsLabel: fmtTime(p.ts),
        live: p.price,
        blueprint: bp ?? null,
      }
    })
  }, [chart])

  const blueprintData = useMemo(
    () => (chart?.blueprint_curve ?? []).map(p => ({ tsLabel: fmtTime(p.ts), blueprint: p.price })),
    [chart?.blueprint_curve],
  )

  const forecastData = useMemo(
    () => (chart?.forecast ?? []).map(p => ({ tsLabel: fmtTime(p.ts), forecast: p.price })),
    [chart?.forecast],
  )

  const analysisData = useMemo(
    () =>
      (chart?.analysis?.length ? chart.analysis : chart?.delta ?? []).map(p => ({
        tsLabel: fmtTime(p.ts),
        delta: p.delta_pct ?? p.pnl_pct ?? 0,
        upnl: chart?.live.find(l => Math.abs(l.ts - p.ts) < 2)?.pnl_pct ?? 0,
      })),
    [chart],
  )

  if (error) return <p className="text-xs text-gray-500 py-2">{error}</p>
  if (!chart) {
    return <div className="text-xs text-gray-500 animate-pulse py-6 text-center">Grafik beyni yükleniyor… (350ms)</div>
  }

  return (
    <div
      className="space-y-3 rounded-xl border-2 p-3 transition-all duration-200"
      style={{ borderColor: `${borderColor}88`, boxShadow: sev === 'critical' ? `0 0 20px ${borderColor}33` : undefined }}
    >
      {/* Üst bilgi bandı */}
      <div className="flex flex-wrap gap-3 justify-between items-start">
        <div>
          <p className="text-white font-bold text-sm">Grafik Beyni — {symbol}</p>
          <p className="text-[10px] text-gray-500">Blueprint ↔ Canlı ↔ Analiz ↔ Tahmin ↔ Ollama</p>
        </div>
        <div className="text-right text-xs space-y-0.5">
          <p className="font-mono text-white text-base">{fmtPrice(chart.current_price)}</p>
          <p className={chart.unrealized_pct >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
            Net PnL {chart.unrealized_pct >= 0 ? '+' : ''}{chart.unrealized_pct.toFixed(3)}%
          </p>
        </div>
      </div>

      {/* Blueprint narrative — AL derken çıkan plan */}
      {chart.blueprint?.narrative && (
        <div className="bg-blue-950/40 border border-blue-800/50 rounded-lg p-2.5 text-[11px]">
          <p className="text-blue-400 font-bold text-[10px] uppercase mb-1">AL anı blueprint (donmuş)</p>
          <p className="text-gray-200 leading-relaxed">{chart.blueprint.narrative}</p>
          {chart.blueprint.reasons && chart.blueprint.reasons.length > 0 && (
            <p className="text-gray-500 mt-1">{chart.blueprint.reasons.join(' · ')}</p>
          )}
        </div>
      )}

      {/* Konsensüs — 3 grafik konuşması */}
      {chart.consensus && (
        <div
          className="rounded-lg p-2.5 border text-[11px]"
          style={{ borderColor: `${actionColor}66`, background: `${actionColor}11` }}
        >
          <p className="font-bold" style={{ color: actionColor }}>
            Konsensüs: {actionLabel(chart.consensus.action)} ({chart.consensus.urgency})
          </p>
          <p className="text-gray-400 mt-0.5">
            Skor {(chart.consensus.score * 100).toFixed(0)}% · {chart.consensus.reasons?.join(' · ')}
          </p>
          {chart.consensus.layers && (
            <p className="text-gray-600 text-[10px] mt-1 font-mono">
              {Object.entries(chart.consensus.layers).map(([k, v]) => `${k}:${v}`).join(' | ')}
            </p>
          )}
        </div>
      )}

      {/* Neden düşüyor/çıkıyor */}
      <div className="bg-gray-950/80 border border-gray-800 rounded-lg p-2.5">
        <p className="text-[10px] uppercase text-amber-500 font-bold mb-1">Neden hareket ediyor?</p>
        <p className="text-gray-200 text-xs leading-relaxed">
          {chart.why_move || chart.rolling?.narrative || severityLabel(sev)}
        </p>
        {chart.rolling?.velocity_pct_per_min != null && (
          <p className="text-gray-500 text-[10px] mt-1 font-mono">
            Hız ~{chart.rolling.velocity_pct_per_min >= 0 ? '+' : ''}
            {chart.rolling.velocity_pct_per_min.toFixed(3)}%/dk · {chart.rolling.trend}
          </p>
        )}
      </div>

      {/* Ollama dersi */}
      {chart.llm_lesson && (
        <div className="bg-violet-950/40 border border-violet-700/50 rounded-lg p-2.5">
          <p className="text-violet-400 text-[10px] uppercase font-bold mb-1">Ollama öğrenme</p>
          <p className="text-gray-200 text-xs leading-relaxed">{chart.llm_lesson}</p>
        </div>
      )}

      <SyncedPriceChart
        live={liveOverlay}
        blueprint={blueprintData}
        forecast={forecastData}
        entry={chart.entry_price}
        stop={chart.stop_loss ?? null}
        tp={chart.take_profit_prices?.[0] ?? null}
        mismatchColor={borderColor}
      />

      <AnalysisChart data={analysisData} color={borderColor} />

      {/* Kademeler */}
      <div className="flex flex-wrap gap-2 text-[10px]">
        {chart.tiers_pct?.map((t, i) => (
          <span key={i} className="px-2 py-1 rounded bg-green-950/50 text-green-400 border border-green-800/40">
            TP{i + 1} %{t}
            {chart.take_profit_prices?.[i] ? ` @ ${fmtPrice(chart.take_profit_prices[i])}` : ''}
          </span>
        ))}
        {chart.stop_loss != null && (
          <span className="px-2 py-1 rounded bg-red-950/50 text-red-400 border border-red-800/40">
            Stop {fmtPrice(chart.stop_loss)}
          </span>
        )}
        {chart.fills?.map((f, i) => (
          <span key={`f${i}`} className="px-2 py-1 rounded bg-gray-800 text-gray-400">
            Kademe {f.tier ?? i + 1}: {fmtPrice(f.price)} ({f.reason})
          </span>
        ))}
      </div>

      <p className="text-[9px] text-gray-600 text-right">
        {severityLabel(sev)} · güncelleme {fmtTime(chart.updated_at)}
      </p>
    </div>
  )
}
