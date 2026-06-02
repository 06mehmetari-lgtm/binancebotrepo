'use client'
import { useState, useRef, useEffect, useCallback } from 'react'

// ── Types ────────────────────────────────────────────────────────────────────

interface Indicators {
  rsi: number | null
  macd_hist: number | null
  bb_pct: number | null
  atr_pct: number | null
  funding_rate: number | null
  oi_change: number | null
  fear_greed: number | null
  vix: number | null
  ls_ratio: number | null
  drift_status: string
  ml_score: number | null
  volume_ratio: number | null
}

interface AgentVote {
  agent: string
  agent_tr: string
  vote: string
  confidence: number
  reasoning: string
}

interface Verdict {
  direction: string
  confidence: number
  reasoning: string
  dissent_risk: string
}

interface Signal {
  direction: string
  confidence: number
  kelly: number
  stop_pct: number | null
  tp_pct: number | null
  risk_reward: number | null
  age_s: number | null
}

interface DocInsights {
  score: number
  rating: string
  commentary: string
  matched_rules: string[]
  docs_used: number
  provider: string
}

interface AnalysisData {
  symbol: string
  price: number
  has_features: boolean
  features_age_s: number | null
  regime: string | null
  crisis_level: number
  indicators: Indicators | null
  votes: AgentVote[]
  verdict: Verdict | null
  signal: Signal | null
  rl: { direction: string; confidence: number } | null
  doc_insights: DocInsights | null
}

type Message =
  | { type: 'user'; text: string; id: string }
  | { type: 'bot'; text: string; id: string }
  | { type: 'analysis'; data: AnalysisData; id: string }
  | { type: 'error'; text: string; id: string }

// ── Helpers ──────────────────────────────────────────────────────────────────

function dirColor(d: string) {
  if (d === 'long') return 'text-green-400'
  if (d === 'short') return 'text-red-400'
  return 'text-gray-400'
}

function dirBadge(d: string) {
  if (d === 'long') return 'bg-green-500/20 border-green-500/40 text-green-300'
  if (d === 'short') return 'bg-red-500/20 border-red-500/40 text-red-300'
  return 'bg-gray-800/60 border-gray-700 text-gray-400'
}

function dirLabel(d: string) {
  if (d === 'long') return 'LONG ▲'
  if (d === 'short') return 'SHORT ▼'
  return 'BEKLE —'
}

function regimeTR(r: string | null) {
  const m: Record<string, string> = {
    trending_up: 'Yükselen Trend ↗',
    trending_down: 'Düşen Trend ↘',
    ranging: 'Yatay Seyir ↔',
    volatile: 'Volatil ⚡',
  }
  return r ? (m[r] ?? r) : '—'
}

function crisisInfo(lvl: number) {
  const labels = ['Normal', 'Dikkat', 'Yüksek Risk', 'Kriz', 'Ekstrem Kriz']
  const colors = ['text-green-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-600']
  const icons = ['✓', '⚠', '⚠⚠', '⛔', '⛔⛔']
  const i = Math.min(lvl, 4)
  return { label: `${icons[i]} ${labels[i]}`, color: colors[i] }
}

function fmtPrice(p: number) {
  if (!p) return '—'
  if (p >= 10000) return `$${p.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
  if (p >= 1) return `$${p.toFixed(3)}`
  return `$${p.toFixed(6)}`
}

function fmtAge(s: number | null) {
  if (s == null) return '—'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}dk`
  return `${Math.round(s / 3600)}sa`
}

function ConfBar({ val, dir }: { val: number; dir: string }) {
  const pct = Math.min(100, val * 100)
  const color = dir === 'long' ? 'bg-green-500' : dir === 'short' ? 'bg-red-500' : 'bg-gray-500'
  return (
    <div className="w-full bg-gray-800 rounded-full h-1">
      <div className={`${color} h-1 rounded-full`} style={{ width: `${pct}%` }} />
    </div>
  )
}

// ── Analysis Card ────────────────────────────────────────────────────────────

