'use client'
import { useEffect, useState, useCallback, useRef } from 'react'

interface SvcInfo { name: string; label: string; status: 'ok' | 'warn' | 'error' | 'unknown'; detail: string }

interface SystemData {
  overall_status: 'healthy' | 'degraded' | 'critical'
  status_counts: Record<string, number>
  services: Record<string, SvcInfo>
  pipeline: {
    feature_count: number; signal_count: number; agent_count: number; context_count: number
    signal_freshness_sec: number | null; feature_freshness_sec: number | null
    ws_status: { status: string; symbols?: number } | null
  }
  ai_learning: {
    neat: { generation: number; best_fitness: number; genome_count: number; species_count: number } | null
    genome_count: number
    best_genome: Record<string, unknown> | null
    agent_last_run_sec: number | null
    agent_verdict_count: number
    shadow_best: Record<string, unknown> | null
    shadow_total: number
    ml_model: { version: number; n_samples: number; val_accuracy: number; top_features: [string, number][] } | null
    rl_active: boolean
  }
  market: { regime: string | null; crisis_level: number; fear_greed: { value: number; classification: string } | null; vix: number | null }
  positions: { open_count: number; daily_pnl: number; immunity_halted: boolean; recent_trades: Record<string, unknown>[] }
  activity: Record<string, unknown>[]
  server_time: number
}

interface AILearningData {
  signal_distribution: { long: number; short: number; flat: number; total: number }
  recent_signals: { symbol: string; direction: string; confidence: number; regime: string; ml_score?: number }[]
  agent_weights: { name: string; label: string; weight: number }[]
  sample_votes: { agent: string; signal: string; confidence: number }[]
  ml_model: { version: number; n_samples: number; val_accuracy: number; top_features: [string, number][] } | null
  rl_active: boolean
  last_run_sec: number | null
  neat_log: Record<string, unknown>[]
  activity_log: Record<string, unknown>[]
  sampled_symbols: number
}

const OVERALL_CFG = {
  healthy:  { color: 'text-green-400',  bg: 'bg-green-900/20 border-green-700/40',   dot: 'bg-green-400',              label: 'TÜM SİSTEMLER SAĞLIKLI', icon: '✓' },
  degraded: { color: 'text-yellow-400', bg: 'bg-yellow-900/20 border-yellow-700/40', dot: 'bg-yellow-400 animate-pulse', label: 'BAZI SERVİSLER UYARIDA',  icon: '⚠' },
  critical: { color: 'text-red-400',    bg: 'bg-red-900/20 border-red-700/40',       dot: 'bg-red-500 animate-pulse',   label: 'KRİTİK SORUN MEVCUT',    icon: '✗' },
}
const SVC_CFG = {
  ok:      { ring: 'border-green-800/40 bg-green-950/20',   dot: 'bg-green-400',               txt: 'text-green-400',  badge: 'bg-green-900/40 text-green-400 border-green-700/50' },
  warn:    { ring: 'border-yellow-800/40 bg-yellow-950/20', dot: 'bg-yellow-400 animate-pulse', txt: 'text-yellow-400', badge: 'bg-yellow-900/30 text-yellow-400 border-yellow-700/50' },
  error:   { ring: 'border-red-800/50 bg-red-950/20',       dot: 'bg-red-500 animate-pulse',   txt: 'text-red-400',   badge: 'bg-red-900/30 text-red-400 border-red-700/50' },
  unknown: { ring: 'border-gray-800/40 bg-gray-800/10',     dot: 'bg-gray-600',                txt: 'text-gray-500',  badge: 'bg-gray-800/50 text-gray-500 border-gray-700/40' },
}
const CRISIS_LABEL = ['Normal', 'Dikkat', 'Uyarı', 'Alarm', 'KRİZ']
const CRISIS_COLOR = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-500']
const REGIME_COLOR: Record<string, string> = {
  trending_up: 'text-green-400', trending_down: 'text-red-400',
  ranging: 'text-blue-400', volatile: 'text-yellow-400',
}
const DIR_COLOR: Record<string, string> = { long: 'text-green-400', short: 'text-red-400', flat: 'text-gray-500' }
const DIR_BG:    Record<string, string> = { long: 'bg-green-900/30 border-green-700/50', short: 'bg-red-900/30 border-red-700/50', flat: 'bg-gray-800/50 border-gray-700/40' }

function fmtSec(s: number | null): string {
  if (s == null) return '—'
  if (s < 60) return `${s}s önce`
  if (s < 3600) return `${Math.floor(s / 60)}dk önce`
  return `${Math.floor(s / 3600)}sa önce`
}

