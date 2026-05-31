'use client'
import { useEffect, useState, useCallback } from 'react'

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
  }
  market: { regime: string | null; crisis_level: number; fear_greed: { value: number; classification: string } | null; vix: number | null }
  positions: { open_count: number; daily_pnl: number; immunity_halted: boolean; recent_trades: Record<string, unknown>[] }
  activity: Record<string, unknown>[]
  server_time: number
}

const OVERALL_CFG = {
  healthy:  { color: 'text-green-400',  bg: 'bg-green-900/20 border-green-700/40',  dot: 'bg-green-400',             label: 'TÜM SİSTEMLER SAĞLIKLI', icon: '✓' },
  degraded: { color: 'text-yellow-400', bg: 'bg-yellow-900/20 border-yellow-700/40', dot: 'bg-yellow-400 animate-pulse', label: 'BAZI SERVİSLER UYARIDA',   icon: '⚠' },
  critical: { color: 'text-red-400',    bg: 'bg-red-900/20 border-red-700/40',       dot: 'bg-red-500 animate-pulse',  label: 'KRİTİK SORUN MEVCUT',     icon: '✗' },
}

const SVC_CFG = {
  ok:      { ring: 'border-green-800/40 bg-green-950/20',  dot: 'bg-green-400',              txt: 'text-green-400',  badge: 'bg-green-900/40 text-green-400 border-green-700/50' },
  warn:    { ring: 'border-yellow-800/40 bg-yellow-950/20', dot: 'bg-yellow-400 animate-pulse', txt: 'text-yellow-400', badge: 'bg-yellow-900/30 text-yellow-400 border-yellow-700/50' },
  error:   { ring: 'border-red-800/50 bg-red-950/20',      dot: 'bg-red-500 animate-pulse',  txt: 'text-red-400',   badge: 'bg-red-900/30 text-red-400 border-red-700/50' },
  unknown: { ring: 'border-gray-800/40 bg-gray-800/10',    dot: 'bg-gray-600',              txt: 'text-gray-500',  badge: 'bg-gray-800/50 text-gray-500 border-gray-700/40' },
}

const CRISIS_LABEL = ['Normal', 'Dikkat', 'Uyarı', 'Alarm', 'KRİZ']
const CRISIS_COLOR = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-500']
const REGIME_COLOR: Record<string, string> = {
  trending_up: 'text-green-400', trending_down: 'text-red-400',
  ranging: 'text-blue-400', volatile: 'text-yellow-400',
}

function fmtSec(s: number | null): string {
  if (s == null) return '—'
  if (s < 60) return `${s}s önce`
  if (s < 3600) return `${Math.floor(s / 60)}dk önce`
  return `${Math.floor(s / 3600)}sa önce`
}

