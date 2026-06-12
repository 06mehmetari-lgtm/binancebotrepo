'use client'

import type { PositionDecision } from '@/lib/positions'
import { SymbolTradeHistory } from '@/components/SymbolTradeHistory'
import { PositionTripleChart } from '@/components/PositionTripleChart'

const DIR_STYLE: Record<string, string> = {
  long: 'text-green-400 bg-green-900/30 border-green-800/50',
  short: 'text-red-400 bg-red-900/30 border-red-800/50',
}

const AGENT_EMOJI: Record<string, string> = {
  bull_agent: '🐂',
  bear_agent: '🐻',
  neutral_agent: '⚖️',
  technical_agent: '📊',
  news_agent: '📰',
  macro_agent: '🌐',
  onchain_agent: '⛓️',
  risk_agent: '🛡️',
  evolution_agent: '🧬',
  debate_agent: '⚖️',
}

function pct(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${Math.round(n <= 1 ? n * 100 : n)}%`
}

export function PositionDecisionPanel({ pos }: { pos: PositionDecision }) {
  const entry = pos.entry_signal ?? {}
  const cur = pos.current_signal ?? {}
  const probs = (pos.verdict?.probabilities ?? cur.probabilities) as {
    long_pct?: number
    short_pct?: number
    ai_confidence_pct?: number
  } | undefined
  const targets = (pos.verdict?.targets ?? cur.targets) as Record<string, unknown> | undefined

  return (
    <div className="px-4 py-4 bg-gray-950/80 border-t border-gray-800/60 space-y-4 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-2 py-0.5 rounded border font-bold ${DIR_STYLE[pos.direction] ?? ''}`}>
          {pos.direction === 'long' ? '▲ LONG' : '▼ SHORT'}
        </span>
        <span className="text-gray-500">Kaynak: <span className="text-white">{pos.source}</span></span>
        {pos.trade_action && (
          <span className="text-orange-400">Anlık aksiyon: {pos.trade_action}</span>
        )}
        {entry.source != null && (
          <span className="text-gray-500">Giriş motoru: <span className="text-blue-400">{String(entry.source)}</span></span>
        )}
      </div>

      <PositionTripleChart symbol={pos.symbol} />

      {pos.guard && (
        <div className={`rounded-lg p-3 border ${
          pos.guard.action === 'emergency_close'
            ? 'bg-red-950/60 border-red-500/60'
            : pos.guard.action === 'close'
              ? 'bg-orange-950/50 border-orange-600/50'
              : pos.guard.urgency === 'medium'
                ? 'bg-yellow-950/40 border-yellow-700/40'
                : 'bg-green-950/30 border-green-800/40'
        }`}>
          <p className="text-[10px] uppercase tracking-wider font-bold text-cyan-400 mb-1">
            🛡️ AI Pozisyon Koruyucu — {pos.guard.action?.toUpperCase()} ({pos.guard.urgency})
          </p>
          <p className="text-gray-200 leading-relaxed">{pos.guard.reason}</p>
          <p className="text-gray-500 mt-1 font-mono text-[10px]">
            PnL {pos.guard.unrealized_pct != null ? `${pos.guard.unrealized_pct >= 0 ? '+' : ''}${pos.guard.unrealized_pct.toFixed(2)}%` : '—'}
            {' · '}AI güven {pct(pos.guard.ai_confidence)}
          </p>
        </div>
      )}

      <div className="bg-gray-900/60 border border-orange-800/40 rounded-lg p-3">
        <p className="text-orange-400 font-semibold text-[10px] uppercase tracking-wider mb-1">Neden bu pozisyon açıldı?</p>
        <p className="text-gray-200 leading-relaxed">{pos.open_reason}</p>
        {pos.verdict?.dissent_risk && (
          <p className="text-yellow-500/80 mt-2">
            <span className="font-semibold">Muhalefet riski:</span> {pos.verdict.dissent_risk}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="bg-gray-800/40 rounded p-2">
          <p className="text-gray-500 text-[10px]">Giriş güveni</p>
          <p className="text-white font-mono font-bold">{pct(entry.confidence ?? entry.confidence_pct)}</p>
        </div>
        <div className="bg-gray-800/40 rounded p-2">
          <p className="text-gray-500 text-[10px]">Anlık güven</p>
          <p className="text-white font-mono font-bold">{pct(cur.confidence ?? pos.verdict?.confidence)}</p>
        </div>
        <div className="bg-gray-800/40 rounded p-2">
          <p className="text-gray-500 text-[10px]">Rejim (giriş)</p>
          <p className="text-blue-300 font-mono">{String(entry.regime ?? '—')}</p>
        </div>
        <div className="bg-gray-800/40 rounded p-2">
          <p className="text-gray-500 text-[10px]">Drift</p>
          <p className="text-gray-300 font-mono">{String(entry.drift_status ?? cur.drift_status ?? '—')}</p>
        </div>
      </div>

      {probs && (
        <div className="flex flex-wrap gap-3 text-[11px]">
          {probs.long_pct != null && (
            <span className="text-green-400">Long tahmin: {probs.long_pct}%</span>
          )}
          {probs.short_pct != null && (
            <span className="text-red-400">Short tahmin: {probs.short_pct}%</span>
          )}
          {probs.ai_confidence_pct != null && (
            <span className="text-purple-400">AI güven: {probs.ai_confidence_pct}%</span>
          )}
        </div>
      )}

      {pos.ladder && (
        <div className="bg-cyan-950/30 border border-cyan-800/40 rounded-lg p-3">
          <p className="text-cyan-400 text-[10px] uppercase tracking-wider font-bold mb-2">
            Kademe {pos.ladder.tier ?? 1} — al/sat planı
          </p>
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            <div>
              <p className="text-gray-500">Kâr hedefi</p>
              <p className="text-green-400 font-mono">%{pos.ladder.take_profit_pct ?? '—'}</p>
            </div>
            <div>
              <p className="text-gray-500">Stop</p>
              <p className="text-red-400 font-mono">%{pos.ladder.stop_loss_pct ?? '—'}</p>
            </div>
            <div>
              <p className="text-gray-500">Giriş güveni</p>
              <p className="text-white font-mono">
                {pos.ladder.entry_confidence != null
                  ? `${Math.round(pos.ladder.entry_confidence * 100)}%`
                  : '—'}
              </p>
            </div>
          </div>
          {pos.ladder.entry_reason && (
            <p className="text-gray-400 mt-2">{pos.ladder.entry_reason}</p>
          )}
        </div>
      )}

      {targets && (targets.stop_loss != null || targets.take_profit != null) && (
        <p className="text-gray-500">
          Hedef SL/TP:{' '}
          <span className="text-red-400 font-mono">{targets.stop_loss != null ? String(targets.stop_loss) : '—'}</span>
          {' / '}
          <span className="text-green-400 font-mono">{targets.take_profit != null ? String(targets.take_profit) : '—'}</span>
        </p>
      )}

      <div>
        <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-2">Al / sat geçmişi</p>
        <SymbolTradeHistory symbol={pos.symbol} />
      </div>

      {(pos.votes?.length ?? 0) > 0 && (
        <div>
          <p className="text-gray-500 text-[10px] uppercase tracking-wider mb-2">9 Ajan oyları (giriş / güncel)</p>
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {pos.votes!.map(v => (
              <div key={v.agent} className="flex gap-2 items-start bg-gray-800/30 rounded px-2 py-1.5">
                <span className="shrink-0">{AGENT_EMOJI[v.agent] ?? '🤖'}</span>
                <div className="min-w-0 flex-1">
                  <span className="text-gray-400 font-mono">{v.agent.replace('_agent', '')}</span>
                  <span className={`ml-2 font-bold ${v.signal === 'long' ? 'text-green-400' : v.signal === 'short' ? 'text-red-400' : 'text-gray-500'}`}>
                    {v.signal?.toUpperCase()} {pct(v.confidence)}
                  </span>
                  {v.reasoning && (
                    <p className="text-gray-500 mt-0.5 line-clamp-2">{v.reasoning}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <a
        href={`/coin/${pos.symbol}`}
        className="inline-block text-orange-400 hover:text-orange-300 text-[11px] font-semibold"
      >
        Tam grafik ve coin analizi →
      </a>
    </div>
  )
}
