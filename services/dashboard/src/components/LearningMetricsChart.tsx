'use client'

import {
  ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'

type NeatPoint = { ts: number; avg_fitness: number; count?: number }
type RlPoint = { ts: number; buffer_size: number; timesteps: number; status: string }
type WinPoint = { ts: number; win_rate: number; trade_n: number }

function fmtTs(ts: number) {
  return new Date(ts * 1000).toLocaleDateString('tr-TR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function LearningMetricsChart({
  neatByTime,
  rl,
  winRateTrend,
  height = 200,
}: {
  neatByTime: NeatPoint[]
  rl: RlPoint[]
  winRateTrend: WinPoint[]
  height?: number
}) {
  const hasNeat = neatByTime.length > 1
  const hasWin = winRateTrend.length > 1
  const hasRl = rl.length > 0

  if (!hasNeat && !hasWin && !hasRl) {
    return (
      <div className="flex items-center justify-center text-gray-600 text-sm" style={{ height }}>
        Öğrenme metrikleri birikiyor — NEAT evrimi veya kapanan işlemler sonrası grafik dolacak
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {hasWin && (
        <div>
          <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Kümülatif Win Rate (OMS işlemleri)</p>
          <ResponsiveContainer width="100%" height={height}>
            <ComposedChart data={winRateTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={fmtTs} tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={40} />
              <YAxis yAxisId="wr" domain={[0, 100]} tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} width={40} tickFormatter={v => `${v}%`} />
              <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 12 }} labelFormatter={fmtTs} formatter={(v: number) => [`${v.toFixed(1)}%`, 'Win Rate']} />
              <Line yAxisId="wr" type="monotone" dataKey="win_rate" stroke="#22c55e" strokeWidth={2} dot={false} name="Win Rate" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {hasNeat && (
        <div>
          <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">NEAT Fitness (yüksek = daha iyi — loss tersi)</p>
          <ResponsiveContainer width="100%" height={height}>
            <ComposedChart data={neatByTime} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={fmtTs} tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={40} />
              <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} axisLine={false} width={52} domain={['auto', 'auto']} />
              <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 12 }} labelFormatter={fmtTs} />
              <Bar dataKey="count" fill="#6366f1" opacity={0.35} name="Evrim sayısı" />
              <Line type="monotone" dataKey="avg_fitness" stroke="#a855f7" strokeWidth={2} dot={false} name="Ort. Fitness" />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {hasRl && (
        <div>
          <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">PPO RL Eğitim Döngüleri</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-1.5">Zaman</th>
                  <th className="text-left py-1.5">Buffer</th>
                  <th className="text-left py-1.5">Timesteps</th>
                  <th className="text-left py-1.5">Durum</th>
                </tr>
              </thead>
              <tbody>
                {rl.slice().reverse().slice(0, 8).map((r, i) => (
                  <tr key={`${r.ts}-${i}`} className="border-b border-gray-800/40">
                    <td className="py-1.5 text-gray-400">{fmtTs(r.ts)}</td>
                    <td className="py-1.5 font-mono text-blue-400">{r.buffer_size}</td>
                    <td className="py-1.5 font-mono text-purple-400">{r.timesteps.toLocaleString()}</td>
                    <td className={`py-1.5 ${r.status === 'ok' ? 'text-green-400' : 'text-yellow-400'}`}>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
