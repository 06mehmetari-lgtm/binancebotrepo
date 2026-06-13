'use client'

import { useCallback, useEffect, useState } from 'react'

type CapitalData = {
  usd_cap: number
  updated_at?: number | null
  source?: string
  sizing?: {
    slot_budget_usd: number
    max_margin_per_position_usd: number
    max_open_positions: number
    max_leverage?: number
    example_65conf_3x?: { margin_usd: number; notional_usd: number }
  }
}

export default function PortfolioCapitalEditor({
  openCount,
  maxOpen,
}: {
  openCount: number
  maxOpen: number
}) {
  const [data, setData] = useState<CapitalData | null>(null)
  const [input, setInput] = useState('10000')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const j = await fetch('/api/portfolio/capital', { cache: 'no-store' }).then(r => r.json())
      if (j.usd_cap) {
        setData(j)
        setInput(String(Math.round(j.usd_cap)))
        setErr('')
      }
    } catch (e) {
      setErr(String(e))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const usd = parseFloat(input.replace(/,/g, ''))
      if (!Number.isFinite(usd) || usd < 100) {
        setErr('Geçerli bir bakiye girin (min $100)')
        return
      }
      const res = await fetch('/api/portfolio/capital', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ usd_cap: usd }),
      })
      const j = await res.json()
      if (!res.ok) {
        setErr(j.error ?? 'Kayıt başarısız')
        return
      }
      setMsg(j.message ?? 'Bakiye kaydedildi')
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const presets = [5000, 10000, 25000, 50000, 100000]
  const cap = data?.usd_cap ?? (parseFloat(input) || 10000)
  const sizing = data?.sizing

  return (
    <section className="bg-gray-900 border border-blue-800/40 rounded-xl p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-blue-400 font-bold text-sm">💰 İşlem bakiyesi (USD)</h2>
          <p className="text-gray-500 text-xs mt-1">
            Girdiğiniz tutar = paper portföy üst limiti. Pozisyon boyutu, slot bütçesi ve max coin sayısı buna göre hesaplanır.
          </p>
        </div>
        <span className="text-xs text-gray-500">
          Açık: {openCount} / {maxOpen} slot
        </span>
      </div>

      <div className="flex flex-wrap gap-2 items-end">
        <label className="flex-1 min-w-[200px] space-y-1">
          <span className="text-gray-500 text-xs">Bakiye ($)</span>
          <input
            type="text"
            inputMode="decimal"
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-lg"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="10000"
          />
        </label>
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold disabled:opacity-50"
        >
          {busy ? 'Kaydediliyor…' : 'Uygula'}
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {presets.map(p => (
          <button
            key={p}
            type="button"
            onClick={() => setInput(String(p))}
            className={`px-2 py-1 rounded text-xs font-mono border ${
              parseFloat(input) === p
                ? 'border-blue-500 text-blue-300 bg-blue-950/40'
                : 'border-gray-700 text-gray-400 hover:bg-gray-800'
            }`}
          >
            ${p.toLocaleString()}
          </button>
        ))}
      </div>

      {sizing && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <div className="bg-gray-950 rounded-lg p-2 border border-gray-800">
            <p className="text-gray-500">Slot bütçesi</p>
            <p className="text-white font-mono font-bold">${sizing.slot_budget_usd.toLocaleString()}</p>
            <p className="text-gray-600 text-[10px]">${cap.toLocaleString()} / {sizing.max_open_positions}</p>
          </div>
          <div className="bg-gray-950 rounded-lg p-2 border border-gray-800">
            <p className="text-gray-500">Max margin / pozisyon</p>
            <p className="text-white font-mono font-bold">${sizing.max_margin_per_position_usd.toLocaleString()}</p>
          </div>
          <div className="bg-gray-950 rounded-lg p-2 border border-gray-800">
            <p className="text-gray-500">Örnek (conf 65%, 3x)</p>
            <p className="text-white font-mono">
              ${sizing.example_65conf_3x?.margin_usd?.toLocaleString() ?? '—'} margin
            </p>
            <p className="text-violet-400 font-mono text-[10px]">
              ≈ ${sizing.example_65conf_3x?.notional_usd?.toLocaleString() ?? '—'} notional
            </p>
          </div>
          <div className="bg-gray-950 rounded-lg p-2 border border-gray-800">
            <p className="text-gray-500">Aktif bakiye</p>
            <p className="text-green-400 font-mono font-bold">${cap.toLocaleString()}</p>
            {data?.updated_at && (
              <p className="text-gray-600 text-[10px]">
                {new Date(data.updated_at * 1000).toLocaleString('tr-TR')}
              </p>
            )}
          </div>
        </div>
      )}

      {msg && (
        <p className="text-green-400 text-xs bg-green-950/30 border border-green-800/40 rounded px-3 py-2">{msg}</p>
      )}
      {err && (
        <p className="text-red-400 text-xs bg-red-950/30 border border-red-800/40 rounded px-3 py-2">{err}</p>
      )}
    </section>
  )
}