function ServiceCard({ s, onRestart }: { s: SvcInfo; onRestart?: (name: string) => Promise<void> }) {
  const c = SVC_CFG[s.status]
  const lbl = s.status === 'ok' ? 'OK' : s.status === 'warn' ? 'UYARI' : s.status === 'error' ? 'HATA' : '?'
  const [restarting, setRestarting] = useState(false)
  const [restartMsg, setRestartMsg] = useState<string | null>(null)
  const canRestart = (s.status === 'error' || s.status === 'warn') && !!onRestart

  async function handleRestart() {
    if (!onRestart || restarting) return
    setRestarting(true)
    setRestartMsg(null)
    try {
      await onRestart(s.name)
      setRestartMsg('Yeniden başlatılıyor...')
      setTimeout(() => setRestartMsg(null), 5000)
    } catch {
      setRestartMsg('Hata')
      setTimeout(() => setRestartMsg(null), 4000)
    } finally {
      setRestarting(false)
    }
  }

  return (
    <div className={`rounded-lg border p-3 ${c.ring}`}>
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`w-2 h-2 rounded-full shrink-0 mt-0.5 ${c.dot}`} />
          <span className="text-white text-xs font-semibold truncate">{s.label}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {canRestart && (
            <button
              onClick={handleRestart}
              disabled={restarting}
              className="text-[10px] px-1.5 py-0.5 rounded border font-bold
                bg-blue-900/40 text-blue-300 border-blue-700/50
                hover:bg-blue-800/60 active:scale-95 transition-all
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {restarting ? '⟳' : '↺ YENİDEN'}
            </button>
          )}
          <span className={`text-[10px] px-1.5 py-0.5 rounded border font-bold ${c.badge}`}>{lbl}</span>
        </div>
      </div>
      <p className="text-gray-500 text-[11px] leading-snug pl-3.5">{s.detail}</p>
      {restartMsg && (
        <p className="text-blue-400 text-[10px] pl-3.5 mt-1">{restartMsg}</p>
      )}
    </div>
  )
}

function PipeBar({ label, count, target, fresh, color }: { label: string; count: number; target: number; fresh: number | null; color: string }) {
  const pct = Math.min(100, (count / Math.max(target, 1)) * 100)
  const stale = fresh != null && fresh > 300
  const barColor = count >= target ? color.replace('text-', 'bg-') : count > 0 ? 'bg-yellow-500' : 'bg-red-500'
  const valColor = count >= target ? color : count > 0 ? 'text-yellow-400' : 'text-red-400'
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <div className="flex items-center gap-2">
          {fresh != null && <span className={`text-[10px] font-mono ${stale ? 'text-yellow-400' : 'text-green-400'}`}>{fmtSec(fresh)}</span>}
          <span className={`font-mono font-bold ${valColor}`}>{count.toLocaleString()}</span>
        </div>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function FitnessBar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-3 bg-gray-800 rounded-full overflow-hidden">
        <div className="h-full bg-gradient-to-r from-purple-600 to-green-500 rounded-full transition-all duration-700" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-green-400 font-mono font-bold text-sm w-16 text-right">{value.toFixed(4)}</span>
    </div>
  )
}

