'use client'
import { useEffect, useState } from 'react'

interface TradeMemory {
  symbol?: string
  was_winner?: boolean
  pnl_pct?: number
  regime?: string
  error_category?: string
  time?: number
  drift_at_entry?: string
  confidence?: number
}

interface MemoryData {
  memories: TradeMemory[]
  total_memories: number
  win_count: number
  loss_count: number
  error_categories: Record<string, number>
  win_regimes: Record<string, number>
  top_symbols: { symbol: string; wins: number; losses: number }[]
  genomes: {
    count: number
    best_fitness: number
    avg_fitness: number
    sample: { fitness?: number; generation?: number; nodes?: number; connections?: number }[]
  }
  current_state: {
    direction_dist: { long: number; short: number; flat: number }
    regime_dist: Record<string, number>
    regime: string | null
    crisis_level: number
    vix: number | null
  }
}

const REGIME_COLOR: Record<string, string> = {
  trending_up: 'text-green-400', trending_down: 'text-red-400',
  ranging: 'text-blue-400', volatile: 'text-yellow-400',
}

const PIPELINE_STEPS = [
  {
    icon: '📡',
    title: 'Veri Akışı',
    desc: '100 sembol için Binance WebSocket kanallarından gerçek zamanlı fiyat, order book, işlem verileri alınır.',
    color: 'border-blue-700/50 bg-blue-950/20',
    label: 'DATA INGESTION',
  },
  {
    icon: '🔬',
    title: 'Özellik Üretimi',
    desc: 'RSI, MACD, BB, ADX, Stoch + funding rate, OI, L/S oranı + sentiment birleştirilerek 50+ özellik hesaplanır. Drift dedektörü piyasa değişimini izler.',
    color: 'border-purple-700/50 bg-purple-950/20',
    label: 'FEATURE ENGINE',
  },
  {
    icon: '🌐',
    title: 'Bağlam Analizi',
    desc: 'GMM ile 4 rejim tespiti (yükselen/düşen trend, yatay, volatil). Kriz dedektörü VIX > 40, BTC -%10/saat, $100M likidasyonu izler.',
    color: 'border-cyan-700/50 bg-cyan-950/20',
    label: 'CONTEXT ENGINE',
  },
  {
    icon: '🤖',
    title: '9 Ajan Tartışması',
    desc: 'Boğa, Ayı, Nötr, Teknik, Haber, Makro, Zincir-üstü, Risk ve Evrim ajanları Claude API ile tartışır. Debate ajanı sonucu sentezler.',
    color: 'border-orange-700/50 bg-orange-950/20',
    label: 'AGENT SYSTEM',
  },
  {
    icon: '⚡',
    title: 'Sinyal Üretimi',
    desc: 'Ağırlıklı oy < %60 ise sinyal bastırılır. Kelly kriteri × kriz çarpanı × drift çarpanı = pozisyon büyüklüğü (maks %5).',
    color: 'border-yellow-700/50 bg-yellow-950/20',
    label: 'SIGNAL ENGINE',
  },
  {
    icon: '🛡️',
    title: 'Bağışıklık Sistemi',
    desc: 'Her emirden önce sabit limitler kontrol edilir: maks kaldıraç 3×, günlük zarar %2, pozisyon %7, günlük 50 işlem. Atlatılamaz.',
    color: 'border-red-700/50 bg-red-950/20',
    label: 'IMMUNITY SYSTEM',
  },
  {
    icon: '👻',
    title: 'Gölge Test',
    desc: '3 paralel kağıt-işlem evreni. ≥100 işlem, Sharpe ≥1.5, WR ≥%52, DD <%10 şartları sağlandığında canlı sermayeye terfi.',
    color: 'border-indigo-700/50 bg-indigo-950/20',
    label: 'SHADOW SYSTEM',
  },
  {
    icon: '🧬',
    title: 'NEAT Evrimi',
    desc: 'Her 3 saatte bir genomlar rekabet eder. Fitness = Sharpe × WR × (1−DD). En iyi genomlar EvolutionAgent aracılığıyla kararları etkiler.',
    color: 'border-green-700/50 bg-green-950/20',
    label: 'NEAT EVOLUTION',
  },
]

