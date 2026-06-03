'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  LEARNING_TABS,
  PROMOTION_CRITERIA,
  stageColor,
  type LearningTab,
} from '@/lib/learning-hub'

type HubData = {
  server_time: number
  focus_symbol: string
  curriculum: { id: string; title: string; level: string; body: string }[]
  strategy_document: string
  universe: { symbols_count: number; sample: string[] }
  portfolio: Record<string, unknown>
  open_positions: Array<{
    symbol: string
    direction: string
    size_usd: number
    unrealized_pct?: number
    verdict?: { direction?: string; confidence?: number }
    regime?: string
    ai_confidence_pct?: number
  }>
  learning: {
    engine_active: boolean
    profiles_count: number
    profiles: Array<Record<string, unknown>>
    recent_lessons: Array<{ symbol: string; text: string; ts: number }>
    focus: Record<string, unknown>
  }
  promotion: {
    approved: boolean
    reason: string | null
    best_shadow_id: string | null
    leaderboard: Array<Record<string, unknown>>
    live_steps: Array<{ step: number; text: string; done: boolean }>
  }
  llm: {
    any_configured?: boolean
    providers?: Array<{
      id: string
      name: string
      env: string
      configured: boolean
      key_count: number
      tier_note: string
    }>
    groq: { configured: boolean; model: string; key_count?: number }
    ollama: { ok: boolean; models: string[]; error?: string }
    provider_order?: string[]
    groq_pools?: Array<{ id: string; label: string; count: number; models: string[] }>
    ai_swarm?: boolean
    ai_min_votes?: number
    status_source?: 'redis' | 'env'
    learn_llm_every_n?: number
  }
  pipeline: {
    services: Array<{ name: string; alive: boolean; age_sec: number | null }>
    activity: Array<Record<string, unknown>>
    trading_halted: boolean
    immunity: Record<string, unknown> | null
  }
  backtest: { status: unknown; summary: unknown }
  qdrant: { points_count?: number }
  dry_run: boolean
}

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString('tr-TR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export default function LearningPage() {
  const [tab, setTab] = useState<LearningTab>('live')
  const [data, setData] = useState<HubData | null>(null)
  const [loading, setLoading] = useState(true)
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [cmdMsg, setCmdMsg] = useState('')
  const [cmdBusy, setCmdBusy] = useState(false)
  const [lastUpdate, setLastUpdate] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/learning?symbol=${encodeURIComponent(symbol)}`)
      if (res.ok) {
        setData(await res.json())
        setLastUpdate(new Date().toLocaleTimeString('tr-TR'))
      }
    } catch {
      /* retry */
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [load])

  const runCommand = async (
    action: string,
    extra?: { direction?: string; confidence?: number; source?: string },
  ) => {
    setCmdBusy(true)
    setCmdMsg('')
    try {
      const res = await fetch('/api/learning/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, symbol, ...extra }),
      })
      const j = await res.json()
      setCmdMsg(j.message ?? j.error ?? (res.ok ? 'OK' : 'Hata'))
      await load()
    } catch (e) {
      setCmdMsg(String(e))
    } finally {
      setCmdBusy(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] gap-3 text-gray-500">
        <span className="animate-pulse text-purple-400 text-2xl">🤖</span>
        <span>AI Öğrenme Merkezi yükleniyor…</span>
      </div>
    )
  }

  const d = data!

  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-2">
            <span>🤖</span> AI Öğrenme Merkezi
          </h1>
          <p className="text-gray-500 text-sm mt-1 max-w-2xl">
            PDF dersleri • Trade geçmişi • Canlı pipeline • Strateji belgesi • Manuel emir (paper)
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            value={symbol}
            onChange={e => setSymbol(e.target.value.toUpperCase())}
            className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white w-36 font-mono"
            placeholder="BTCUSDT"
          />
          <span className="text-xs text-gray-600">Güncelleme: {lastUpdate}</span>
          <span
            className={`text-xs font-bold px-2 py-1 rounded border ${
              d.learning.engine_active
                ? 'text-green-400 border-green-800 bg-green-950/40'
                : 'text-red-400 border-red-800'
            }`}
          >
            Öğrenme {d.learning.engine_active ? 'AKTİF' : 'KAPALI'}
          </span>
          <span className="text-xs font-bold px-2 py-1 rounded bg-yellow-900/30 text-yellow-400 border border-yellow-800">
            {d.dry_run ? 'PAPER' : 'LIVE'}
          </span>
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-gray-800 pb-2">
        {LEARNING_TABS.map(t => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            title={t.desc}
            className={`text-xs sm:text-sm px-3 py-2 rounded-lg transition-all ${
              tab === t.id
                ? 'bg-purple-600/30 text-purple-200 border border-purple-500/50 font-semibold'
                : 'text-gray-500 hover:text-white hover:bg-gray-800/80'
            }`}
          >
            <span className="mr-1">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </nav>

      {cmdMsg && (
        <p className="text-sm text-purple-200 bg-purple-950/40 border border-purple-800/50 rounded-lg px-4 py-2">
          {cmdMsg}
        </p>
      )}

      {tab === 'live' && (
        <div className="grid lg:grid-cols-2 gap-4">
          <section className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
            <h2 className="text-orange-400 font-bold text-sm uppercase tracking-wider">🎯 Canlıya geçiş</h2>
            <p className="text-gray-400 text-sm">
              Canlı emir için shadow kanıtı + .env onayı gerekir. Immunity limitleri değiştirilemez.
            </p>
            <div
              className={`p-4 rounded-lg border ${
                d.promotion.approved
                  ? 'bg-green-950/30 border-green-700/50'
                  : 'bg-gray-800/50 border-gray-700'
              }`}
            >
              <p className="text-white font-semibold">
                Promotion: {d.promotion.approved ? '✓ ONAYLI' : '⏳ BEKLİYOR'}
              </p>
              <p className="text-gray-500 text-xs mt-1">{d.promotion.reason}</p>
              {d.promotion.best_shadow_id && (
                <p className="text-cyan-400 text-xs mt-2">En iyi shadow: {d.promotion.best_shadow_id}</p>
              )}
            </div>
            <ol className="space-y-2">
              {d.promotion.live_steps.map(s => (
                <li key={s.step} className="flex gap-2 text-sm">
                  <span className={s.done ? 'text-green-400' : 'text-gray-600'}>
                    {s.done ? '✓' : '○'}
                  </span>
                  <span className={s.done ? 'text-gray-300' : 'text-gray-500'}>{s.text}</span>
                </li>
              ))}
            </ol>
            <div className="text-xs text-gray-600 space-y-1 font-mono">
              <p>DRY_RUN=false</p>
              <p>LIVE_TRADING_CONFIRMED=true</p>
              <p>system:promotion:status → approved</p>
            </div>
          </section>

          <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-blue-400 font-bold text-sm uppercase mb-3">Shadow leaderboard</h2>
            <div className="space-y-3">
              {(d.promotion.leaderboard as Array<Record<string, unknown>>).map((e, i) => (
                <div
                  key={String(e.shadow_id ?? i)}
                  className="flex justify-between items-center text-sm border-b border-gray-800/60 pb-2"
                >
                  <span className="text-white font-mono">{String(e.shadow_id)}</span>
                  <span className="text-gray-400">
                    S={Number(e.sharpe ?? 0).toFixed(2)} WR=
                    {(Number(e.win_rate ?? 0) * 100).toFixed(0)}% T={String(e.trades ?? 0)}
                  </span>
                  {Boolean(e.promotion_ready) && (
                    <span className="text-green-400 text-xs font-bold">READY</span>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {PROMOTION_CRITERIA.map(c => (
                <div key={c.key} className="bg-gray-800/40 rounded p-2 text-xs">
                  <span className="text-gray-500">{c.label}</span>
                  <p className="text-white font-mono">
                    ≥{c.target}
                    {c.unit}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-white font-semibold text-sm mb-2">Açık pozisyonlar ({d.open_positions.length})</h2>
            {d.open_positions.length === 0 ? (
              <p className="text-gray-500 text-sm">Açık pozisyon yok</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-500 text-xs border-b border-gray-800">
                      <th className="text-left py-2">Symbol</th>
                      <th>Dir</th>
                      <th>PnL%</th>
                      <th>AI</th>
                      <th>Regime</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.open_positions.map(p => (
                      <tr key={`${p.symbol}-${p.direction}`} className="border-b border-gray-800/40">
                        <td className="py-2 font-bold text-white">{p.symbol}</td>
                        <td className="text-green-400">{p.direction}</td>
                        <td
                          className={
                            (p.unrealized_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                          }
                        >
                          {(p.unrealized_pct ?? 0).toFixed(2)}%
                        </td>
                        <td className="text-gray-400">
                          {p.verdict?.direction ?? '—'} {p.ai_confidence_pct ?? '—'}%
                        </td>
                        <td className="text-blue-400">{p.regime ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {tab === 'brain' && (
        <section className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
          <h2 className="text-cyan-400 font-bold">🧠 Ollama beyin</h2>
          {d.llm.ollama.ok ? (
            <>
              <p className="text-green-400 text-sm">Ollama erişilebilir</p>
              <ul className="grid sm:grid-cols-2 gap-2">
                {d.llm.ollama.models.map(m => (
                  <li
                    key={m}
                    className="text-sm font-mono text-gray-300 bg-gray-800/60 rounded px-3 py-2 border border-gray-700"
                  >
                    {m}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-red-400 text-sm">
              Ollama yanıt vermiyor: {d.llm.ollama.error ?? 'bağlantı hatası'}
            </p>
          )}
          <p className="text-gray-500 text-xs">
            learning_engine L2+ profillerde Ollama/Groq ile coin özeti üretir. Model:{' '}
            {process.env.NEXT_PUBLIC_OLLAMA_MODEL ?? 'llama3.1:8b (container env)'}
          </p>
        </section>
      )}

      {tab === 'lessons' && (
        <div className="grid lg:grid-cols-2 gap-4">
          <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-purple-400 font-bold text-sm mb-3">📖 Müfredat (statik dersler)</h2>
            <div className="space-y-3 max-h-[480px] overflow-y-auto">
              {d.curriculum.map(c => (
                <article key={c.id} className="border border-gray-800 rounded-lg p-3">
                  <div className="flex justify-between">
                    <h3 className="text-white font-semibold text-sm">{c.title}</h3>
                    <span className="text-xs text-purple-400">{c.level}</span>
                  </div>
                  <p className="text-gray-500 text-xs mt-2 leading-relaxed">{c.body}</p>
                </article>
              ))}
            </div>
          </section>
          <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-purple-400 font-bold text-sm mb-3">
              Canlı dersler ({d.learning.recent_lessons.length})
            </h2>
            <p className="text-xs text-gray-600 mb-2">
              Qdrant hafıza: {d.qdrant?.points_count ?? 0} trade point
            </p>
            <div className="space-y-2 max-h-[480px] overflow-y-auto">
              {d.learning.recent_lessons.length === 0 ? (
                <p className="text-gray-500 text-sm">Henüz ders yok — learning_engine çalıştırın</p>
              ) : (
                d.learning.recent_lessons.map((l, i) => (
                  <div
                    key={`${l.symbol}-${l.ts}-${i}`}
                    className="text-xs border-l-2 border-purple-600 pl-3 py-1"
                  >
                    <span className="text-orange-400 font-mono">{l.symbol}</span>
                    <span className="text-gray-600 ml-2">{fmtTime(l.ts)}</span>
                    <p className="text-gray-400 mt-1 leading-snug">{l.text}</p>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      )}

      {tab === 'stream' && (
        <div className="grid lg:grid-cols-3 gap-4">
          <section className="lg:col-span-1 bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-green-400 font-bold text-sm mb-3">Servis nabzı</h2>
            <ul className="space-y-2">
              {d.pipeline.services.map(s => (
                <li key={s.name} className="flex justify-between text-sm">
                  <span className="text-gray-400">{s.name}</span>
                  <span className={s.alive ? 'text-green-400' : 'text-red-400'}>
                    {s.alive ? `OK ${s.age_sec ?? 0}s` : 'DOWN'}
                  </span>
                </li>
              ))}
            </ul>
            {d.pipeline.trading_halted && (
              <p className="mt-4 text-red-400 text-xs font-bold">⛔ İşlemler duraklatıldı</p>
            )}
          </section>
          <section className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-green-400 font-bold text-sm mb-3">📡 activity:feed</h2>
            <div className="space-y-1 max-h-[520px] overflow-y-auto font-mono text-xs">
              {d.pipeline.activity.map((ev, i) => (
                <div key={i} className="text-gray-500 hover:text-gray-300 py-0.5">
                  <span className="text-gray-600">{fmtTime(Number(ev.time ?? 0))}</span>{' '}
                  <span className="text-cyan-600">{String(ev.type)}</span>{' '}
                  {ev.symbol ? <span className="text-white">{String(ev.symbol)}</span> : null}{' '}
                  {ev.direction ? <span>{String(ev.direction)}</span> : null}
                  {ev.total != null ? (
                    <span className="text-gray-600">
                      {' '}
                      L={String(ev.long)} S={String(ev.short)}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {tab === 'strategy' && (
        <div className="space-y-4">
          <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-white font-bold mb-2">
              Odak: {d.focus_symbol} — {d.learning.profiles_count} profil evrende
            </h2>
            <div className="grid md:grid-cols-2 gap-4 text-sm">
              <pre className="bg-gray-950 p-3 rounded text-xs text-gray-400 overflow-auto max-h-48">
                {JSON.stringify(d.learning.focus.signal, null, 2)}
              </pre>
              <pre className="bg-gray-950 p-3 rounded text-xs text-gray-400 overflow-auto max-h-48">
                {JSON.stringify(d.learning.focus.verdict, null, 2)}
              </pre>
            </div>
          </section>
          <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800">
              <h2 className="text-orange-400 font-semibold text-sm">En derin profiller (L2/L3)</h2>
            </div>
            <div className="overflow-x-auto max-h-[500px]">
              <table className="w-full text-xs">
                <thead className="text-gray-500 bg-gray-950">
                  <tr>
                    <th className="text-left p-2">Symbol</th>
                    <th>Stage</th>
                    <th>Updates</th>
                    <th>Regime</th>
                    <th>Depth</th>
                    <th className="text-left p-2">Giriş ipucu</th>
                  </tr>
                </thead>
                <tbody>
                  {d.learning.profiles.slice(0, 50).map(p => (
                    <tr
                      key={String(p.symbol)}
                      className="border-t border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
                      onClick={() => setSymbol(String(p.symbol))}
                    >
                      <td className="p-2 font-bold text-white">{String(p.symbol)}</td>
                      <td className={`p-2 ${stageColor(String(p.learning_stage))}`}>
                        {String(p.learning_stage)}
                      </td>
                      <td className="p-2 text-gray-400">{String(p.updates)}</td>
                      <td className="p-2 text-blue-400">{String(p.current_regime)}</td>
                      <td className="p-2">{String(p.depth_score)}</td>
                      <td className="p-2 text-gray-500 max-w-xs truncate">
                        {String(p.best_entry_hint ?? '').slice(0, 60)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {tab === 'doc' && (
        <section className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-white font-bold">📋 Strateji belgesi (otomatik)</h2>
            <button
              type="button"
              className="text-xs text-orange-400 hover:text-orange-300"
              onClick={() => navigator.clipboard.writeText(d.strategy_document)}
            >
              Kopyala
            </button>
          </div>
          <pre className="text-xs text-gray-400 whitespace-pre-wrap leading-relaxed max-h-[70vh] overflow-y-auto font-sans">
            {d.strategy_document}
          </pre>
        </section>
      )}

      {tab === 'llm' && (
        <section className="space-y-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-white font-bold mb-2">LLM durumu</h2>
            <p className={d.llm.any_configured ? 'text-green-400 text-sm' : 'text-red-400 text-sm'}>
              {d.llm.any_configured
                ? `✓ En az bir sağlayıcı aktif (Groq: ${d.llm.groq.key_count ?? 0} anahtar)`
                : '✗ LLM anahtarı görünmüyor — agent_system çalışıyor mu? .env kontrol edin'}
            </p>
            <p className="text-gray-600 text-[10px]">
              Durum kaynağı: {d.llm.status_source === 'redis' ? 'agent_system (.env doğru)' : 'dashboard env (sınırlı)'}
            </p>
            <p className="text-gray-500 text-xs mt-2 font-mono">
              Legacy: {d.llm.groq.model} · Swarm: {d.llm.ai_swarm ? `açık (min ${d.llm.ai_min_votes ?? 3} oy)` : 'kapalı'}
            </p>
            {(d.llm.groq_pools ?? []).filter(p => p.count > 0).length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {(d.llm.groq_pools ?? [])
                  .filter(p => p.count > 0)
                  .map(p => (
                    <span
                      key={p.id}
                      className="text-[10px] px-2 py-1 rounded bg-gray-800 text-gray-400 border border-gray-700"
                      title={p.models.join(', ')}
                    >
                      {p.label}: {p.count} model
                    </span>
                  ))}
              </div>
            )}
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-orange-400 font-bold mb-4">Eksik / yapılandırılmış anahtarlar</h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {(d.llm.providers ?? []).map(p => (
                <div
                  key={p.id}
                  className={`rounded-lg border p-3 ${
                    p.configured ? 'border-green-800/50 bg-green-950/20' : 'border-red-900/40 bg-red-950/10'
                  }`}
                >
                  <div className="flex justify-between items-center">
                    <span className="text-white font-medium text-sm">{p.name}</span>
                    <span className={p.configured ? 'text-green-400' : 'text-red-400'}>
                      {p.configured ? '✓' : '✕'}
                    </span>
                  </div>
                  <p className="text-gray-500 text-xs mt-1">{p.tier_note}</p>
                  {p.key_count > 1 && (
                    <p className="text-blue-400 text-xs mt-1">{p.key_count} anahtar (rotasyon)</p>
                  )}
                  <p className="text-gray-600 text-[10px] font-mono mt-1 truncate">{p.env}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-3">
              <h2 className="text-cyan-400 font-bold">Ollama</h2>
              <p className={d.llm.ollama.ok ? 'text-green-400' : 'text-red-400'}>
                {d.llm.ollama.ok ? '✓ Çalışıyor' : '✗ Kapalı'}
              </p>
              <p className="text-gray-500 text-xs">{d.llm.ollama.models.length} model yüklü</p>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 text-sm text-gray-400">
              <p>
                Debate + öğrenme: rate-limit olunca sıradaki anahtar/sağlayıcıya geçer (GROQ_API_KEY_1…
                {32}). Öğrenme LLM: her {d.llm.learn_llm_every_n ?? 90} tick.
              </p>
            </div>
          </div>
        </section>
      )}

      {tab === 'command' && (
        <section className="bg-gray-900 border border-orange-800/40 rounded-xl p-6 space-y-6">
          <div>
            <h2 className="text-orange-400 font-bold text-lg">⚡ Emir merkezi — {symbol}</h2>
            <p className="text-gray-500 text-sm mt-1">
              Paper mod: sinyal Redis&apos;e yazılır → OMS/shadow döngüsü işler. Immunity reddedebilir.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('force_signal', { direction: 'long', confidence: 0.72 })}
              className="py-4 rounded-xl bg-green-900/40 border border-green-700 text-green-300 font-bold hover:bg-green-900/60 disabled:opacity-50"
            >
              ▲ LONG aç
            </button>
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('force_signal', { direction: 'short', confidence: 0.72 })}
              className="py-4 rounded-xl bg-red-900/40 border border-red-700 text-red-300 font-bold hover:bg-red-900/60 disabled:opacity-50"
            >
              ▼ SHORT aç
            </button>
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('force_signal', { direction: 'flat' })}
              className="py-4 rounded-xl bg-gray-800 border border-gray-600 text-gray-300 font-bold hover:bg-gray-700 disabled:opacity-50"
            >
              ◼ FLAT / çıkış sinyali
            </button>
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('close_symbol', { source: 'both' })}
              className="py-4 rounded-xl bg-orange-900/40 border border-orange-700 text-orange-200 font-bold hover:bg-orange-900/60 disabled:opacity-50"
            >
              Kapat (guard)
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('refresh_debate')}
              className="px-4 py-2 rounded-lg bg-purple-900/40 border border-purple-700 text-sm text-purple-200"
            >
              🔄 Debate yenile
            </button>
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('refresh_learning')}
              className="px-4 py-2 rounded-lg bg-blue-900/40 border border-blue-700 text-sm text-blue-200"
            >
              📚 Öğrenme taraması
            </button>
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('close_all')}
              className="px-4 py-2 rounded-lg bg-red-950 border border-red-800 text-sm text-red-300"
            >
              🚨 Tümünü kapat
            </button>
            <button
              type="button"
              disabled={cmdBusy}
              onClick={() => runCommand('resume_trading')}
              className="px-4 py-2 rounded-lg bg-yellow-900/30 border border-yellow-800 text-sm text-yellow-300"
            >
              ▶ İşleme devam
            </button>
          </div>
          <p className="text-gray-600 text-xs">
            LONG/SHORT: signal:latest + activity feed. Kapat: ch:position:guard. Debate: ch:learn:SYMBOL.
            Öğrenme: ch:features:SYMBOL.
          </p>
        </section>
      )}
    </div>
  )
}
