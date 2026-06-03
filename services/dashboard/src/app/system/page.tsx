'use client'

import { useEffect, useState } from 'react'

type SysData = {
  score: number
  data_pipeline: {
    healthy: boolean
    features: number
    signals: number
    agent_verdicts: number
    learn_profiles: number
    symbols: number
    activity_events: number
  }
  services: { name: string; alive: boolean; age_sec: number | null }[]
  problems: { name: string; alive: boolean }[]
  trading_halted: boolean
  promotion: { approved?: boolean; reason?: string }
}

export default function SystemPage() {
  const [data, setData] = useState<SysData | null>(null)

  useEffect(() => {
    const load = () => fetch('/api/system').then(r => r.json()).then(setData).catch(() => {})
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  if (!data) {
    return <p className="text-gray-500 text-center mt-20">Sistem durumu yükleniyor…</p>
  }

  return (
    <div className="space-y-5 max-w-5xl">
      <header>
        <h1 className="text-2xl font-black text-white">🖥 Sistem Durumu</h1>
        <p className="text-gray-500 text-sm mt-1">
          Redis pipeline + servis nabzı · Sunucuda tam kontrol: <code className="text-orange-400">bash check.sh</code>
        </p>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs">Sistem skoru</p>
          <p className={`text-3xl font-black ${data.score >= 80 ? 'text-green-400' : 'text-yellow-400'}`}>
            {data.score}
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs">Sembol</p>
          <p className="text-2xl font-bold text-white">{data.data_pipeline.symbols}</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs">Features</p>
          <p className="text-2xl font-bold text-cyan-400">{data.data_pipeline.features}</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-gray-500 text-xs">Sinyaller</p>
          <p className="text-2xl font-bold text-orange-400">{data.data_pipeline.signals}</p>
        </div>
      </div>

      {data.trading_halted && (
        <p className="text-red-400 bg-red-950/40 border border-red-800 rounded-lg px-4 py-2 text-sm font-bold">
          ⛔ İşlemler duraklatıldı
        </p>
      )}

      <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-green-400 font-semibold text-sm mb-3">Servisler</h2>
        <div className="grid sm:grid-cols-2 gap-2">
          {data.services.map(s => (
            <div key={s.name} className="flex justify-between text-sm py-1 border-b border-gray-800/50">
              <span className="text-gray-400">{s.name}</span>
              <span className={s.alive ? 'text-green-400' : 'text-red-400'}>
                {s.alive ? `OK ${s.age_sec ?? ''}s` : 'DOWN'}
              </span>
            </div>
          ))}
        </div>
      </section>

      {data.problems.length > 0 && (
        <section className="bg-red-950/30 border border-red-800/50 rounded-xl p-4">
          <h2 className="text-red-400 font-semibold text-sm">Sorunlu servisler</h2>
          <ul className="mt-2 text-sm text-red-200">
            {data.problems.map(p => (
              <li key={p.name}>{p.name}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
