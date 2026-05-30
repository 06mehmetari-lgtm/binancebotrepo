'use client'
import { useEffect, useState } from 'react'

interface ShadowEntry { shadow_id: string; sharpe: number; win_rate: number; trades: number; return: number; promotion_ready: boolean }

export default function ShadowPage() {
  const [data, setData] = useState<ShadowEntry[]>([])
  useEffect(() => {
    const fetch_ = () => fetch('/api/shadow').then(r => r.json()).then(d => setData(Array.isArray(d) ? d : []))
    fetch_()
    const t = setInterval(fetch_, 10000)
    return () => clearInterval(t)
  }, [])

  return (
    <div>
      <h1 className="text-xl font-bold text-blue-400 mb-4">Shadow Trading Universes</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {data.map(s => (
          <div key={s.shadow_id} className={`bg-gray-900 rounded-lg p-5 border ${s.promotion_ready ? 'border-yellow-500' : 'border-gray-800'}`}>
            <div className="flex justify-between items-center mb-3">
              <span className="font-bold text-lg">{s.shadow_id}</span>
              {s.promotion_ready && <span className="text-yellow-400 text-sm">🏆 PROMOTION READY</span>}
            </div>
            <div className="space-y-2 text-sm">
              <Row label="Sharpe" value={s.sharpe.toFixed(3)} ok={s.sharpe >= 1.2} target="≥ 1.2" />
              <Row label="Win Rate" value={(s.win_rate*100).toFixed(1)+'%'} ok={s.win_rate >= 0.55} target="≥ 55%" />
              <Row label="Trades" value={s.trades.toString()} ok={s.trades >= 30} target="≥ 30" />
              <Row label="Return" value={(s.return*100).toFixed(2)+'%'} ok={s.return > 0} target="> 0%" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Row({ label, value, ok, target }: { label: string; value: string; ok: boolean; target: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-400">{label}</span>
      <span className={ok ? 'text-green-400' : 'text-red-400'}>{value} <span className="text-gray-600 text-xs">({target})</span></span>
    </div>
  )
}