function AnalysisCard({ data }: { data: AnalysisData }) {
  const [showAllVotes, setShowAllVotes] = useState(false)

  const {
    symbol, price, has_features, features_age_s,
    regime, crisis_level, indicators, votes, verdict, signal, rl, doc_insights,
  } = data

  const finalDir = signal?.direction ?? verdict?.direction ?? 'flat'
  const crisis = crisisInfo(crisis_level)
  const longN = votes.filter(v => v.vote === 'long').length
  const shortN = votes.filter(v => v.vote === 'short').length
  const flatN = votes.filter(v => v.vote === 'flat').length
  const displayedVotes = showAllVotes ? votes : votes.slice(0, 5)

  return (
    <div className="border border-gray-700/60 rounded-xl overflow-hidden bg-gray-900/70 w-full max-w-2xl">

      {/* ── Header ── */}
      <div className={`px-4 py-3 border-b flex items-start justify-between gap-3 ${
        finalDir === 'long' ? 'bg-green-950/40 border-green-800/30'
        : finalDir === 'short' ? 'bg-red-950/40 border-red-800/30'
        : 'bg-gray-800/40 border-gray-700/40'
      }`}>
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white font-bold text-base tracking-tight">{symbol}</span>
            <span className={`text-xs font-bold px-2 py-0.5 rounded border ${dirBadge(finalDir)}`}>
              {dirLabel(finalDir)}
            </span>
            {!has_features && (
              <span className="text-xs px-2 py-0.5 rounded border bg-yellow-900/30 border-yellow-700/40 text-yellow-400">
                Veri Yok
              </span>
            )}
          </div>
          <div className="mt-1 flex items-center gap-3 text-sm">
            <span className="text-white font-mono">{fmtPrice(price)}</span>
            {signal && (
              <span className={`font-semibold ${dirColor(finalDir)}`}>
                %{(signal.confidence * 100).toFixed(0)} güven
              </span>
            )}
          </div>
        </div>
        <div className="text-right text-xs shrink-0">
          <div className={crisis.color}>{crisis.label}</div>
          {features_age_s != null && (
            <div className="text-gray-600 mt-0.5">veri: {fmtAge(features_age_s)} önce</div>
          )}
        </div>
      </div>

      <div className="p-4 space-y-5">

        {/* ── Piyasa Durumu ── */}
        <section>
          <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-2">
            📊 Piyasa Durumu
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="bg-gray-800/50 border border-gray-700/40 rounded px-2 py-1">
              Rejim: <span className="text-orange-300">{regimeTR(regime)}</span>
            </span>
            {indicators && (
              <span className="bg-gray-800/50 border border-gray-700/40 rounded px-2 py-1">
                Drift:{' '}
                <span className={indicators.drift_status === 'DRIFTING' ? 'text-yellow-400' : 'text-green-400'}>
                  {indicators.drift_status}
                </span>
              </span>
            )}
            {indicators?.ml_score != null && (
              <span className="bg-gray-800/50 border border-gray-700/40 rounded px-2 py-1">
                ML: <span className="text-blue-300">{indicators.ml_score.toFixed(3)}</span>
              </span>
            )}
            {indicators?.volume_ratio != null && (
              <span className="bg-gray-800/50 border border-gray-700/40 rounded px-2 py-1">
                Hacim: <span className={indicators.volume_ratio > 1.5 ? 'text-green-400' : 'text-gray-400'}>
                  {indicators.volume_ratio.toFixed(2)}x
                </span>
              </span>
            )}
          </div>
        </section>

        {/* ── Teknik Göstergeler ── */}
        {indicators && (
          <section>
            <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-2">
              📈 Teknik Göstergeler
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-xs">

              {/* RSI */}
              {indicators.rsi != null && (() => {
                const v = indicators.rsi
                const c = v < 30 ? 'text-blue-400' : v > 70 ? 'text-red-400' : 'text-gray-200'
                const lbl = v < 30 ? 'Aşırı Satım' : v > 70 ? 'Aşırı Alım' : 'Normal'
                return (
                  <div className="bg-gray-800/40 rounded px-2.5 py-2">
                    <div className="text-gray-500 mb-0.5">RSI (14)</div>
                    <div className={c}>{v.toFixed(1)} <span className="text-gray-500">{lbl}</span></div>
                  </div>
                )
              })()}

              {/* MACD */}
              {indicators.macd_hist != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">MACD Hist</div>
                  <div className={indicators.macd_hist >= 0 ? 'text-green-400' : 'text-red-400'}>
                    {indicators.macd_hist >= 0 ? '+' : ''}{indicators.macd_hist.toFixed(4)}
                    <span className="text-gray-500 ml-1">
                      {indicators.macd_hist >= 0 ? '↑ Momentum' : '↓ Momentum'}
                    </span>
                  </div>
                </div>
              )}

              {/* Bollinger */}
              {indicators.bb_pct != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">Bollinger %B</div>
                  <div className={indicators.bb_pct > 0.8 ? 'text-red-400' : indicators.bb_pct < 0.2 ? 'text-blue-400' : 'text-gray-200'}>
                    %{(indicators.bb_pct * 100).toFixed(0)}
                    <span className="text-gray-500 ml-1">
                      {indicators.bb_pct > 0.8 ? 'Üst Band' : indicators.bb_pct < 0.2 ? 'Alt Band' : 'Orta'}
                    </span>
                  </div>
                </div>
              )}

              {/* ATR */}
              {indicators.atr_pct != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">ATR Volatilite</div>
                  <div className={indicators.atr_pct > 2 ? 'text-orange-400' : 'text-gray-200'}>
                    %{indicators.atr_pct.toFixed(2)}
                  </div>
                </div>
              )}

              {/* Funding */}
              {indicators.funding_rate != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">Funding Rate</div>
                  <div className={indicators.funding_rate > 0.0005 ? 'text-orange-400' : indicators.funding_rate < -0.0005 ? 'text-blue-400' : 'text-gray-200'}>
                    {(indicators.funding_rate * 100).toFixed(4)}%
                    <span className="text-gray-500 ml-1">
                      {indicators.funding_rate > 0.0005 ? 'Long baskı' : indicators.funding_rate < -0.0005 ? 'Short baskı' : ''}
                    </span>
                  </div>
                </div>
              )}

              {/* OI */}
              {indicators.oi_change != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">Açık Pozisyon</div>
                  <div className={indicators.oi_change > 0 ? 'text-green-400' : 'text-red-400'}>
                    {indicators.oi_change > 0 ? '+' : ''}{(indicators.oi_change * 100).toFixed(2)}%
                  </div>
                </div>
              )}

              {/* Fear & Greed */}
              {indicators.fear_greed != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">Korku/Açgözlülük</div>
                  <div className={
                    indicators.fear_greed < 25 ? 'text-blue-400' :
                    indicators.fear_greed < 45 ? 'text-blue-300' :
                    indicators.fear_greed > 75 ? 'text-red-400' :
                    indicators.fear_greed > 55 ? 'text-orange-400' : 'text-gray-200'
                  }>
                    {indicators.fear_greed}/100
                    <span className="text-gray-500 ml-1">
                      {indicators.fear_greed < 25 ? 'Aşırı Korku' :
                       indicators.fear_greed < 45 ? 'Korku' :
                       indicators.fear_greed > 75 ? 'Aşırı Açgözlülük' :
                       indicators.fear_greed > 55 ? 'Açgözlülük' : 'Nötr'}
                    </span>
                  </div>
                </div>
              )}

              {/* VIX */}
              {indicators.vix != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">VIX (Risk)</div>
                  <div className={indicators.vix > 30 ? 'text-red-400' : indicators.vix > 20 ? 'text-yellow-400' : 'text-green-400'}>
                    {indicators.vix.toFixed(1)}
                    <span className="text-gray-500 ml-1">
                      {indicators.vix > 40 ? 'Kriz' : indicators.vix > 30 ? 'Yüksek' : indicators.vix > 20 ? 'Orta' : 'Düşük'}
                    </span>
                  </div>
                </div>
              )}

              {/* L/S Ratio */}
              {indicators.ls_ratio != null && (
                <div className="bg-gray-800/40 rounded px-2.5 py-2">
                  <div className="text-gray-500 mb-0.5">Long/Short Oran</div>
                  <div className={indicators.ls_ratio > 1.2 ? 'text-green-400' : indicators.ls_ratio < 0.8 ? 'text-red-400' : 'text-gray-200'}>
                    {indicators.ls_ratio.toFixed(2)}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* ── Ajan Oyları ── */}
        {votes.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-2">
              <div className="text-[11px] text-gray-500 uppercase tracking-widest">
                🤖 Ajan Oyları ({votes.length} ajan)
              </div>
              <div className="text-xs flex gap-3">
                <span className="text-green-400">▲ {longN}</span>
                <span className="text-red-400">▼ {shortN}</span>
                <span className="text-gray-500">— {flatN}</span>
              </div>
            </div>

            <div className="space-y-2">
              {displayedVotes.map((v, i) => (
                <div key={i} className="bg-gray-800/40 border border-gray-700/30 rounded-lg px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <span className="text-gray-200 text-xs font-semibold">{v.agent_tr}</span>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-bold ${dirColor(v.vote)}`}>
                        {dirLabel(v.vote)}
                      </span>
                      <span className="text-gray-500 text-xs">%{(v.confidence * 100).toFixed(0)}</span>
                    </div>
                  </div>
                  <ConfBar val={v.confidence} dir={v.vote} />
                  {v.reasoning && (
                    <p className="text-gray-500 text-[11px] mt-2 leading-relaxed">
                      {v.reasoning.slice(0, 200)}
                    </p>
                  )}
                </div>
              ))}
            </div>

            {votes.length > 5 && (
              <button
                onClick={() => setShowAllVotes(s => !s)}
                className="text-xs text-orange-400 hover:text-orange-300 mt-2 transition-colors"
              >
                {showAllVotes ? 'Daha az göster ▲' : `${votes.length - 5} ajan daha ▼`}
              </button>
            )}
          </section>
        )}

        {/* ── AI Tartışma Kararı ── */}
        {verdict?.reasoning && (
          <section>
            <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-2">
              💬 AI Tartışma Kararı
            </div>
            <div className="bg-gray-800/40 border border-gray-700/30 rounded-lg p-3">
              <p className="text-gray-200 text-xs leading-relaxed">{verdict.reasoning}</p>
              {verdict.dissent_risk && (
                <p className="text-yellow-400/80 text-[11px] mt-2.5 pt-2.5 border-t border-gray-700/40 leading-relaxed">
                  ⚠ Muhalefet riski: {verdict.dissent_risk}
                </p>
              )}
            </div>
          </section>
        )}

        {/* ── Sinyal & Risk ── */}
        {signal && (
          <section>
            <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-2">
              🎯 Sinyal & Risk Metrikleri
            </div>
            <div className="grid grid-cols-3 gap-1.5 text-xs">
              <div className="bg-gray-800/40 rounded px-2 py-2 text-center">
                <div className="text-gray-500 text-[10px] mb-1">Güven</div>
                <div className={`font-bold ${dirColor(signal.direction)}`}>
                  %{(signal.confidence * 100).toFixed(0)}
                </div>
              </div>
              <div className="bg-gray-800/40 rounded px-2 py-2 text-center">
                <div className="text-gray-500 text-[10px] mb-1">Kelly</div>
                <div className="text-orange-300 font-bold">%{(signal.kelly * 100).toFixed(1)}</div>
              </div>
              {signal.risk_reward != null && (
                <div className="bg-gray-800/40 rounded px-2 py-2 text-center">
                  <div className="text-gray-500 text-[10px] mb-1">R:R Oranı</div>
                  <div className="text-blue-300 font-bold">1:{signal.risk_reward.toFixed(2)}</div>
                </div>
              )}
              {signal.stop_pct != null && (
                <div className="bg-gray-800/40 rounded px-2 py-2 text-center">
                  <div className="text-gray-500 text-[10px] mb-1">Stop Loss</div>
                  <div className="text-red-400">%{Math.abs(signal.stop_pct).toFixed(2)}</div>
                </div>
              )}
              {signal.tp_pct != null && (
                <div className="bg-gray-800/40 rounded px-2 py-2 text-center">
                  <div className="text-gray-500 text-[10px] mb-1">Take Profit</div>
                  <div className="text-green-400">%{Math.abs(signal.tp_pct).toFixed(2)}</div>
                </div>
              )}
              {signal.age_s != null && (
                <div className="bg-gray-800/40 rounded px-2 py-2 text-center">
                  <div className="text-gray-500 text-[10px] mb-1">Sinyal Yaşı</div>
                  <div className="text-gray-300">{fmtAge(signal.age_s)}</div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* ── RL Ajanı ── */}
        {rl && (
          <div className="flex items-center gap-2 text-xs bg-blue-900/20 border border-blue-800/30 rounded px-3 py-2">
            <span className="text-blue-400 font-medium">🧠 PPO RL Ajanı:</span>
            <span className={`font-bold ${dirColor(rl.direction)}`}>{dirLabel(rl.direction)}</span>
            <span className="text-gray-500">· %{(rl.confidence * 100).toFixed(0)} güven</span>
          </div>
        )}

        {/* ── Döküman Analizi ── */}
        {doc_insights && (
          <section>
            <div className="text-[11px] text-gray-500 uppercase tracking-widest mb-2">
              📚 Döküman Analizi ({doc_insights.docs_used} döküman · {doc_insights.provider})
            </div>
            <div className="bg-gray-800/40 border border-gray-700/30 rounded-xl p-3 space-y-3">

              {/* Score + Rating */}
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1 text-[10px] text-gray-500">
                    <span>Döküman Skoru</span>
                    <span className="font-bold text-white">{doc_insights.score}/100</span>
                  </div>
                  <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${
                        doc_insights.score >= 70 ? 'bg-green-500' :
                        doc_insights.score >= 40 ? 'bg-yellow-500' : 'bg-red-500'
                      }`}
                      style={{ width: `${doc_insights.score}%` }}
                    />
                  </div>
                </div>
                <span className={`text-xs font-bold px-2.5 py-1 rounded-lg border whitespace-nowrap ${
                  doc_insights.rating.includes('GÜÇLÜ AL') ? 'bg-green-900/50 border-green-700/50 text-green-300' :
                  doc_insights.rating.includes('AL')        ? 'bg-green-900/30 border-green-800/40 text-green-400' :
                  doc_insights.rating.includes('GÜÇLÜ SAT') ? 'bg-red-900/50 border-red-700/50 text-red-300' :
                  doc_insights.rating.includes('SAT')        ? 'bg-red-900/30 border-red-800/40 text-red-400' :
                                                               'bg-gray-800 border-gray-700 text-gray-400'
                }`}>
                  {doc_insights.rating}
                </span>
              </div>

              {/* Commentary */}
              {doc_insights.commentary && (
                <p className="text-gray-300 text-xs leading-relaxed border-t border-gray-700/40 pt-2">
                  {doc_insights.commentary}
                </p>
              )}

              {/* Matched rules */}
              {doc_insights.matched_rules.length > 0 && (
                <div className="space-y-1 border-t border-gray-700/40 pt-2">
                  <p className="text-[10px] text-gray-600 uppercase tracking-wider mb-1">Eşleşen Kurallar</p>
                  {doc_insights.matched_rules.map((rule, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-[11px] text-gray-400">
                      <span className="text-orange-500 mt-0.5 shrink-0">▸</span>
                      <span>{rule}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {/* ── Karar Zinciri ── */}
        <div className="border-t border-gray-800 pt-3">
          <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-1.5">Karar Zinciri</div>
          <div className="flex flex-wrap gap-1 items-center text-[11px]">
            <span className={has_features ? 'text-green-500' : 'text-red-500'}>
              feature_engine {has_features ? '✓' : '✗'}
            </span>
            <span className="text-gray-700">→</span>
            <span className={regime ? 'text-green-500' : 'text-gray-600'}>
              context {regime ? `✓ (${regimeTR(regime)})` : '—'}
            </span>
            <span className="text-gray-700">→</span>
            <span className={votes.length > 0 ? 'text-green-500' : 'text-gray-600'}>
              {votes.length > 0 ? `${votes.length} ajan ✓` : 'ajanlar —'}
            </span>
            <span className="text-gray-700">→</span>
            <span className={
              signal
                ? signal.direction !== 'flat'
                  ? 'text-green-500'
                  : 'text-yellow-500'
                : 'text-gray-600'
            }>
              signal {signal ? `(${dirLabel(signal.direction)})` : '—'}
            </span>
            <span className="text-gray-700">→</span>
            <span className="text-gray-600">immunity → shadow → OMS</span>
          </div>
        </div>

      </div>
    </div>
  )
}

// ── Quick Symbols ────────────────────────────────────────────────────────────

const QUICK = [
  'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
  'AVAXUSDT', 'ADAUSDT', 'LINKUSDT', 'SUIUSDT', 'DOGEUSDT',
  'NEARUSDT', 'TAOUSDT', 'HYPEUSDT', 'ARBUSDT', 'OPUSDT',
]

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AIPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      type: 'bot',
      text: 'Merhaba! Ben Prometheus AI Analiz Asistanıyım. Herhangi bir coin yazın — sistemin 9 yapay zeka ajanının tüm analizini, teknik göstergelerini ve karar zincirini gerçek zamanlı olarak göstereyim.\n\nÖrnek: "BTC", "ETHUSDT", "Solana nasıl?", "SOL analizi"',
      id: 'welcome',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<AnalysisData[]>([])
  const [historySymbol, setHistorySymbol] = useState('')
  const [showHistory, setShowHistory] = useState(false)

  const loadHistory = useCallback(async (symbol: string) => {
    if (!symbol) return
    try {
      const res = await fetch(`/api/analysis-history?symbol=${symbol}`)
      const data = await res.json()
      if (data.history?.length > 0) {
        setHistory(data.history)
        setHistorySymbol(symbol)
        setShowHistory(true)
      }
    } catch { /* ignore */ }
  }, [])
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const analyze = useCallback(async (query: string) => {
    if (!query.trim() || loading) return

    setMessages(prev => [...prev, { type: 'user', text: query.trim(), id: `u-${Date.now()}` }])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(`/api/ai-analysis?q=${encodeURIComponent(query.trim())}`)
      const data = await res.json()

      if (data.error === 'no_symbol') {
        setMessages(prev => [...prev, {
          type: 'error',
          text: 'Hangi coini analiz etmemi istiyorsunuz? Örnek: "BTC", "ETHUSDT", "Solana"',
          id: `e-${Date.now()}`,
        }])
      } else {
        setMessages(prev => [...prev, {
          type: 'analysis',
          data,
          id: `a-${Date.now()}`,
        }])
        // Load history for this coin in background
        if (data.symbol) loadHistory(data.symbol)
      }
    } catch {
      setMessages(prev => [...prev, {
        type: 'error',
        text: 'API bağlantı hatası. Sunucuyu kontrol edin.',
        id: `e-${Date.now()}`,
      }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [loading])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    analyze(input)
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col" style={{ height: 'calc(100vh - 100px)' }}>

      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-white">🤖 AI Analiz Asistanı</h1>
          <p className="text-gray-500 text-xs mt-0.5">
            9 yapay zeka ajanı · Gerçek zamanlı Redis verisi · Tam karar zinciri
          </p>
        </div>
        <div className="text-xs text-gray-600 text-right hidden sm:block">
          <div>feature_engine → context</div>
          <div>→ 9 ajan → signal → immunity</div>
          <div>→ shadow → OMS</div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1 pb-2">
        {messages.map(msg => {
          if (msg.type === 'user') {
            return (
              <div key={msg.id} className="flex justify-end">
                <div className="bg-orange-500/20 border border-orange-500/30 text-orange-100 rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm max-w-xs">
                  {msg.text}
                </div>
              </div>
            )
          }
          if (msg.type === 'bot') {
            return (
              <div key={msg.id} className="flex justify-start">
                <div className="bg-gray-800/60 border border-gray-700/40 rounded-2xl rounded-tl-sm px-4 py-3 text-sm max-w-lg">
                  <div className="text-orange-400 text-xs font-bold mb-1.5">⚡ PROMETHEUS AI</div>
                  <p className="text-gray-300 leading-relaxed whitespace-pre-line">{msg.text}</p>
                </div>
              </div>
            )
          }
          if (msg.type === 'error') {
            return (
              <div key={msg.id} className="flex justify-start">
                <div className="bg-red-900/30 border border-red-700/40 text-red-300 rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm max-w-sm">
                  ⚠ {msg.text}
                </div>
              </div>
            )
          }
          if (msg.type === 'analysis') {
            return (
              <div key={msg.id} className="flex justify-start w-full">
                <AnalysisCard data={msg.data} />
              </div>
            )
          }
          return null
        })}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-800/60 border border-gray-700/40 rounded-2xl rounded-tl-sm px-5 py-3 text-sm text-gray-400 flex items-center gap-2">
              <span className="flex gap-1">
                {[0, 1, 2].map(i => (
                  <span
                    key={i}
                    className="w-1.5 h-1.5 bg-orange-400 rounded-full inline-block"
                    style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
                  />
                ))}
              </span>
              <span>Analiz ediliyor...</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Quick buttons */}
      <div className="py-2 border-t border-gray-800">
        <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-1.5">Hızlı Erişim</div>
        <div className="flex flex-wrap gap-1.5">
          {QUICK.map(sym => (
            <button
              key={sym}
              onClick={() => analyze(sym)}
              disabled={loading}
              className="text-xs px-2.5 py-1 rounded-lg bg-gray-800/60 hover:bg-gray-700/60 text-gray-400 hover:text-white border border-gray-700/40 hover:border-gray-600 transition-all disabled:opacity-40"
            >
              {sym.replace('USDT', '')}
            </button>
          ))}
        </div>
      </div>

      {/* Analysis History Panel */}
      {showHistory && history.length > 0 && (
        <div className="border-t border-gray-800 py-2">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-semibold">
              📊 {historySymbol} — Son {history.length} Analiz Geçmişi
            </span>
            <button onClick={() => setShowHistory(false)} className="text-gray-600 hover:text-gray-400 text-xs">✕</button>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {history.slice(0, 10).map((h, i) => {
              const dir = h.verdict?.direction ?? h.signal?.direction ?? 'flat'
              const conf = h.verdict?.confidence ?? h.signal?.confidence ?? 0
              const ts = h.timestamp ? new Date(h.timestamp * 1000).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '—'
              const bg = dir === 'long' ? 'border-green-700/40 bg-green-900/10' : dir === 'short' ? 'border-red-700/40 bg-red-900/10' : 'border-gray-700/40'
              const col = dir === 'long' ? 'text-green-400' : dir === 'short' ? 'text-red-400' : 'text-gray-400'
              return (
                <div key={i} className={`flex-shrink-0 border rounded-lg px-3 py-2 text-center min-w-[80px] ${bg}`}>
                  <div className={`text-xs font-bold ${col}`}>{dir.toUpperCase()}</div>
                  <div className="text-gray-500 text-[10px]">{(conf * 100).toFixed(0)}%</div>
                  <div className="text-gray-600 text-[10px]">{ts}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex gap-2 pt-2">
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="BTC, ETHUSDT, Solana, AVAX analizi..."
          disabled={loading}
          className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-orange-500/50 transition-colors disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-5 py-2.5 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/40 text-orange-400 rounded-xl text-sm font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Analiz Et
        </button>
      </form>

      <style jsx>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-5px); }
        }
      `}</style>
    </div>
  )
}