function ServiceCard({ s }: { s: SvcInfo }) {
  const c = SVC_CFG[s.status]
  const statusLabel = s.status === 'ok' ? 'OK' : s.status === 'warn' ? 'UYARI' : s.status === 'error' ? 'HATA' : '?'
  return (
    <div className={`rounded-lg border p-3 ${c.ring}`}>
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`w-2 h-2 rounded-full shrink-0 mt-0.5 ${c.dot}`} />
          <span className="text-white text-xs font-semibold truncate">{s.label}</span>
        </div>
        <span className={`text-[10px] px-1.5 py-0.5 rounded border font-bold shrink-0 ${c.badge}`}>{statusLabel}</span>
      </div>
      <p className="text-gray-500 text-[11px] leading-snug pl-3.5">{s.detail}</p>
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
          {fresh != null && (
            <span className={`text-[10px] font-mono ${stale ? 'text-yellow-400' : 'text-green-400'}`}>{fmtSec(fresh)}</span>
          )}
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

export default function SystemPage() {
  const [data, setData] = useState<SystemData | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')

  const fetchData = useCallback(async () => {
    try {
      const d = await fetch('/api/system').then(r => r.json())
      setData(d)
      setLastUpdate(new Date().toLocaleTimeString('tr-TR'))
    } catch { } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 5000)
    return () => clearInterval(t)
  }, [fetchData])

  if (loading) return (
    <div className="flex items-center justify-center mt-32 gap-3 text-gray-500">
      <span className="animate-spin text-orange-400 text-xl">⚡</span>
      <span className="text-sm">Sistem durumu yükleniyor...</span>
    </div>
  )

  if (!data || 'error' in data) return (
    <div className="text-red-400 text-sm p-8 text-center">Sistem verisi alınamadı — Redis bağlantısı kontrol edin</div>
  )

  const overall = OVERALL_CFG[data.overall_status]
  const services = Object.values(data.services)
  const ai = data.ai_learning
  const pipe = data.pipeline
  const mkt = data.market
  const pos = data.positions

  const okCount = services.filter(s => s.status === 'ok').length
  const warnCount = data.status_counts.warn ?? 0
  const errCount  = data.status_counts.error ?? 0

  return (
    <div className="space-y-4">

      {/* ── Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-white font-bold text-base">🖥 Sistem Durumu</h1>
          <p className="text-gray-500 text-xs mt-0.5">Tüm servisler, yapay zeka ve pipeline — anlık izleme</p>
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
          { l: 'Feature',   v: pipe.feature_count,  c: 'text-blue-400',   s: 'coin' },
          { l: 'Sinyal',    v: pipe.signal_count,   c: 'text-orange-400', s: 'aktif' },
          { l: 'AI Karar',  v: ai.agent_verdict_count, c: 'text-purple-400', s: 'verdict' },
          { l: 'Genom',     v: ai.genome_count,     c: 'text-green-400',  s: 'NEAT' },
          { l: 'Pozisyon',  v: pos.open_count,      c: pos.open_count > 0 ? 'text-yellow-400' : 'text-gray-600', s: 'açık' },
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

      {/* ── Services + AI side by side ── */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">

        {/* Service Grid — 3 cols */}
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
            {services.map(s => <ServiceCard key={s.name} s={s} />)}
          </div>
        </div>

        {/* AI Learning — 2 cols */}
        <div className="xl:col-span-2 flex flex-col gap-4">

          {/* NEAT Evolution */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden flex-1">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="text-purple-400 font-semibold text-sm">🧬 NEAT Evrimi</h2>
              <p className="text-gray-600 text-[11px] mt-0.5">Fitness = Sharpe × WR × (1−DD) · Her 3 saatte bir nesil</p>
            </div>
            <div className="p-4 space-y-4">
              {ai.neat ? (
                <>
                  <div>
                    <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1.5">En İyi Fitness</p>
                    <FitnessBar value={ai.neat.best_fitness} />
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="bg-gray-800/50 rounded-lg p-2">
                      <p className="text-gray-500 text-[10px]">Nesil</p>
                      <p className="text-white font-bold text-lg">{ai.neat.generation}</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-2">
                      <p className="text-gray-500 text-[10px]">Genom</p>
                      <p className="text-purple-400 font-bold text-lg">{ai.neat.genome_count}</p>
                    </div>
                    <div className="bg-gray-800/50 rounded-lg p-2">
                      <p className="text-gray-500 text-[10px]">Tür</p>
                      <p className="text-blue-400 font-bold text-lg">{ai.neat.species_count}</p>
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-center py-4">
                  <p className="text-gray-600 text-2xl mb-2">🧬</p>
                  {ai.genome_count > 0 ? (
                    <>
                      <p className="text-gray-400 text-sm font-semibold">{ai.genome_count} Genom Mevcut</p>
                      <p className="text-gray-600 text-xs mt-1">NEAT istatistik anahtarı bekleniyor</p>
                    </>
                  ) : (
                    <>
                      <p className="text-gray-400 text-sm font-semibold">Evrim Başlamadı</p>
                      <p className="text-gray-600 text-xs mt-1">neat_evolution servisi ilk nesli hazırlıyor</p>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Agent + Shadow */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="text-orange-400 font-semibold text-sm">🤖 Agent & Shadow</h2>
            </div>
            <div className="p-4 space-y-3">
              {/* Agent */}
              <div className="flex items-center justify-between text-xs bg-gray-800/40 rounded-lg px-3 py-2">
                <div>
                  <p className="text-gray-400">Agent son çalışma</p>
                  <p className={`font-bold ${ai.agent_last_run_sec != null && ai.agent_last_run_sec < 120 ? 'text-green-400' : ai.agent_last_run_sec != null ? 'text-yellow-400' : 'text-gray-500'}`}>
                    {fmtSec(ai.agent_last_run_sec)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-gray-400">Aktif verdict</p>
                  <p className="text-purple-400 font-bold">{ai.agent_verdict_count} coin</p>
                </div>
              </div>

              {/* Shadow */}
              {ai.shadow_total > 0 && ai.shadow_best ? (
                <div className="space-y-2 text-xs">
                  <div className="flex items-center justify-between bg-gray-800/40 rounded-lg px-3 py-2">
                    <div>
                      <p className="text-gray-400">Shadow Sharpe</p>
                      <p className={`font-bold ${((ai.shadow_best.sharpe as number) ?? 0) >= 1.5 ? 'text-green-400' : 'text-orange-400'}`}>
                        {((ai.shadow_best.sharpe as number) ?? 0).toFixed(2)}
                        {' '}<span className="text-gray-600 font-normal">/ 1.5 hedef</span>
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-gray-400">İşlem</p>
                      <p className="text-gray-300 font-bold">{(ai.shadow_best.trades as number) ?? 0} / 100</p>
                    </div>
                  </div>
                  {/* Progress to promotion */}
                  <div>
                    <div className="flex justify-between text-[10px] text-gray-500 mb-1">
                      <span>Canlıya terfi ilerleme</span>
                      <span>{Math.min(100, Math.round(((ai.shadow_best.trades as number) ?? 0)))}%</span>
                    </div>
                    <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full bg-indigo-500 rounded-full transition-all"
                        style={{ width: `${Math.min(100, ((ai.shadow_best.trades as number) ?? 0))}%` }} />
                    </div>
                    <div className="flex justify-between text-[10px] text-gray-600 mt-1">
                      <span>0 işlem</span><span>100 işlem gerekli</span>
                    </div>
                  </div>
                  {(ai.shadow_best.promotion_ready as boolean) && (
                    <div className="bg-yellow-900/30 border border-yellow-600/50 rounded-lg p-2 text-center">
                      <p className="text-yellow-400 font-black text-sm animate-pulse">🚀 CANLIYA TERFİ HAZIR!</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-2 text-xs text-gray-600">
                  Shadow sistem 100 kağıt işlem bekliyor · Şu an: {ai.shadow_total > 0 ? `${ai.shadow_total} strateji` : 'Başlamadı'}
                </div>
              )}
            </div>
          </div>

        </div>
      </div>

      {/* ── Pipeline + Market ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Pipeline */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-4">
          <h2 className="text-blue-400 font-semibold text-sm">📡 Veri Pipeline Durumu</h2>
          <PipeBar label="Feature Engine (özellik)"  count={pipe.feature_count} target={400} fresh={pipe.feature_freshness_sec} color="text-blue-400" />
          <PipeBar label="Signal Engine (sinyal)"     count={pipe.signal_count}  target={400} fresh={pipe.signal_freshness_sec}  color="text-orange-400" />
          <PipeBar label="Agent System (AI verdict)"  count={pipe.agent_count}   target={400} fresh={null} color="text-purple-400" />
          <PipeBar label="Context Engine (bağlam)"    count={pipe.context_count} target={400} fresh={null} color="text-cyan-400" />
          <div className="pt-3 border-t border-gray-800/60 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${pipe.ws_status?.status === 'CONNECTED' ? 'bg-green-400 animate-pulse' : 'bg-red-500'}`} />
              <span className="text-gray-400">WebSocket Binance USDM</span>
            </div>
            <span className={`font-bold ${pipe.ws_status?.status === 'CONNECTED' ? 'text-green-400' : 'text-red-400'}`}>
              {pipe.ws_status?.status ?? 'UNKNOWN'} · {pipe.ws_status?.symbols ?? 0} coin
            </span>
          </div>
        </div>

        {/* Market Context */}
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
              <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">Fear & Greed</p>
              {mkt.fear_greed ? (
                <>
                  <p className={`font-black text-2xl ${mkt.fear_greed.value < 25 ? 'text-red-400' : mkt.fear_greed.value < 45 ? 'text-orange-400' : mkt.fear_greed.value < 55 ? 'text-yellow-400' : 'text-green-400'}`}>
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

      {/* ── Positions + Activity ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Positions Status */}
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
                    Şu an {pipe.signal_count} sinyal aktif, system normal çalışıyor.
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs text-center">
                <div className="bg-gray-800/50 rounded-lg p-2">
                  <p className="text-gray-600">Min Güven</p>
                  <p className="text-white font-bold">60%</p>
                </div>
                <div className="bg-gray-800/50 rounded-lg p-2">
                  <p className="text-gray-600">Maks Pozisyon</p>
                  <p className="text-white font-bold">3 adet</p>
                </div>
                <div className="bg-gray-800/50 rounded-lg p-2">
                  <p className="text-gray-600">Kaldıraç</p>
                  <p className="text-white font-bold">Maks 3×</p>
                </div>
              </div>
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>Günlük Gerçekleşen P&L:</span>
                <span className={`font-mono font-bold ${pos.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {pos.daily_pnl >= 0 ? '+' : ''}${pos.daily_pnl.toFixed(2)}
                </span>
              </div>
            </div>
          ) : (
            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between bg-green-950/20 border border-green-800/30 rounded-lg px-3 py-2">
                <span className="text-green-400 font-semibold">{pos.open_count} Açık Pozisyon</span>
                <a href="/positions" className="text-orange-400 hover:text-orange-300">Detaylar →</a>
              </div>
              <div className="flex items-center justify-between text-gray-400 px-1">
                <span>Günlük P&L</span>
                <span className={`font-mono font-bold ${pos.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {pos.daily_pnl >= 0 ? '+' : ''}${pos.daily_pnl.toFixed(2)}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Activity Feed */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h2 className="text-green-400 font-semibold text-sm">⚡ Canlı Aktivite</h2>
            <span className="text-xs text-gray-600">{data.activity.length} olay · 5s</span>
          </div>
          {data.activity.length === 0 ? (
            <div className="p-6 text-center">
              <p className="text-gray-500 text-xs">Henüz aktivite yok — signal engine ısınıyor (~60s)</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-800/40 max-h-52 overflow-y-auto">
              {data.activity.map((ev, i) => {
                const e = ev as Record<string, unknown>
                const rawTs = e.time as number | undefined
                const secs = rawTs ? Math.floor(Date.now() / 1000 - rawTs) : null
                const ago = secs == null ? '—' : secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}dk`
                const isLong  = e.direction === 'long'
                const isShort = e.direction === 'short'
                return (
                  <div key={i} className="flex items-center gap-2.5 px-4 py-2 text-xs hover:bg-gray-800/20">
                    <span className={`shrink-0 ${e.type === 'scan_summary' ? 'text-blue-400' : isLong ? 'text-green-400' : isShort ? 'text-red-400' : 'text-purple-400'}`}>
                      {e.type === 'scan_summary' ? '⟳' : e.type === 'regime_change' ? '⇄' : isLong ? '▲' : isShort ? '▼' : '◉'}
                    </span>
                    <div className="flex-1 min-w-0 truncate text-gray-400">
                      {e.symbol != null && <span className="text-white font-bold mr-1">{String(e.symbol)}</span>}
                      {e.type === 'scan_summary'
                        ? <span>{String(e.total ?? '')} coin · ▲{String(e.long ?? '')} ▼{String(e.short ?? '')}</span>
                        : e.type === 'signal'
                        ? <span className={isLong ? 'text-green-400' : 'text-red-400'}>{String(e.direction ?? '').toUpperCase()} {Math.round(((e.confidence as number) ?? 0) * 100)}%</span>
                        : e.type === 'rsi_alert'
                        ? <span>RSI {(e.rsi as number | null)?.toFixed(1) ?? '—'}</span>
                        : e.type === 'regime_change'
                        ? <span className="text-purple-400">rejim → {String(e.regime ?? '')}</span>
                        : <span>{String(e.type ?? '')}</span>}
                    </div>
                    <span className="text-gray-700 font-mono shrink-0">{ago}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── How it learns (static explanation) ── */}
      <div className="bg-gray-900/60 border border-gray-800/60 rounded-xl p-4">
        <h2 className="text-white font-semibold text-sm mb-3">🎓 Yapay Zeka Nasıl Öğreniyor?</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          {[
            { icon: '🧬', title: 'NEAT Evrimi', color: 'border-purple-800/40', desc: 'Her 3 saatte bir genomlar üzerinde mutasyon ve çaprazlama uygulanır. Fitness = Sharpe × WR × (1-MaxDD). En yüksek fitness genomları hayatta kalır ve bir sonraki nesle geçer.' },
            { icon: '🤖', title: '9 Ajan Tartışması', color: 'border-orange-800/40', desc: 'Boğa, Ayı, Teknik, Haber, Makro, Zincir-üstü, Risk ve Evrim ajanları her coin için tartışır. Debate ajanı sonucu sentezler ve confidence veriri. Her ajanın doğruluk oranı takip edilir.' },
            { icon: '👻', title: 'Shadow Backtest', color: 'border-indigo-800/40', desc: '3 paralel kağıt-işlem evreni çalışır. 100 işlem sonrası Sharpe ≥1.5, WR ≥52%, DD <10% şartları sağlanırsa strateji canlıya terfi eder. Şu an bu şartlar sağlanmaya çalışılıyor.' },
            { icon: '📐', title: 'PPO (RL Agent)', color: 'border-green-800/40', desc: '500K adım boyunca gymnasium ortamında eğitilen PPO ajanı pozisyon boyutlandırma ve giriş zamanlamasını optimize eder. Stochastic policy gradient ile kendini sürekli günceller.' },
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
