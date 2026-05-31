'use client'
import { useEffect, useState, useRef } from 'react'
import { PositionDecisionPanel } from '@/components/PositionDecisionPanel'
import type { PositionDecision } from '@/lib/positions'

interface ActivityEvent {
  type: string
  time?: number
  symbol?: string
  direction?: string
  confidence?: number
  source?: string
  rsi?: number
  label?: string
  regime?: string
  prev_regime?: string
  crisis_level?: number
  total?: number
  long?: number
  short?: number
  flat?: number
}

interface ActiveSignal {
  symbol: string
  direction: string
  confidence: number
  regime?: string
  drift_status?: string
  rsi?: number
  crisis_level?: number
  source?: string
  trade_action?: string
  open_reason?: string
  timestamp?: number
}

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

interface LearnProfile {
  symbol: string
  current_regime?: string
  best_entry_hint?: string
  avoid_hint?: string
  updates?: number
  drivers?: { factor: string; effect: string; win_rate: number; avg_move_pct: number; samples: number }[]
}

interface LearnLesson {
  symbol: string
  text: string
  source: string
  ts: number
  category?: string
}

interface MemoryData {
  activity: ActivityEvent[]
  active_signals: ActiveSignal[]
  signal_summary: {
    total: number; long: number; short: number; flat: number
    close_actions?: number; hold_actions?: number
    avg_confidence: number; tracked_symbols: number
    context_symbols: number; agent_symbols: number
    open_positions?: number
    position_long?: number
    position_short?: number
    snapshot_at?: number | null
  }
  open_positions?: PositionDecision[]
  portfolio?: { total_open?: number; long_positions?: number; short_positions?: number }
  learning?: {
    global?: { message?: string; symbols_tracked?: number; top_drivers?: { factor: string; avg_win_rate: number }[] }
    profiles?: LearnProfile[]
    profiles_count?: number
    recent_lessons?: LearnLesson[]
    backtest_log?: { msg: string; level: string; ts: number }[]
    engine_active?: boolean
    last_heartbeat?: number | null
  }
  scanning?: { active: boolean; last_scan?: number | null; universe_size?: number }
  services?: { name: string; ok: boolean }[]
  drift_summary: Record<string, number>
  ws_status: { status: string; symbols?: number } | null
  shadow_leaderboard: { shadow_id: string; sharpe: number; win_rate: number; trades: number; return: number; promotion_ready: boolean }[]
  fear_greed: { value: number; classification: string } | null
  memories: TradeMemory[]
  total_memories: number
  win_count: number
  loss_count: number
  error_categories: Record<string, number>
  win_regimes: Record<string, number>
  top_symbols: { symbol: string; wins: number; losses: number }[]
  genomes: { count: number; best_fitness: number; avg_fitness: number; sample: { fitness?: number; generation?: number; nodes?: number; connections?: number }[] }
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
const DIR_COLOR: Record<string, string> = { long: 'text-green-400', short: 'text-red-400', flat: 'text-gray-500' }
const DIR_BG: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border border-green-800/50',
  short: 'text-red-400 bg-red-900/30 border border-red-800/50',
  flat: 'text-gray-500 bg-gray-800/40 border border-gray-700/40',
}
const DRIFT_COLOR: Record<string, string> = { STABLE: 'text-green-400', WARNING: 'text-yellow-400', DRIFTING: 'text-orange-400', SHOCK: 'text-red-500' }
const CRISIS_COLORS = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-500 animate-pulse']
const CRISIS_LABELS = ['Normal', 'Caution', 'Warning', 'Alarm', 'CRISIS']