function LogLine({ e }: { e: Record<string, unknown> }) {
  const t = e.type as string | undefined
  const ts = e.time as number | undefined
  const ago = ts ? (() => {
    const s = Math.floor(Date.now() / 1000 - ts)
    if (s < 60) return `${s}s`
    if (s < 3600) return `${Math.floor(s / 60)}dk`
    return `${Math.floor(s / 3600)}sa`
  })() : '—'

  const dir = e.direction as string | undefined
  let icon = '◉', textColor = 'text-gray-500'
  if (t === 'scan_summary') { icon = '⟳'; textColor = 'text-blue-400' }
  else if (t === 'signal' && dir === 'long')  { icon = '▲'; textColor = 'text-green-400' }
  else if (t === 'signal' && dir === 'short') { icon = '▼'; textColor = 'text-red-400' }
  else if (t === 'regime_change') { icon = '⇄'; textColor = 'text-purple-400' }
  else if (t === 'trade_open')    { icon = '◆'; textColor = 'text-yellow-400' }
  else if (t === 'trade_close')   { icon = '◇'; textColor = 'text-cyan-400' }
  else if (t === 'error')         { icon = '✗'; textColor = 'text-red-400' }
  else if (t === 'warning')       { icon = '⚠'; textColor = 'text-yellow-400' }
  else if (t === 'rsi_alert')     { icon = '⚡'; textColor = 'text-orange-400' }

  return (
    <div className="flex items-start gap-2 px-3 py-1.5 hover:bg-gray-800/30 text-[11px] font-mono border-b border-gray-800/30">
      <span className={`shrink-0 mt-0.5 ${textColor}`}>{icon}</span>
      <div className="flex-1 min-w-0">
        {e.symbol != null && <span className="text-white font-bold mr-1">{String(e.symbol)}</span>}
        {t === 'scan_summary'
          ? <span className="text-blue-300">{String(e.total ?? '')} coin · ▲{String(e.long ?? '')} ▼{String(e.short ?? '')} ={String(e.flat ?? '')}</span>
          : t === 'signal'
          ? <span className={dir === 'long' ? 'text-green-300' : 'text-red-300'}>
              {String(dir ?? '').toUpperCase()} {Math.round(((e.confidence as number) ?? 0) * 100)}% · {String(e.regime ?? '')}
            </span>
          : t === 'regime_change'
          ? <span className="text-purple-300">rejim → {String(e.regime ?? '')}</span>
          : t === 'trade_open'
          ? <span className="text-yellow-300">AÇILIYOR {String(e.direction ?? '')} @ ${Number(e.price ?? 0).toFixed(2)}</span>
          : t === 'trade_close'
          ? <span className="text-cyan-300">KAPANIYOR pnl=${Number(e.pnl ?? 0).toFixed(2)}</span>
          : t === 'rsi_alert'
          ? <span className="text-orange-300">RSI {Number(e.rsi ?? 0).toFixed(1)}</span>
          : <span className="text-gray-400">{String(t ?? '')} {e.message ? String(e.message) : ''}</span>}
      </div>
      <span className="text-gray-700 shrink-0">{ago}</span>
    </div>
  )
}

function SignalDistBar({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`w-10 text-right font-bold ${color}`}>{pct}%</span>
      <div className="flex-1 h-2.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-700 ${color.replace('text-', 'bg-')}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-500 w-12">{label}</span>
    </div>
  )
}