function MemoryCard({ m, index }: { m: TradeMemory; index: number }) {
  const win = m.was_winner
  const pnl = (m.pnl_pct ?? 0) * 100
  const age = m.time ? Math.round((Date.now() / 1000 - m.time) / 3600) : null

  return (
    <div className={`rounded-lg border overflow-hidden ${win ? 'border-green-900/60 bg-green-950/10' : 'border-red-900/50 bg-red-950/10'}`}>
      <div className="px-3 py-2 flex items-center justify-between border-b border-gray-800/50">
        <div className="flex items-center gap-2">
          <span className={`text-base ${win ? 'text-green-400' : 'text-red-400'}`}>{win ? '✓' : '✗'}</span>
          <span className="text-white font-bold text-sm">{m.symbol ?? '—'}</span>
          {m.regime && <span className={`text-[10px] ${REGIME_COLOR[m.regime] ?? 'text-gray-500'}`}>{m.regime.replace('_', ' ')}</span>}
        </div>
        <div className="flex items-center gap-2">
          <span className={`font-mono text-sm font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
          </span>
          {age !== null && <span className="text-gray-700 text-xs">{age}sa önce</span>}
        </div>
      </div>
      <div className="px-3 py-2 flex flex-wrap gap-2 text-xs">
        {m.error_category && !win && (
          <span className="bg-red-900/20 text-red-400 border border-red-800/30 px-1.5 py-0.5 rounded">
            {m.error_category}
          </span>
        )}
        {m.drift_at_entry && (
          <span className="text-gray-500">{m.drift_at_entry}</span>
        )}
        {m.confidence != null && (
          <span className="text-gray-600">conf: {Math.round(m.confidence * 100)}%</span>
        )}
      </div>
    </div>
  )
}

function StatBar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? (value / total) * 100 : 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-400 w-28 shrink-0 truncate">{label}</span>
      <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-400 font-mono w-8 text-right">{value}</span>
    </div>
  )
}

export default function MemoryPage() {
  const [data, setData] = useState<Partial<MemoryData>>({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [tab, setTab] = useState<'pipeline' | 'memories' | 'stats'>('pipeline')

  const fetchData = async () => {
    try {
      const d = await fetch('/api/memory').then(r => r.json())
      setData(d || {})
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => { fetchData(); const t = setInterval(fetchData, 30000); return () => clearInterval(t) }, [])

  const memories = data.memories ?? []
  const winRate = (data.win_count ?? 0) + (data.loss_count ?? 0) > 0
    ? ((data.win_count ?? 0) / ((data.win_count ?? 0) + (data.loss_count ?? 0))) * 100
    : 0
  const currentState = data.current_state
  const genomes = data.genomes
  const errorCats = Object.entries(data.error_categories ?? {}).sort((a, b) => b[1] - a[1])
  const winRegs = Object.entries(data.win_regimes ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">AI Hafızası & Öğrenme</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            Sistemin nasıl çalıştığı, ne öğrendiği ve kendini nasıl geliştirdiği
          </p>
        </div>
        <span className="text-xs text-gray-600 shrink-0">{lastUpdate ? `${lastUpdate} · 30s` : '30s refresh'}</span>
      </div>

      {/* Summary stats */}
      {!loading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
          {[
            { label: 'Toplam Hafıza', value: String(data.total_memories ?? 0), color: 'text-blue-400', sub: 'Qdrant kayıtları' },
            { label: 'Kazanma Oranı', value: winRate > 0 ? `${winRate.toFixed(1)}%` : '—', color: winRate >= 52 ? 'text-green-400' : 'text-orange-400', sub: `${data.win_count ?? 0}K / ${data.loss_count ?? 0}K` },
            { label: 'En İyi Genome', value: genomes?.best_fitness ? genomes.best_fitness.toFixed(4) : '—', color: 'text-purple-400', sub: `${genomes?.count ?? 0} aktif genom` },
            { label: 'Kriz Seviyesi', value: `L${currentState?.crisis_level ?? 0}`, color: (currentState?.crisis_level ?? 0) === 0 ? 'text-green-400' : 'text-red-400', sub: currentState?.regime?.replace('_', ' ') ?? 'bekleniyor' },
          ].map(item => (
            <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
              <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{item.label}</p>
              <p className={`text-xl font-bold ${item.color}`}>{item.value}</p>
              <p className="text-gray-600 text-xs mt-0.5">{item.sub}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tab selector */}
      <div className="flex gap-1 bg-gray-900/60 rounded-lg p-1 border border-gray-800/60">
        {([
          { key: 'pipeline', label: '⚙️ Karar Süreci' },
          { key: 'memories', label: '🧠 İşlem Hafızası' },
          { key: 'stats', label: '📊 AI İstatistikleri' },
        ] as const).map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2 text-xs rounded transition-colors font-semibold ${tab === t.key
              ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30'
              : 'text-gray-500 hover:text-gray-300'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* TAB: Pipeline */}
      {tab === 'pipeline' && (
        <div className="space-y-3">
          <div className="bg-gray-900/40 border border-gray-800/60 rounded-lg p-4">
            <h2 className="text-orange-400 font-semibold text-xs uppercase tracking-wider mb-3">
              Coin Nasıl Bulunuyor? — 8 Aşamalı Karar Süreci
            </h2>
            <p className="text-gray-500 text-xs mb-4">
              Her coin için saniyede bir kez bu 8 aşama çalışır. Sistem aynı anda 500+ coini paralel olarak takip eder ve yalnızca tüm filtrelerden geçenlerde pozisyon açar.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
              {PIPELINE_STEPS.map((step, i) => (
                <div key={i} className={`rounded-lg border p-3 ${step.color}`}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xl">{step.icon}</span>
                    <div>
                      <p className="text-[10px] text-gray-600 uppercase tracking-wider">{step.label}</p>
                      <p className="text-white font-semibold text-xs">{step.title}</p>
                    </div>
                  </div>
                  <p className="text-gray-400 text-[11px] leading-relaxed">{step.desc}</p>
                  {i < PIPELINE_STEPS.length - 1 && (
                    <div className="hidden xl:block absolute" />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Current state live */}
          {currentState && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <h3 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">Şu An — Sinyal Dağılımı</h3>
                <div className="space-y-2">
                  {[
                    { label: 'LONG', count: currentState.direction_dist.long, color: 'bg-green-500', text: 'text-green-400' },
                    { label: 'SHORT', count: currentState.direction_dist.short, color: 'bg-red-500', text: 'text-red-400' },
                    { label: 'FLAT', count: currentState.direction_dist.flat, color: 'bg-gray-600', text: 'text-gray-400' },
                  ].map(item => {
                    const total = (currentState.direction_dist.long + currentState.direction_dist.short + currentState.direction_dist.flat) || 1
                    return (
                      <div key={item.label} className="flex items-center gap-2 text-xs">
                        <span className={`w-10 font-bold ${item.text}`}>{item.label}</span>
                        <div className="flex-1 bg-gray-800 rounded-full h-2 overflow-hidden">
                          <div className={`h-full rounded-full ${item.color}`}
                            style={{ width: `${(item.count / total) * 100}%` }} />
                        </div>
                        <span className={`w-8 text-right font-mono ${item.text}`}>{item.count}</span>
                      </div>
                    )
                  })}
                </div>
                <div className="mt-3 pt-3 border-t border-gray-800/60 flex justify-between text-xs">
                  <span className="text-gray-500">Rejim: <span className={REGIME_COLOR[currentState.regime ?? ''] ?? 'text-gray-400'}>{currentState.regime?.replace('_', ' ') ?? '—'}</span></span>
                  {currentState.vix != null && <span className="text-gray-500">VIX: <span className={currentState.vix > 40 ? 'text-red-400' : currentState.vix > 25 ? 'text-orange-400' : 'text-green-400'}>{currentState.vix.toFixed(1)}</span></span>}
                </div>
              </div>

              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <h3 className="text-gray-400 font-semibold text-xs uppercase tracking-wider mb-3">Şu An — Rejim Dağılımı</h3>
                <div className="space-y-2">
                  {Object.entries(currentState.regime_dist).sort((a, b) => b[1] - a[1]).map(([regime, count]) => {
                    const total = Object.values(currentState.regime_dist).reduce((s, v) => s + v, 0) || 1
                    return (
                      <div key={regime} className="flex items-center gap-2 text-xs">
                        <span className={`w-28 shrink-0 ${REGIME_COLOR[regime] ?? 'text-gray-400'}`}>{regime.replace('_', ' ')}</span>
                        <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
                          <div className={`h-full rounded-full ${REGIME_COLOR[regime]?.replace('text-', 'bg-') ?? 'bg-gray-500'}`}
                            style={{ width: `${(count / total) * 100}%` }} />
                        </div>
                        <span className="text-gray-400 w-8 text-right font-mono">{count}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          {/* NEAT genome sample */}
          {genomes && genomes.sample.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <h3 className="text-green-400 font-semibold text-xs uppercase tracking-wider mb-3">
                NEAT Evrim — En İyi Genomlar
                <span className="text-gray-600 font-normal ml-2">Fitness = Sharpe × WR × (1−MaxDD)</span>
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
                {genomes.sample.map((g, i) => (
                  <div key={i} className="bg-gray-800/50 rounded p-2.5 text-xs">
                    <p className="text-green-400 font-bold text-base font-mono">{typeof g.fitness === 'number' ? g.fitness.toFixed(4) : '—'}</p>
                    <p className="text-gray-500 mt-0.5">Gen {g.generation ?? '—'}</p>
                    <p className="text-gray-600">{g.nodes ?? '—'} nöron · {g.connections ?? '—'} bağlantı</p>
                  </div>
                ))}
              </div>
              <p className="text-gray-600 text-xs mt-2">
                Genomlar her 3 saatte bir evrimleşir. Toplam {genomes.count} aktif genom, ort. fitness: {genomes.avg_fitness.toFixed(4)}
              </p>
            </div>
          )}
        </div>
      )}

      {/* TAB: Memories */}
      {tab === 'memories' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-gray-500 text-xs">
              Qdrant vektör veritabanındaki son {memories.length} hafıza · Toplam: {data.total_memories ?? 0} kayıt
            </p>
          </div>
          {loading ? (
            <div className="text-center py-12 text-gray-500 text-sm">Hafıza yükleniyor...</div>
          ) : memories.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
              <p className="text-gray-400 text-sm">Henüz işlem hafızası yok</p>
              <p className="text-gray-600 text-xs mt-2 max-w-xs mx-auto">
                Gölge sistemin işlemleri otopsi ajanı tarafından analiz edilip Qdrant'a kaydedilince burada görünecek.
                Bu, sistemin geçmiş hatalarından öğrenmesini sağlar.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">
              {memories.map((m, i) => <MemoryCard key={i} m={m} index={i} />)}
            </div>
          )}
        </div>
      )}

      {/* TAB: Stats */}
      {tab === 'stats' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Error categories */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <h3 className="text-red-400 font-semibold text-xs uppercase tracking-wider mb-3">En Sık Hata Kategorileri</h3>
              {errorCats.length === 0 ? (
                <p className="text-gray-600 text-xs">Henüz veri yok</p>
              ) : (
                <div className="space-y-2">
                  {errorCats.map(([cat, count]) => (
                    <StatBar key={cat} label={cat} value={count} total={errorCats.reduce((s, [, v]) => s + v, 0)} color="bg-red-500" />
                  ))}
                </div>
              )}
              <p className="text-gray-600 text-xs mt-3 border-t border-gray-800/60 pt-2">
                Otopsi ajanı her kaybedilen işlemi analiz eder ve hata kategorisi atar. Bu veriler gelecek karar ağırlıklarını etkiler.
              </p>
            </div>

            {/* Win regimes */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <h3 className="text-green-400 font-semibold text-xs uppercase tracking-wider mb-3">Kazanılan Rejimler</h3>
              {winRegs.length === 0 ? (
                <p className="text-gray-600 text-xs">Henüz veri yok</p>
              ) : (
                <div className="space-y-2">
                  {winRegs.map(([regime, count]) => (
                    <StatBar key={regime} label={regime.replace('_', ' ')} value={count} total={winRegs.reduce((s, [, v]) => s + v, 0)} color="bg-green-500" />
                  ))}
                </div>
              )}
              <p className="text-gray-600 text-xs mt-3 border-t border-gray-800/60 pt-2">
                Hangi piyasa rejiminde daha fazla kazanıldığı. Sistem bu pattern'i öğrenerek o rejimlerde daha agresif pozisyon alır.
              </p>
            </div>
          </div>

          {/* Top symbols */}
          {(data.top_symbols ?? []).length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h3 className="text-orange-400 font-semibold text-xs uppercase tracking-wider">En Çok İşlem Yapılan Semboller</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs min-w-[400px]">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-800/60">
                      <th className="text-left px-4 py-2">Sembol</th>
                      <th className="text-left px-4 py-2">Kazanılan</th>
                      <th className="text-left px-4 py-2">Kaybedilen</th>
                      <th className="text-left px-4 py-2">WR</th>
                      <th className="text-left px-4 py-2">Performans</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.top_symbols ?? []).map(s => {
                      const total = s.wins + s.losses
                      const wr = total > 0 ? (s.wins / total) * 100 : 0
                      return (
                        <tr key={s.symbol} className="border-b border-gray-800/30 hover:bg-gray-800/20">
                          <td className="px-4 py-2.5 font-bold text-white">{s.symbol}</td>
                          <td className="px-4 py-2.5 text-green-400 font-mono">{s.wins}</td>
                          <td className="px-4 py-2.5 text-red-400 font-mono">{s.losses}</td>
                          <td className={`px-4 py-2.5 font-mono font-bold ${wr >= 52 ? 'text-green-400' : 'text-gray-400'}`}>{wr.toFixed(0)}%</td>
                          <td className="px-4 py-2.5 w-32">
                            <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
                              <div className={`h-full rounded-full ${wr >= 52 ? 'bg-green-500' : 'bg-red-500'}`}
                                style={{ width: `${wr}%` }} />
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Learning explanation */}
          <div className="bg-gray-900/60 border border-gray-800/60 rounded-lg p-4 space-y-3 text-xs text-gray-400">
            <h3 className="text-white font-semibold text-sm">Sistem Nasıl Öğreniyor?</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                {
                  icon: '🔁', title: 'NEAT Evrimi',
                  text: 'Her 3 saatte bir genomlar üzerinde mutasyon ve çaprazlama uygulanır. Daha yüksek Sharpe/WR oranına sahip genomlar hayatta kalır ve sonraki nesle geçer.',
                },
                {
                  icon: '🏆', title: 'Ajan Ağırlıklandırması',
                  text: 'Her ajan ne kadar doğru tahmin yaptığı takip edilir. Doğru tahmin eden ajanın oyuna verilen ağırlık artar; yanlış yapanınki düşer.',
                },
                {
                  icon: '🗃️', title: 'Vektör Hafızası',
                  text: 'Her tamamlanan işlem embedding\'e çevrilip Qdrant\'ta saklanır. Yeni bir sinyal üretilirken benzer geçmiş durumlar aranır ve bağlam olarak kullanılır.',
                },
                {
                  icon: '📐', title: 'PPO Takviyeli Öğrenme',
                  text: '500K adım boyunca gymnasium ortamında eğitilen PPO ajanı pozisyon boyutlandırma ve giriş zamanlamasını optimize eder. Model periyodik olarak yeniden eğitilir.',
                },
              ].map(item => (
                <div key={item.title} className="bg-gray-800/40 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-base">{item.icon}</span>
                    <span className="text-white font-semibold text-xs">{item.title}</span>
                  </div>
                  <p className="leading-relaxed">{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