function timeAgo(ts?: number): string {
  if (!ts) return ''
  const seconds = Math.floor(Date.now() / 1000 - (ts > 1e12 ? ts / 1000 : ts))
  if (seconds < 5) return 'şimdi'
  if (seconds < 60) return `${seconds}s önce`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}dk önce`
  return `${Math.floor(seconds / 3600)}sa önce`
}

function ActivityRow({ ev }: { ev: ActivityEvent }) {
  const ago = timeAgo(ev.time)
  if (ev.type === 'scan_summary') {
    return (
      <div className="flex items-start gap-2.5 px-3 py-2 border-b border-gray-800/40 hover:bg-gray-800/20">
        <span className="text-blue-400 text-sm mt-0.5 shrink-0">⟳</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-blue-400 font-semibold text-xs">TARAMA TAMAMLANDI</span>
            <span className="text-gray-500 text-xs">{ev.total} coin</span>
            <span className="text-green-400 text-xs">▲{ev.long}</span>
            <span className="text-red-400 text-xs">▼{ev.short}</span>
            <span className="text-gray-500 text-xs">—{ev.flat}</span>
          </div>
        </div>
        <span className="text-gray-700 text-[10px] shrink-0">{ago}</span>
      </div>
    )
  }
  if (ev.type === 'rsi_alert') {
    const isOversold = (ev.rsi ?? 50) < 50
    return (
      <div className="flex items-start gap-2.5 px-3 py-2 border-b border-gray-800/40 hover:bg-gray-800/20">
        <span className={`text-sm mt-0.5 shrink-0 ${isOversold ? 'text-blue-400' : 'text-orange-400'}`}>{isOversold ? '📉' : '📈'}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-bold text-xs">{ev.symbol}</span>
            <span className={`font-semibold text-xs ${isOversold ? 'text-blue-400' : 'text-orange-400'}`}>{ev.label}</span>
            <span className={`font-mono text-xs ${isOversold ? 'text-blue-300' : 'text-orange-300'}`}>RSI {ev.rsi?.toFixed(1)}</span>
            {ev.confidence != null && <span className="text-gray-500 text-xs">{Math.round(ev.confidence * 100)}%</span>}
          </div>
        </div>
        <span className="text-gray-700 text-[10px] shrink-0">{ago}</span>
      </div>
    )
  }
  if (ev.type === 'regime_change') {
    return (
      <div className="flex items-start gap-2.5 px-3 py-2 border-b border-gray-800/40 hover:bg-gray-800/20">
        <span className="text-purple-400 text-sm mt-0.5 shrink-0">⇄</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-bold text-xs">{ev.symbol}</span>
            <span className="text-gray-500 text-xs">rejim değişti</span>
            <span className={`text-xs ${REGIME_COLOR[ev.prev_regime ?? ''] ?? 'text-gray-400'}`}>{ev.prev_regime?.replace('_', ' ')}</span>
            <span className="text-gray-600 text-xs">→</span>
            <span className={`text-xs font-semibold ${REGIME_COLOR[ev.regime ?? ''] ?? 'text-gray-400'}`}>{ev.regime?.replace('_', ' ')}</span>
          </div>
        </div>
        <span className="text-gray-700 text-[10px] shrink-0">{ago}</span>
      </div>
    )
  }
  if (ev.type === 'signal') {
    return (
      <div className="flex items-start gap-2.5 px-3 py-2 border-b border-gray-800/40 hover:bg-gray-800/20">
        <span className={`text-sm mt-0.5 shrink-0 ${ev.direction === 'long' ? 'text-green-400' : 'text-red-400'}`}>
          {ev.direction === 'long' ? '▲' : '▼'}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-bold text-xs">{ev.symbol}</span>
            <span className={`px-1.5 rounded text-[10px] font-bold ${DIR_BG[ev.direction ?? 'flat']}`}>
              {ev.direction?.toUpperCase()}
            </span>
            {ev.confidence != null && (
              <span className={`font-mono text-xs font-bold ${ev.confidence >= 0.8 ? 'text-green-400' : 'text-orange-400'}`}>
                {Math.round(ev.confidence * 100)}%
              </span>
            )}
            {ev.rsi != null && <span className="text-gray-500 text-xs font-mono">RSI {ev.rsi?.toFixed(0)}</span>}
            {ev.regime && <span className={`text-[10px] ${REGIME_COLOR[ev.regime] ?? 'text-gray-500'}`}>{ev.regime.replace('_', ' ')}</span>}
          </div>
        </div>
        <span className="text-gray-700 text-[10px] shrink-0">{ago}</span>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-2.5 px-3 py-2 border-b border-gray-800/40 hover:bg-gray-800/20">
      <span className="text-gray-600 text-sm mt-0.5 shrink-0">◉</span>
      <div className="flex-1 min-w-0">
        <span className="text-gray-400 text-xs">{ev.type} {ev.symbol ?? ''}</span>
      </div>
      <span className="text-gray-700 text-[10px] shrink-0">{ago}</span>
    </div>
  )
}

function StatPill({ label, value, color, highlight }: { label: string; value: string | number; color: string; highlight?: boolean }) {
  return (
    <div className={`rounded-lg p-3 text-center border ${highlight ? 'bg-yellow-950/30 border-yellow-700/50' : 'bg-gray-900 border-gray-800'}`}>
      <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-xl font-black ${color}`}>{value}</p>
    </div>
  )
}