export default function SystemPage() {
  const [data, setData]     = useState<SystemData | null>(null)
  const [ai, setAi]         = useState<AILearningData | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [logFilter, setLogFilter] = useState<string>('all')
  const fetchRef = useRef<() => Promise<void>>()

  const fetchAll = useCallback(async () => {
    try {
      const [sys, aiData] = await Promise.all([
        fetch('/api/system').then(r => r.json()),
        fetch('/api/ai-learning').then(r => r.json()),
      ])
      setData(sys)
      setAi(aiData)
      setLastUpdate(new Date().toLocaleTimeString('tr-TR'))
    } catch { } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchRef.current = fetchAll }, [fetchAll])

  const handleRestart = useCallback(async (serviceName: string) => {
    const res = await fetch(`/api/admin/restart/${serviceName}`, { method: 'POST' })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.error ?? 'Restart failed')
    }
    // Refresh after 3s to show new status
    setTimeout(() => fetchRef.current?.(), 3000)
    setTimeout(() => fetchRef.current?.(), 8000)
  }, [])

  useEffect(() => {
    fetchAll()
    const t = setInterval(fetchAll, 5000)
    return () => clearInterval(t)
  }, [fetchAll])

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400 text-xl">⚡</span>
      <span className="text-sm">Sistem durumu yükleniyor...</span>
    </div>
  )
  if (!data || 'error' in data) return (
    <div className="text-red-400 text-sm p-8 text-center">Sistem verisi alınamadı — Redis bağlantısı kontrol edin</div>
  )

  const overall   = OVERALL_CFG[data.overall_status]
  const services  = Object.values(data.services)
  const sysAi     = data.ai_learning
  const pipe      = data.pipeline
  const mkt       = data.market
  const pos       = data.positions
  const okCount   = services.filter(s => s.status === 'ok').length
  const warnCount = data.status_counts.warn ?? 0
  const errCount  = data.status_counts.error ?? 0

  // Log filtering
  const logEntries = ai?.activity_log ?? data.activity
  const filteredLogs = logFilter === 'all' ? logEntries
    : logFilter === 'trade' ? logEntries.filter(e => ['trade_open', 'trade_close'].includes(String((e as Record<string, unknown>).type ?? '')))
    : logFilter === 'signal' ? logEntries.filter(e => String((e as Record<string, unknown>).type ?? '') === 'signal')
    : logFilter === 'error' ? logEntries.filter(e => ['error', 'warning'].includes(String((e as Record<string, unknown>).type ?? '')))
    : logEntries

  return (
    <div className="space-y-4">

      {/* ── Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-white font-bold text-base">🖥 Sistem &amp; AI İzleme</h1>
          <p className="text-gray-500 text-xs mt-0.5">Tüm servisler, yapay zeka öğrenmesi ve canlı loglar</p>
        </div>
        <span className="text-xs text-gray-600">{lastUpdate} · 5s otomatik</span>
      </div>

      {/* ── Status Banner ── */}
      <div className={`rounded-xl border p-4 flex items-center gap-4 ${overall.bg}`}>
        <div className={`w-12 h-12 rounded-full flex items-center justify-center text-2xl font-black shrink-0 ${overall.color} border-2 ${overall.bg}`}>
          {overall.icon}
        </div>
        <div className="flex-1 min-w-0">
          <p className={`font-black text-lg ${overall.color}`}>{overall.label}</p>
          <p className="text-gray-400 text-xs mt-0.5">
            <span className="text-green-400 font-bold">{okCount}</span> normal ·
            {warnCount > 0 && <> <span className="text-yellow-400 font-bold">{warnCount}</span> uyarı ·</>}
            {errCount  > 0 && <> <span className="text-red-400 font-bold animate-pulse">{errCount}</span> hata ·</>}
            {' '}{pipe.feature_count} coin izleniyor
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className={`text-xl font-black ${pipe.ws_status?.status === 'CONNECTED' ? 'text-green-400' : 'text-gray-500'}`}>
            {pipe.ws_status?.status === 'CONNECTED' ? '🟢 CANLI' : '🔴 OFFLİNE'}
          </p>
          <p className="text-gray-500 text-xs">{pipe.ws_status?.symbols ?? 0} coin stream</p>
        </div>
      </div>

      {/* ── Quick Metrics ── */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {[
          { l: 'Feature',    v: pipe.feature_count,       c: 'text-blue-400',   s: 'coin' },
          { l: 'Sinyal',     v: pipe.signal_count,        c: 'text-orange-400', s: 'aktif' },
          { l: 'AI Karar',   v: sysAi.agent_verdict_count, c: 'text-purple-400', s: 'verdict' },
          { l: 'Genom',      v: sysAi.genome_count,       c: 'text-green-400',  s: 'NEAT' },
          { l: 'Pozisyon',   v: pos.open_count,           c: pos.open_count > 0 ? 'text-yellow-400' : 'text-gray-600', s: 'açık' },
          { l: 'Günlük P&L', v: `${pos.daily_pnl >= 0 ? '+' : ''}$${pos.daily_pnl.toFixed(2)}`, c: pos.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400', s: 'realized', str: true },
        ].map(m => (
          <div key={m.l} className="bg-gray-900 border border-gray-800 rounded-lg p-3 text-center">
            <p className="text-gray-600 text-[10px] uppercase tracking-wider">{m.l}</p>
            <p className={`text-xl font-black leading-tight ${m.c}`}>
              {m.str ? m.v : typeof m.v === 'number' ? m.v.toLocaleString() : m.v}
            </p>
            <p className="text-gray-700 text-[10px]">{m.s}</p>
          </div>
        ))}
      </div>

      {/* ── Services + AI Learning side by side ── */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">

        {/* Service Grid */}
        <div className="xl:col-span-3 bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-white font-semibold text-sm">Servis Sağlığı</h2>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="text-green-400">✓ {data.status_counts.ok ?? 0}</span>
              {warnCount > 0 && <span className="text-yellow-400">⚠ {warnCount}</span>}
              {errCount  > 0 && <span className="text-red-400 animate-pulse">✗ {errCount}</span>}
              {(data.status_counts.unknown ?? 0) > 0 && <span className="text-gray-500">? {data.status_counts.unknown}</span>}
            </div>
          </div>
          <div className="p-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
            {services.map(s => <ServiceCard key={s.name} s={s} onRestart={handleRestart} />)}
          </div>
        </div>

        {/* AI Learning Panel */}
        <div className="xl:col-span-2 flex flex-col gap-4">

          {/* NEAT Evolution */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="text-purple-400 font-semibold text-sm">🧬 NEAT Evrimi</h2>
              <p className="text-gray-600 text-[11px] mt-0.5">Fitness = Sharpe × WR × (1−DD) · Her 3 saatte nesil</p>
            </div>
            <div className="p-4 space-y-4">
              {sysAi.neat ? (
                <>
                  <div>
                    <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1.5">En İyi Fitness</p>
                    <FitnessBar value={sysAi.neat.best_fitness} />
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    {[
                      { l: 'Nesil', v: sysAi.neat.generation, c: 'text-white' },
                      { l: 'Genom', v: sysAi.neat.genome_count, c: 'text-purple-400' },
                      { l: 'Tür',   v: sysAi.neat.species_count, c: 'text-blue-400' },
                    ].map(m => (
                      <div key={m.l} className="bg-gray-800/50 rounded-lg p-2">
                        <p className="text-gray-500 text-[10px]">{m.l}</p>
                        <p className={`font-bold text-lg ${m.c}`}>{m.v}</p>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="text-center py-4">
                  <p className="text-gray-600 text-2xl mb-2">🧬</p>
                  <p className="text-gray-400 text-sm font-semibold">
                    {sysAi.genome_count > 0 ? `${sysAi.genome_count} Genom Mevcut` : 'Evrim Başlamadı'}
                  </p>
                  <p className="text-gray-600 text-xs mt-1">neat_evolution servisi ilk nesli hazırlıyor</p>
                </div>
              )}
            </div>
          </div>

          {/* ML Model + RL Agent */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-blue-400 font-semibold text-sm">🧠 ML Model &amp; RL Agent</h2>
              <div className="flex items-center gap-2">
                {sysAi.rl_active !== undefined && (
                  <span className={`text-[10px] px-2 py-0.5 rounded border font-bold ${sysAi.rl_active ? 'bg-green-900/30 border-green-700/50 text-green-400' : 'bg-gray-800/50 border-gray-700/40 text-gray-500'}`}>
                    PPO {sysAi.rl_active ? 'AKTIF' : 'BEKLIYOR'}
                  </span>
                )}
              </div>
            </div>
            <div className="p-4 space-y-3">
              {sysAi.ml_model ? (
                <>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="bg-gray-800/50 rounded-lg p-2">
                      <p className="text-gray-500 text-[10px]">Versiyon</p>
                      <p className="text-blue-400 font-bold text-lg">v{sysAi.ml_model.version}</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-2">
                      <p className="text-gray-500 text-[10px]">Örnekler</p>
                      <p className="text-white font-bold text-lg">{sysAi.ml_model.n_samples.toLocaleString()}</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-2">
                      <p className="text-gray-500 text-[10px]">Val Acc</p>
                      <p className={`font-bold text-lg ${sysAi.ml_model.val_accuracy >= 0.6 ? 'text-green-400' : sysAi.ml_model.val_accuracy >= 0.5 ? 'text-yellow-400' : 'text-red-400'}`}>
                        {(sysAi.ml_model.val_accuracy * 100).toFixed(1)}%
                      </p>
                    </div>
                  </div>
                  <div>
                    <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all duration-500 ${sysAi.ml_model.val_accuracy >= 0.6 ? 'bg-green-500' : sysAi.ml_model.val_accuracy >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'}`}
                        style={{ width: `${Math.min(100, sysAi.ml_model.val_accuracy * 100)}%` }} />
                    </div>
                    <div className="flex justify-between text-[10px] text-gray-600 mt-1">
                      <span>0%</span><span>60% hedef</span><span>100%</span>
                    </div>
                  </div>
                  {sysAi.ml_model.top_features.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-gray-500 text-[10px] uppercase tracking-wider">Top Features</p>
                      {sysAi.ml_model.top_features.slice(0, 5).map(([feat, imp]) => (
                        <div key={feat} className="flex items-center gap-2 text-[10px]">
                          <span className="text-gray-400 w-32 truncate font-mono">{feat}</span>
                          <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                            <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.min(100, imp * 100)}%` }} />
                          </div>
                          <span className="text-blue-400 w-8 text-right font-mono">{(imp * 100).toFixed(1)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center py-3">
                  <p className="text-gray-600 text-xl mb-1">🧠</p>
                  <p className="text-gray-500 text-xs">İlk 50 işlem tamamlanana kadar</p>
                  <p className="text-gray-600 text-[10px]">heuristic mod aktif</p>
                </div>
              )}
            </div>
          </div>

          {/* Agent & Shadow */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="text-orange-400 font-semibold text-sm">🤖 Agent &amp; Shadow</h2>
            </div>
            <div className="p-4 space-y-3">
              <div className="flex items-center justify-between text-xs bg-gray-800/40 rounded-lg px-3 py-2">
                <div>
                  <p className="text-gray-400">Agent son çalışma</p>
                  <p className={`font-bold ${sysAi.agent_last_run_sec != null && sysAi.agent_last_run_sec < 120 ? 'text-green-400' : sysAi.agent_last_run_sec != null ? 'text-yellow-400' : 'text-gray-500'}`}>
                    {fmtSec(sysAi.agent_last_run_sec)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-gray-400">Aktif verdict</p>
                  <p className="text-purple-400 font-bold">{sysAi.agent_verdict_count} coin</p>
                </div>
              </div>
              {sysAi.shadow_total > 0 && sysAi.shadow_best ? (
                <div className="space-y-2 text-xs">
                  <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                    <div>
                      <p className="text-gray-400">En İyi Shadow Sharpe</p>
                      <p className={`font-bold ${((sysAi.shadow_best.sharpe as number) ?? 0) >= 1.5 ? 'text-green-400' : 'text-orange-400'}`}>
                        {Number(sysAi.shadow_best.sharpe ?? 0).toFixed(2)} <span className="text-gray-600 font-normal">/ 1.5</span>
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-gray-400">İşlem</p>
                      <p className="text-gray-300 font-bold">{Number(sysAi.shadow_best.trades ?? 0)} / 100</p>
                    </div>
                  </div>
                  <div>
                    <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${Math.min(100, Number(sysAi.shadow_best.trades ?? 0))}%` }} />
                    </div>
                    <div className="flex justify-between text-[10px] text-gray-600 mt-1">
                      <span>0</span><span>100 işlem gerekli</span>
                    </div>
                  </div>
                  {(sysAi.shadow_best.promotion_ready as boolean) && (
                    <div className="bg-yellow-900/30 border border-yellow-600/50 rounded-lg p-2 text-center">
                      <p className="text-yellow-400 font-black text-sm animate-pulse">🚀 CANLIYA TERFİ HAZIR!</p>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-center text-xs text-gray-600 py-2">
                  Shadow {sysAi.shadow_total > 0 ? `${sysAi.shadow_total} strateji` : 'başlamadı'} · 100 kağıt işlem bekleniyor
                </p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── AI LEARNING MONITOR ── */}
      {ai && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-green-400 font-semibold text-sm">🧠 Yapay Zeka Şu An Ne Öğreniyor?</h2>
            <span className="text-[11px] text-gray-600">{ai.sampled_symbols} coin örneklendi · {fmtSec(ai.last_run_sec)}</span>
          </div>
          <div className="p-4 grid grid-cols-1 lg:grid-cols-3 gap-4">

            {/* Signal Distribution */}
            <div className="space-y-3">
              <p className="text-gray-400 text-xs font-semibold uppercase tracking-wider">Anlık Sinyal Dağılımı</p>
              <SignalDistBar label="LONG"  pct={ai.signal_distribution.long}  color="text-green-400" />
              <SignalDistBar label="SHORT" pct={ai.signal_distribution.short} color="text-red-400" />
              <SignalDistBar label="FLAT"  pct={ai.signal_distribution.flat}  color="text-gray-400" />
              <p className="text-gray-600 text-[10px]">{ai.signal_distribution.total} sembol analiz edildi</p>
            </div>

            {/* Agent Weights */}
            <div className="space-y-2">
              <p className="text-gray-400 text-xs font-semibold uppercase tracking-wider">Ajan Ağırlıkları (Öğrenilmiş)</p>
              {ai.agent_weights.map(a => (
                <div key={a.name} className="flex items-center gap-2 text-[11px]">
                  <span className="text-gray-400 w-20 truncate">{a.label}</span>
                  <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                    <div className="h-full bg-indigo-500 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (a.weight / 2) * 100)}%` }} />
                  </div>
                  <span className="text-indigo-400 font-mono w-8 text-right">{a.weight.toFixed(2)}</span>
                </div>
              ))}
            </div>

            {/* Recent Non-Flat Signals */}
            <div className="space-y-2">
              <p className="text-gray-400 text-xs font-semibold uppercase tracking-wider">Aktif Sinyaller (Flat Değil)</p>
              {ai.recent_signals.length === 0 ? (
                <div className="bg-gray-800/40 rounded-lg p-3 text-center">
                  <p className="text-gray-600 text-xs">Şu an tüm sinyaller FLAT</p>
                  <p className="text-gray-700 text-[10px] mt-1">Piyasa yön bekleniyor</p>
                </div>
              ) : (
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {ai.recent_signals.map((s, i) => (
                    <a key={i} href={`/coin/${s.symbol}`}
                      className="flex items-center justify-between px-2 py-1.5 rounded bg-gray-800/40 hover:bg-gray-800/70 transition-colors gap-1">
                      <span className="text-white text-xs font-bold w-14 truncate">{s.symbol.replace('USDT', '')}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border font-bold ${DIR_BG[s.direction] ?? ''} ${DIR_COLOR[s.direction] ?? ''}`}>
                        {s.direction.toUpperCase()}
                      </span>
                      <span className="text-gray-400 text-[10px] font-mono">{Math.round(s.confidence * 100)}%</span>
                      {s.ml_score != null && s.ml_score !== 0 && (
                        <span className={`text-[10px] font-mono ${s.ml_score > 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ML{s.ml_score > 0 ? '+' : ''}{s.ml_score.toFixed(2)}
                        </span>
                      )}
                    </a>
                  ))}
                </div>
              )}

              {/* Sample vote breakdown */}
              {ai.sample_votes.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-800/60">
                  <p className="text-gray-600 text-[10px] mb-1.5">BTC Ajan Oyları:</p>
                  <div className="flex flex-wrap gap-1">
                    {ai.sample_votes.map((v, i) => (
                      <span key={i}
                        className={`text-[10px] px-1.5 py-0.5 rounded border ${v.signal === 'long' ? 'bg-green-900/30 border-green-800/40 text-green-400' : v.signal === 'short' ? 'bg-red-900/30 border-red-800/40 text-red-400' : 'bg-gray-800/50 border-gray-700/40 text-gray-500'}`}>
                        {String(v.agent).replace('agent_', '')} {Math.round(v.confidence * 100)}%
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Pipeline + Market ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-4">
          <h2 className="text-blue-400 font-semibold text-sm">📡 Veri Pipeline</h2>
          <PipeBar label="Feature Engine"  count={pipe.feature_count} target={400} fresh={pipe.feature_freshness_sec} color="text-blue-400" />
          <PipeBar label="Signal Engine"   count={pipe.signal_count}  target={400} fresh={pipe.signal_freshness_sec}  color="text-orange-400" />
          <PipeBar label="Agent Verdicts"  count={pipe.agent_count}   target={400} fresh={null} color="text-purple-400" />
          <PipeBar label="Context Engine"  count={pipe.context_count} target={400} fresh={null} color="text-cyan-400" />
          <div className="pt-3 border-t border-gray-800/60 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${pipe.ws_status?.status === 'CONNECTED' ? 'bg-green-400 animate-pulse' : 'bg-red-500'}`} />
              <span className="text-gray-400">Binance USDM WebSocket</span>
            </div>
            <span className={`font-bold ${pipe.ws_status?.status === 'CONNECTED' ? 'text-green-400' : 'text-red-400'}`}>
              {pipe.ws_status?.status ?? 'UNKNOWN'} · {pipe.ws_status?.symbols ?? 0} coin
            </span>
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-4">
          <h2 className="text-cyan-400 font-semibold text-sm">🌐 Market Durumu</h2>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-800/50 rounded-xl p-3 text-center">
              <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-2">Piyasa Rejimi</p>
              <p className={`font-bold text-sm ${REGIME_COLOR[mkt.regime ?? ''] ?? 'text-gray-400'}`}>
                {mkt.regime?.replace(/_/g, ' ') ?? '—'}
              </p>
            </div>
            <div className="bg-gray-800/50 rounded-xl p-3 text-center">
              <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">Kriz Seviyesi</p>
              <p className={`font-black text-2xl ${CRISIS_COLOR[mkt.crisis_level] ?? 'text-green-400'}`}>L{mkt.crisis_level}</p>
              <p className={`text-[11px] ${CRISIS_COLOR[mkt.crisis_level] ?? 'text-green-400'}`}>{CRISIS_LABEL[mkt.crisis_level] ?? 'Normal'}</p>
            </div>
            <div className="bg-gray-800/50 rounded-xl p-3 text-center">
              <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">Fear &amp; Greed</p>
              {mkt.fear_greed ? (
                <>
                  <p className={`font-black text-2xl ${mkt.fear_greed.value < 25 ? 'text-red-400' : mkt.fear_greed.value < 45 ? 'text-orange-400' : 'text-green-400'}`}>
                    {mkt.fear_greed.value}
                  </p>
                  <p className="text-gray-500 text-[10px]">{mkt.fear_greed.classification}</p>
                </>
              ) : <p className="text-gray-600">—</p>}
            </div>
            <div className="bg-gray-800/50 rounded-xl p-3 text-center">
              <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">VIX</p>
              {mkt.vix != null ? (
                <>
                  <p className={`font-black text-2xl ${mkt.vix > 40 ? 'text-red-400 animate-pulse' : mkt.vix > 25 ? 'text-orange-400' : 'text-green-400'}`}>
                    {mkt.vix.toFixed(1)}
                  </p>
                  <p className={`text-[10px] ${mkt.vix > 40 ? 'text-red-400' : mkt.vix > 25 ? 'text-orange-400' : 'text-gray-500'}`}>
                    {mkt.vix > 40 ? 'EXTREME' : mkt.vix > 25 ? 'ELEVATED' : 'NORMAL'}
                  </p>
                </>
              ) : <p className="text-gray-600">—</p>}
            </div>
          </div>
          {pos.immunity_halted && (
            <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-3 text-center">
              <p className="text-red-400 font-black text-sm animate-pulse">🛡 TRADING DURDURULDU</p>
              <p className="text-gray-400 text-xs mt-1">Günlük kayıp limiti — immunity sistemi devrede</p>
            </div>
          )}
        </div>
      </div>

      {/* ── LIVE LOGS ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between gap-3">
          <h2 className="text-white font-semibold text-sm shrink-0">📋 Canlı Sistem Logları</h2>
          <div className="flex items-center gap-1 flex-wrap">
            {[
              { key: 'all',    label: 'Tümü' },
              { key: 'signal', label: '📶 Sinyal' },
              { key: 'trade',  label: '💼 Trade' },
              { key: 'error',  label: '🔴 Hata' },
            ].map(f => (
              <button key={f.key} onClick={() => setLogFilter(f.key)}
                className={`text-[11px] px-2 py-0.5 rounded border transition-colors ${logFilter === f.key ? 'bg-orange-500/20 border-orange-500/40 text-orange-400' : 'border-gray-700 text-gray-500 hover:text-white'}`}>
                {f.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-gray-600 shrink-0">{filteredLogs.length} kayıt</span>
        </div>
        {filteredLogs.length === 0 ? (
          <div className="p-6 text-center">
            <p className="text-gray-500 text-xs">Log yok — signal engine ısınıyor (~60s)</p>
          </div>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            {filteredLogs.map((ev, i) => (
              <LogLine key={i} e={ev as Record<string, unknown>} />
            ))}
          </div>
        )}
      </div>

      {/* ── Positions ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-orange-400 font-semibold text-sm mb-3">💼 Pozisyon Durumu</h2>
        {pos.open_count === 0 ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3 bg-blue-950/30 border border-blue-800/30 rounded-lg p-3 text-xs">
              <span className="text-blue-400 text-lg shrink-0">ℹ</span>
              <div>
                <p className="text-blue-300 font-semibold">Açık Pozisyon Yok — Bekleme Modunda</p>
                <p className="text-gray-500 mt-1">
                  Shadow sistem 100 kağıt işlem tamamlayana kadar OMS canlı pozisyon açmaz.
                  Şu an {pipe.signal_count} sinyal aktif.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs text-center">
              {[
                { l: 'Min Güven', v: '55%' },
                { l: 'Maks Pozisyon', v: '3 adet' },
                { l: 'Maks Kaldıraç', v: '3×' },
              ].map(m => (
                <div key={m.l} className="bg-gray-800/50 rounded-lg p-2">
                  <p className="text-gray-600">{m.l}</p>
                  <p className="text-white font-bold">{m.v}</p>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>Günlük P&L:</span>
              <span className={`font-mono font-bold ${pos.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {pos.daily_pnl >= 0 ? '+' : ''}${pos.daily_pnl.toFixed(2)}
              </span>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between bg-green-950/20 border border-green-800/30 rounded-lg px-3 py-2 text-xs">
            <span className="text-green-400 font-semibold">{pos.open_count} Açık Pozisyon</span>
            <a href="/positions" className="text-orange-400 hover:text-orange-300">Detaylar →</a>
          </div>
        )}
      </div>

      {/* ── How it learns ── */}
      <div className="bg-gray-900/60 border border-gray-800/60 rounded-xl p-4">
        <h2 className="text-white font-semibold text-sm mb-3">🎓 Yapay Zeka Nasıl Öğreniyor?</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          {[
            { icon: '🧬', title: 'NEAT Evrimi', color: 'border-purple-800/40', desc: 'Her 3 saatte genomlar üzerinde mutasyon ve çaprazlama. Fitness = Sharpe × WR × (1-MaxDD). En iyi genomlar hayatta kalır.' },
            { icon: '🤖', title: '9 Ajan Tartışması', color: 'border-orange-800/40', desc: 'Boğa, Ayı, Teknik, Haber, Makro, Zincir-üstü, Risk, Nötr ajanları her coin için tartışır. Zamanla doğru tahmin yapan ajanların ağırlığı artar.' },
            { icon: '👻', title: 'Shadow Backtest', color: 'border-indigo-800/40', desc: '3 paralel kağıt-işlem evreni. 100 işlem + Sharpe ≥1.5 + WR ≥52% + DD <10% sağlanırsa canlıya terfi eder.' },
            { icon: '📐', title: 'PPO (RL Agent)', color: 'border-green-800/40', desc: '500K adım gymnasium ortamında eğitilen PPO. Pozisyon boyutu ve giriş zamanlamasını optimize eder.' },
          ].map(item => (
            <div key={item.title} className={`rounded-lg border bg-gray-800/30 p-3 ${item.color}`}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xl">{item.icon}</span>
                <span className="text-white font-semibold">{item.title}</span>
              </div>
              <p className="text-gray-500 leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </div>

    </div>
  )
}
