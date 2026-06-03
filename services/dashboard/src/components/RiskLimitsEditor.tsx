'use client'

import { useCallback, useEffect, useState } from 'react'
import type { RiskLimitsConfig } from '@/lib/risk-limits-config'
import { RISK_LIMITS_DEFAULTS } from '@/lib/risk-limits-config'

type FormState = {
  max_leverage: string
  max_position_pct: string
  max_daily_loss_pct: string
  max_open_positions: string
  min_signal_confidence_pct: string
  min_immunity_confidence_pct: string
  max_trades_per_day: string
}

function limitsToForm(l: RiskLimitsConfig): FormState {
  return {
    max_leverage: String(l.max_leverage),
    max_position_pct: String(Math.round(l.max_position_pct * 1000) / 10),
    max_daily_loss_pct: String(Math.round(l.max_daily_loss_pct * 1000) / 10),
    max_open_positions: String(l.max_open_positions),
    min_signal_confidence_pct: String(Math.round(l.min_signal_confidence * 1000) / 10),
    min_immunity_confidence_pct: String(Math.round(l.min_immunity_confidence * 1000) / 10),
    max_trades_per_day: String(l.max_trades_per_day),
  }
}

function formToPayload(f: FormState) {
  return {
    max_leverage: parseFloat(f.max_leverage),
    max_position_pct: parseFloat(f.max_position_pct) / 100,
    max_daily_loss_pct: parseFloat(f.max_daily_loss_pct) / 100,
    max_open_positions: parseInt(f.max_open_positions, 10),
    min_signal_confidence: parseFloat(f.min_signal_confidence_pct) / 100,
    min_immunity_confidence: parseFloat(f.min_immunity_confidence_pct) / 100,
    max_trades_per_day: parseInt(f.max_trades_per_day, 10),
    updated_by: 'dashboard_positions',
  }
}

export default function RiskLimitsEditor({
  openCount,
}: {
  openCount: number
}) {
  const [form, setForm] = useState<FormState>(limitsToForm(RISK_LIMITS_DEFAULTS))
  const [source, setSource] = useState('')
  const [updatedAt, setUpdatedAt] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetch('/api/risk-limits').then(r => r.json())
      if (data.limits) {
        setForm(limitsToForm(data.limits))
        setSource(data.source ?? '')
        if (data.limits.updated_at) {
          setUpdatedAt(
            new Date(data.limits.updated_at * 1000).toLocaleString('tr-TR'),
          )
        }
      }
    } catch {
      setErr('Limitler yüklenemedi')
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
      const res = await fetch('/api/risk-limits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formToPayload(form)),
      })
      const j = await res.json()
      if (!res.ok) {
        setErr(j.error ?? 'Kayıt başarısız')
        return
      }
      setMsg(j.message ?? 'Kaydedildi')
      if (j.limits) {
        setForm(limitsToForm(j.limits))
        setSource('database')
        if (j.limits.updated_at) {
          setUpdatedAt(new Date(j.limits.updated_at * 1000).toLocaleString('tr-TR'))
        }
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const maxOpen = parseInt(form.max_open_positions, 10) || 3

  const fields: { key: keyof FormState; label: string }[] = [
    { key: 'max_leverage', label: 'Max kaldıraç (×)' },
    { key: 'max_position_pct', label: 'Max pozisyon (%)' },
    { key: 'max_daily_loss_pct', label: 'Max günlük kayıp (%)' },
    { key: 'max_open_positions', label: 'Max açık pozisyon' },
    { key: 'min_signal_confidence_pct', label: 'Min sinyal güveni (%)' },
    { key: 'min_immunity_confidence_pct', label: 'Min immunity güveni (%)' },
    { key: 'max_trades_per_day', label: 'Max işlem / gün' },
  ]

  return (
    <section className="bg-gray-900 border border-orange-800/40 rounded-xl p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-orange-400 font-bold text-sm">⚙ Dinamik risk limitleri</h2>
          <p className="text-gray-500 text-xs mt-1">
            Kayıt → PostgreSQL + Redis. Immunity, sinyal motoru ve OMS buradan okur.
            {source && <span className="text-gray-600"> Kaynak: {source}</span>}
            {updatedAt && <span className="text-gray-600"> · {updatedAt}</span>}
          </p>
        </div>
        <span className="text-xs text-gray-500">
          Açık: {openCount} / {maxOpen} max
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 text-xs">
        {fields.map(({ key, label }) => (
          <label key={key} className="block space-y-1">
            <span className="text-gray-500">{label}</span>
            <input
              type="number"
              step="any"
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1.5 text-white font-mono"
              value={form[key]}
              onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
            />
          </label>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="px-4 py-2 rounded-lg bg-orange-600 hover:bg-orange-500 text-white text-xs font-bold disabled:opacity-50"
        >
          {busy ? 'Kaydediliyor…' : 'Kaydet ve uygula'}
        </button>
        <button
          type="button"
          onClick={load}
          className="px-3 py-2 rounded-lg border border-gray-600 text-gray-400 text-xs hover:bg-gray-800"
        >
          Yenile
        </button>
      </div>

      {msg && (
        <p className="text-green-400 text-xs bg-green-950/30 border border-green-800/40 rounded px-3 py-2">
          {msg}
        </p>
      )}
      {err && (
        <p className="text-red-400 text-xs bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
          {err}
        </p>
      )}
    </section>
  )
}