const PIPELINE_STEPS = [
  { icon: '📡', title: 'Veri Akışı', desc: '500+ sembol için Binance WebSocket kanallarından gerçek zamanlı fiyat, order book, işlem verileri alınır.', color: 'border-blue-700/50 bg-blue-950/20', label: 'DATA INGESTION' },
  { icon: '🔬', title: 'Özellik Üretimi', desc: 'RSI, MACD, BB, ADX, Stoch + funding rate, OI, L/S oranı + sentiment birleştirilerek 50+ özellik hesaplanır. Drift dedektörü piyasa değişimini izler.', color: 'border-purple-700/50 bg-purple-950/20', label: 'FEATURE ENGINE' },
  { icon: '🌐', title: 'Bağlam Analizi', desc: 'GMM ile 4 rejim tespiti (yükselen/düşen trend, yatay, volatil). Kriz dedektörü VIX > 40, BTC -%10/saat, $100M likidasyonu izler.', color: 'border-cyan-700/50 bg-cyan-950/20', label: 'CONTEXT ENGINE' },
  { icon: '🤖', title: '9 Ajan Tartışması', desc: 'Boğa, Ayı, Nötr, Teknik, Haber, Makro, Zincir-üstü, Risk ve Evrim ajanları Groq/Ollama ile tartışır. Debate ajanı sonucu sentezler.', color: 'border-orange-700/50 bg-orange-950/20', label: 'AGENT SYSTEM' },
  { icon: '⚡', title: 'Sinyal Üretimi', desc: 'Ağırlıklı oy < %60 ise sinyal bastırılır. Kelly kriteri × kriz çarpanı × drift çarpanı = pozisyon büyüklüğü (maks %5).', color: 'border-yellow-700/50 bg-yellow-950/20', label: 'SIGNAL ENGINE' },
  { icon: '🛡️', title: 'Bağışıklık Sistemi', desc: 'Her emirden önce sabit limitler kontrol edilir: maks kaldıraç 3×, günlük zarar %2, pozisyon %5, günlük 50 işlem. Atlatılamaz.', color: 'border-red-700/50 bg-red-950/20', label: 'IMMUNITY SYSTEM' },
  { icon: '👻', title: 'Gölge Test', desc: '3 paralel kağıt-işlem evreni. ≥100 işlem, Sharpe ≥1.5, WR ≥%52, DD <%10 şartları sağlandığında canlı sermayeye terfi.', color: 'border-indigo-700/50 bg-indigo-950/20', label: 'SHADOW SYSTEM' },
  { icon: '🧬', title: 'NEAT Evrimi', desc: 'Her 3 saatte bir genomlar rekabet eder. Fitness = Sharpe × WR × (1−DD). En iyi genomlar EvolutionAgent aracılığıyla kararları etkiler.', color: 'border-green-700/50 bg-green-950/20', label: 'NEAT EVOLUTION' },
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
          <span className={`font-mono text-sm font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%</span>
          {age !== null && <span className="text-gray-700 text-xs">{age}sa önce</span>}
        </div>
      </div>
      <div className="px-3 py-2 flex flex-wrap gap-2 text-xs">
        {m.error_category && !win && <span className="bg-red-900/20 text-red-400 border border-red-800/30 px-1.5 py-0.5 rounded">{m.error_category}</span>}
        {m.drift_at_entry && <span className="text-gray-500">{m.drift_at_entry}</span>}
        {m.confidence != null && <span className="text-gray-600">conf: {Math.round(m.confidence * 100)}%</span>}
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
  const [tab, setTab] = useState<'live' | 'pipeline' | 'learning' | 'memories' | 'stats'>('live')
  const [expandedPos, setExpandedPos] = useState<string | null>(null)
  const feedRef = useRef<HTMLDivElement>(null)

  const fetchData = async () => {
    try {
      const d = await fetch('/api/memory').then(r => r.json())
      setData(d || {})
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { } finally { setLoading(false) }
  }

  useEffect(() => {
    fetchData()
    const t = setInterval(fetchData, 5000)
    return () => clearInterval(t)
  }, [])

  const memories = data.memories ?? []
  const summary = data.signal_summary
  const activity = data.activity ?? []
  const activeSignals = data.active_signals ?? []
  const openPositions = data.open_positions ?? []
  const currentState = data.current_state
  const genomes = data.genomes
  const winRate = (data.win_count ?? 0) + (data.loss_count ?? 0) > 0
    ? ((data.win_count ?? 0) / ((data.win_count ?? 0) + (data.loss_count ?? 0))) * 100
    : 0
  const errorCats = Object.entries(data.error_categories ?? {}).sort((a, b) => b[1] - a[1])
  const winRegs = Object.entries(data.win_regimes ?? {}).sort((a, b) => b[1] - a[1])
  const wsConnected = (data.ws_status as { status?: string } | null)?.status === 'CONNECTED'
  const crisis = currentState?.crisis_level ?? 0
  const learning = data.learning
  const scanning = data.scanning
  const openPosCount = summary?.open_positions ?? data.portfolio?.total_open ?? openPositions.length
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-white font-bold text-base">Sistem İzleme</h1>
          <p className="text-gray-500 text-xs mt-0.5">Yapay zekanın anlık kararları, hafızası ve öğrenim istatistikleri</p>
        </div>
        <div className="flex items-center gap-3 shrink-0 flex-wrap justify-end">
          <span className={`flex items-center gap-1.5 text-xs font-semibold ${scanning?.active ? 'text-green-400' : 'text-yellow-400'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${scanning?.active ? 'bg-green-400 animate-pulse' : 'bg-yellow-500'}`} />
            {scanning?.active ? `TARAMA AKTİF · ${scanning.universe_size ?? 0} coin` : 'Tarama bekleniyor'}
          </span>
          <span className={`flex items-center gap-1.5 text-xs font-semibold ${wsConnected ? 'text-green-400' : 'text-gray-500'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-green-400' : 'bg-gray-600'}`} />
            WS {wsConnected ? 'BAĞLI' : 'BEKLE'}
          </span>
          <span className={`text-xs font-semibold ${learning?.engine_active ? 'text-purple-400' : 'text-gray-600'}`}>
            🧠 Öğrenme {learning?.engine_active ? 'AKTİF' : '—'}
          </span>
          <span className="text-xs text-gray-600">{lastUpdate ? `${lastUpdate} · 5s` : '5s'}</span>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-9 gap-2">
        <StatPill label="Takip Edilen" value={summary?.tracked_symbols ?? 0} color="text-blue-400" />
        <StatPill label="Açık Pozisyon" value={openPosCount} color="text-yellow-400" highlight={openPosCount > 0} />
        <StatPill label="Poz L/S" value={`${summary?.position_long ?? 0}/${summary?.position_short ?? 0}`} color="text-yellow-300" />
        <StatPill label="Sinyal L/S" value={`${summary?.long ?? 0}/${summary?.short ?? 0}`} color="text-orange-400" />
        <StatPill label="Aktif" value={activeSignals.length} color="text-orange-300" />
        <StatPill label="Ort Güven" value={summary?.avg_confidence ? `${Math.round(summary.avg_confidence * 100)}%` : '—'} color={(summary?.avg_confidence ?? 0) >= 0.7 ? 'text-green-400' : 'text-orange-400'} />
        <StatPill label="Kapat" value={summary?.close_actions ?? 0} color="text-yellow-400" />
        <StatPill label="Öğrenilen Coin" value={learning?.profiles_count ?? 0} color="text-purple-400" />
        <StatPill label="Kriz" value={`L${crisis}`} color={CRISIS_COLORS[crisis] ?? 'text-green-400'} />
      </div>

      {/* Tab Selector */}
      <div className="flex gap-1 bg-gray-900/60 rounded-lg p-1 border border-gray-800/60 flex-wrap">
        {([
          { key: 'live', label: '🔴 Canlı İzleme' },
          { key: 'learning', label: '🧬 AI Öğrenmesi' },
          { key: 'pipeline', label: '⚙️ Karar Süreci' },
          { key: 'memories', label: '🧠 İşlem Hafızası' },
          { key: 'stats', label: '📊 İstatistikler' },
        ] as const).map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex-1 py-2 text-xs rounded transition-colors font-semibold ${tab === t.key
              ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30'
              : 'text-gray-500 hover:text-gray-300'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* TAB: Live */}
      {tab === 'live' && (
        <div className="space-y-4">
          {openPositions.length > 0 && (
            <div className="bg-gray-900 border border-yellow-700/40 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
                <div>
                  <h2 className="text-yellow-400 font-semibold text-sm uppercase tracking-wider">Açık Pozisyonlar — AI Gerekçesi</h2>
                  <p className="text-gray-600 text-xs mt-0.5">Ana sayfa ile aynı kaynak (portfolio:state:v1) · satıra tıkla</p>
                </div>
                <span className="text-yellow-400 font-bold text-lg">{openPositions.length}</span>
              </div>
              <div className="divide-y divide-gray-800/50">
                {openPositions.map(pos => {
                  const exp = expandedPos === pos.symbol
                  return (
                    <div key={pos.symbol}>
                      <button
                        type="button"
                        onClick={() => setExpandedPos(exp ? null : pos.symbol)}
                        className="w-full px-4 py-3 flex flex-wrap items-center gap-3 hover:bg-gray-800/30 text-left text-xs"
                      >
                        <span className="font-bold text-white w-24">{pos.symbol}</span>
                        <span className={`px-2 py-0.5 rounded border font-bold ${DIR_BG[pos.direction] ?? ''}`}>
                          {pos.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
                        </span>
                        <span className={`font-mono font-bold ${(pos.unrealized_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {(pos.unrealized_pct ?? 0) >= 0 ? '+' : ''}{pos.unrealized_pct?.toFixed(2)}%
                        </span>
                        <span className="text-gray-500 flex-1 min-w-[200px] line-clamp-1">{pos.open_reason}</span>
                        <span className="text-gray-600">{exp ? '▲ gizle' : '▼ detay'}</span>
                      </button>
                      {exp && <PositionDecisionPanel pos={pos} />}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* Activity Feed */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
              <div>
                <h2 className="text-orange-400 font-semibold text-sm uppercase tracking-wider">Canlı Aktivite Akışı</h2>
                <p className="text-gray-600 text-xs mt-0.5">{activity.length} son olay · 5s güncelleme</p>
              </div>
              <div className="flex gap-2 text-[10px] text-gray-500">
                <span className="text-blue-400">⟳ tarama</span>
                <span className="text-green-400/70">▲ long</span>
                <span className="text-red-400/70">▼ short</span>
                <span className="text-purple-400">⇄ rejim</span>
              </div>
            </div>
            <div ref={feedRef} className="overflow-y-auto max-h-[520px]">
              {activity.length === 0 ? (
                <div className="p-8 text-center">
                  <p className="text-gray-500 text-sm">Aktivite bekleniyor...</p>
                  <p className="text-gray-600 text-xs mt-1">
                    {scanning?.active
                      ? `${scanning.universe_size} coin taranıyor — sinyal üretilince burada görünür`
                      : 'signal_engine ve learning_engine konteynerlerini başlatın'}
                  </p>
                </div>
              ) : (
                activity.map((ev, i) => <ActivityRow key={i} ev={ev} />)
              )}
            </div>
          </div>

          {/* Right panel: signal snapshot + regime */}
          <div className="space-y-4">
            {/* Current signal snapshot */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h2 className="text-blue-400 font-semibold text-sm uppercase tracking-wider">Anlık Sinyal Dağılımı</h2>
                <p className="text-gray-600 text-xs mt-0.5">{summary?.total ?? 0} coindan toplam</p>
              </div>
              <div className="p-4 space-y-3">
                {[
                  { label: 'LONG ▲', count: summary?.long ?? 0, total: summary?.total ?? 1, color: 'bg-green-500', text: 'text-green-400' },
                  { label: 'SHORT ▼', count: summary?.short ?? 0, total: summary?.total ?? 1, color: 'bg-red-500', text: 'text-red-400' },
                  { label: 'FLAT —', count: summary?.flat ?? 0, total: summary?.total ?? 1, color: 'bg-gray-600', text: 'text-gray-500' },
                ].map(item => (
                  <div key={item.label} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className={`font-bold w-14 ${item.text}`}>{item.label}</span>
                      <div className="flex-1 mx-3 bg-gray-800 rounded-full h-2 overflow-hidden">
                        <div className={`h-full rounded-full ${item.color}`}
                          style={{ width: item.total > 0 ? `${(item.count / item.total) * 100}%` : '0%' }} />
                      </div>
                      <span className={`font-mono font-bold w-10 text-right ${item.text}`}>{item.count}</span>
                    </div>
                  </div>
                ))}
                <div className="pt-2 border-t border-gray-800/60 flex items-center justify-between text-xs text-gray-500">
                  <span>Ort. Güven: <span className="text-white font-mono">{summary?.avg_confidence ? `${Math.round(summary.avg_confidence * 100)}%` : '—'}</span></span>
                  <span>Bağlam: <span className="text-cyan-400">{summary?.context_symbols ?? 0}</span> · Ajan: <span className="text-purple-400">{summary?.agent_symbols ?? 0}</span></span>
                </div>
              </div>
            </div>

            {/* Regime distribution */}
            {currentState && Object.keys(currentState.regime_dist).length > 0 && (
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <h2 className="text-cyan-400 font-semibold text-xs uppercase tracking-wider mb-3">Rejim Dağılımı</h2>
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
                        <span className="text-gray-300 font-mono w-12 text-right">{count} <span className="text-gray-600">({Math.round((count / total) * 100)}%)</span></span>
                      </div>
                    )
                  })}
                </div>
                {currentState.vix != null && (
                  <div className="mt-3 pt-3 border-t border-gray-800/60 flex items-center gap-2 text-xs">
                    <span className="text-gray-500">VIX:</span>
                    <span className={`font-mono font-bold ${currentState.vix > 40 ? 'text-red-400 animate-pulse' : currentState.vix > 25 ? 'text-orange-400' : 'text-green-400'}`}>
                      {currentState.vix.toFixed(1)}
                    </span>
                    <span className={`${CRISIS_COLORS[crisis] ?? 'text-green-400'}`}>· {CRISIS_LABELS[crisis]}</span>
                  </div>
                )}
              </div>
            )}

            {/* Top active signals */}
            {activeSignals.length > 0 && (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-800">
                  <h2 className="text-green-400 font-semibold text-xs uppercase tracking-wider">En Güçlü Aktif Sinyaller</h2>
                </div>
                <div className="divide-y divide-gray-800/40">
                  {activeSignals.map(sig => (
                    <button
                      type="button"
                      key={sig.symbol}
                      onClick={() => {
                        const p = openPositions.find(o => o.symbol === sig.symbol)
                        if (p) setExpandedPos(expandedPos === sig.symbol ? null : sig.symbol)
                        else window.location.href = `/coin/${sig.symbol}`
                      }}
                      className="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-gray-800/20 text-xs text-left"
                    >
                      <span className="font-bold text-white w-20 shrink-0">{sig.symbol}</span>
                      <span className={`px-1.5 rounded font-bold text-[10px] shrink-0 ${DIR_BG[sig.direction] ?? DIR_BG.flat}`}>
                        {sig.direction === 'long' ? '▲' : '▼'} {sig.direction.toUpperCase()}
                      </span>
                      <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
                        <div className={`h-full rounded-full ${sig.direction === 'long' ? 'bg-green-500' : 'bg-red-500'}`}
                          style={{ width: `${Math.round(sig.confidence * 100)}%` }} />
                      </div>
                      <span className={`font-mono font-bold w-10 text-right shrink-0 ${sig.confidence >= 0.8 ? 'text-green-400' : 'text-orange-400'}`}>
                        {Math.round(sig.confidence * 100)}%
                      </span>
                      {sig.rsi != null && (
                        <span className={`font-mono w-12 text-right shrink-0 ${sig.rsi < 32 ? 'text-blue-400' : sig.rsi > 68 ? 'text-orange-400' : 'text-gray-500'}`}>
                          {sig.rsi.toFixed(0)}
                        </span>
                      )}
                      {sig.drift_status && (
                        <span className={`text-[10px] shrink-0 ${DRIFT_COLOR[sig.drift_status] ?? 'text-gray-500'}`}>{sig.drift_status}</span>
                      )}
                      {sig.trade_action === 'hold' && (
                        <span className="text-yellow-500 text-[10px] shrink-0">HOLD</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        </div>
      )}

      {/* TAB: Learning */}
      {tab === 'learning' && (
        <div className="space-y-4">
          {learning?.global && (
            <div className="bg-purple-950/30 border border-purple-700/40 rounded-xl px-4 py-3">
              <p className="text-purple-300 font-bold text-sm">Global öğrenme özeti</p>
              <p className="text-purple-100/80 text-sm mt-1">{learning.global.message}</p>
              {learning.global.top_drivers && learning.global.top_drivers.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {learning.global.top_drivers.map(d => (
                    <span key={d.factor} className="text-xs bg-gray-900/80 px-2 py-1 rounded text-gray-300">
                      {d.factor} · WR {(d.avg_win_rate * 100).toFixed(0)}%
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h2 className="text-purple-400 font-semibold text-sm uppercase tracking-wider">Son öğrenilen dersler</h2>
                <p className="text-gray-600 text-xs mt-0.5">Canlı motor + backtest + işlem sonrası</p>
              </div>
              <div className="max-h-[480px] overflow-y-auto divide-y divide-gray-800/40">
                {(learning?.recent_lessons ?? []).length === 0 ? (
                  <p className="p-6 text-center text-gray-500 text-sm">Henüz ders yok — learning_engine başlatın</p>
                ) : (
                  learning!.recent_lessons!.map((les, i) => (
                    <div key={i} className="px-4 py-3 hover:bg-gray-800/20 text-xs">
                      <div className="flex justify-between gap-2 mb-1">
                        <span className="font-bold text-white">{les.symbol}</span>
                        <span className="text-gray-600 shrink-0">{timeAgo(les.ts)}</span>
                      </div>
                      <span className="text-[10px] text-purple-400 uppercase">{les.source}</span>
                      <p className="text-gray-300 mt-1 leading-relaxed">{les.text}</p>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800">
                <h2 className="text-green-400 font-semibold text-sm uppercase tracking-wider">Coin davranış profilleri</h2>
                <p className="text-gray-600 text-xs mt-0.5">{learning?.profiles_count ?? 0} coin için birikmiş model</p>
              </div>
              <div className="max-h-[480px] overflow-y-auto divide-y divide-gray-800/40">
                {(learning?.profiles ?? []).length === 0 ? (
                  <p className="p-6 text-center text-gray-500 text-sm">Profil oluşuyor (2–5 dk)</p>
                ) : (
                  learning!.profiles!.map(p => (
                    <a key={p.symbol} href={`/coin/${p.symbol}`}
                      className="block px-4 py-3 hover:bg-gray-800/20 text-xs">
                      <div className="flex justify-between items-center mb-1">
                        <span className="font-bold text-white">{p.symbol}</span>
                        <span className="text-gray-500">{p.updates ?? 0} gözlem</span>
                      </div>
                      <p className="text-blue-400">Rejim: {p.current_regime ?? '—'}</p>
                      <p className="text-green-400/90 mt-0.5">Al: {p.best_entry_hint}</p>
                      <p className="text-red-400/90">Kaçın: {p.avoid_hint}</p>
                      {p.drivers && p.drivers[0] && (
                        <p className="text-gray-500 mt-1">
                          En güçlü faktör: {p.drivers[0].factor} → {p.drivers[0].effect} (WR {(p.drivers[0].win_rate * 100).toFixed(0)}%)
                        </p>
                      )}
                    </a>
                  ))
                )}
              </div>
            </div>
          </div>

          {learning?.backtest_log && learning.backtest_log.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <h3 className="text-orange-400 text-xs font-semibold uppercase tracking-wider mb-2">Backtest öğrenme logu</h3>
              <div className="font-mono text-[11px] text-gray-400 space-y-1 max-h-40 overflow-y-auto">
                {learning.backtest_log.map((l, i) => (
                  <p key={i} className={l.level === 'success' ? 'text-green-400/80' : l.level === 'error' ? 'text-red-400/80' : ''}>
                    [{new Date(l.ts * 1000).toLocaleTimeString('tr-TR')}] {l.msg}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB: Pipeline */}
      {tab === 'pipeline' && (
        <div className="space-y-3">
          <div className="bg-gray-900/40 border border-gray-800/60 rounded-lg p-4">
            <h2 className="text-orange-400 font-semibold text-xs uppercase tracking-wider mb-3">Coin Nasıl Bulunuyor? — 8 Aşamalı Karar Süreci</h2>
            <p className="text-gray-500 text-xs mb-4">
              Her coin için bu 8 aşama paralel olarak çalışır. Sistem 500+ coini aynı anda takip eder; yalnızca tüm filtrelerden geçenlerde pozisyon açar.
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
                </div>
              ))}
            </div>
          </div>

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
                          <div className={`h-full rounded-full ${item.color}`} style={{ width: `${(item.count / total) * 100}%` }} />
                        </div>
                        <span className={`w-8 text-right font-mono ${item.text}`}>{item.count}</span>
                      </div>
                    )
                  })}
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
                    <p className="text-gray-600">{g.nodes ?? '—'} nöron · {g.connections ?? '—'} bağ</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB: Memories */}
      {tab === 'memories' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-gray-500 text-xs">Qdrant vektör veritabanındaki son {memories.length} hafıza · Toplam: {data.total_memories ?? 0} kayıt</p>
          </div>
          {loading ? (
            <div className="text-center py-12 text-gray-500 text-sm">Hafıza yükleniyor...</div>
          ) : memories.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
              <p className="text-gray-400 text-sm">Henüz işlem hafızası yok</p>
              <p className="text-gray-600 text-xs mt-2 max-w-xs mx-auto">
                Gölge sistemin işlemleri otopsi ajanı tarafından analiz edilip Qdrant&apos;a kaydedilince burada görünecek.
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
            {[
              { label: 'Toplam Hafıza', value: String(data.total_memories ?? 0), color: 'text-blue-400', sub: 'Qdrant kayıtları' },
              { label: 'Kazanma Oranı', value: winRate > 0 ? `${winRate.toFixed(1)}%` : '—', color: winRate >= 52 ? 'text-green-400' : 'text-orange-400', sub: `${data.win_count ?? 0}K / ${data.loss_count ?? 0}K` },
              { label: 'En İyi Genome', value: genomes?.best_fitness ? genomes.best_fitness.toFixed(4) : '—', color: 'text-purple-400', sub: `${genomes?.count ?? 0} aktif genom` },
              { label: 'Kriz Seviyesi', value: `L${crisis}`, color: CRISIS_COLORS[crisis] ?? 'text-green-400', sub: CRISIS_LABELS[crisis] },
            ].map(item => (
              <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">{item.label}</p>
                <p className={`text-xl font-bold ${item.color}`}>{item.value}</p>
                <p className="text-gray-600 text-xs mt-0.5">{item.sub}</p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <h3 className="text-red-400 font-semibold text-xs uppercase tracking-wider mb-3">En Sık Hata Kategorileri</h3>
              {errorCats.length === 0 ? <p className="text-gray-600 text-xs">Henüz veri yok</p> : (
                <div className="space-y-2">
                  {errorCats.map(([cat, count]) => (
                    <StatBar key={cat} label={cat} value={count} total={errorCats.reduce((s, [, v]) => s + v, 0)} color="bg-red-500" />
                  ))}
                </div>
              )}
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <h3 className="text-green-400 font-semibold text-xs uppercase tracking-wider mb-3">Kazanılan Rejimler</h3>
              {winRegs.length === 0 ? <p className="text-gray-600 text-xs">Henüz veri yok</p> : (
                <div className="space-y-2">
                  {winRegs.map(([regime, count]) => (
                    <StatBar key={regime} label={regime.replace('_', ' ')} value={count} total={winRegs.reduce((s, [, v]) => s + v, 0)} color="bg-green-500" />
                  ))}
                </div>
              )}
            </div>
          </div>

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
                              <div className={`h-full rounded-full ${wr >= 52 ? 'bg-green-500' : 'bg-red-500'}`} style={{ width: `${wr}%` }} />
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

          <div className="bg-gray-900/60 border border-gray-800/60 rounded-lg p-4 space-y-3 text-xs text-gray-400">
            <h3 className="text-white font-semibold text-sm">Sistem Nasıl Öğreniyor?</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                { icon: '🔁', title: 'NEAT Evrimi', text: 'Her 3 saatte bir genomlar üzerinde mutasyon ve çaprazlama uygulanır. Daha yüksek Sharpe/WR oranına sahip genomlar hayatta kalır.' },
                { icon: '🏆', title: 'Ajan Ağırlıklandırması', text: 'Her ajan ne kadar doğru tahmin yaptığı takip edilir. Doğru tahmin eden ajanın oyuna verilen ağırlık artar.' },
                { icon: '🗃️', title: 'Vektör Hafızası', text: 'Her tamamlanan işlem embedding\'e çevrilip Qdrant\'ta saklanır. Yeni sinyal üretilirken benzer geçmiş durumlar bağlam olarak kullanılır.' },
                { icon: '📐', title: 'PPO Takviyeli Öğrenme', text: '500K adım boyunca gymnasium ortamında eğitilen PPO ajanı pozisyon boyutlandırma ve giriş zamanlamasını optimize eder.' },
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
