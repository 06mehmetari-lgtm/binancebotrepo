/** Statik müfredat + öğrenme merkezi yardımcıları */

export type LearningTab =
  | 'live'
  | 'brain'
  | 'lessons'
  | 'stream'
  | 'strategy'
  | 'doc'
  | 'llm'
  | 'command'

export const LEARNING_TABS: { id: LearningTab; label: string; icon: string; desc: string }[] = [
  { id: 'live', label: 'Canlıya Geçiş', icon: '🎯', desc: 'Shadow → canlı kapı, kriterler, ortam' },
  { id: 'brain', label: 'Ollama Beyin', icon: '🧠', desc: 'Yerel LLM modelleri ve sağlık' },
  { id: 'lessons', label: 'AI Dersleri', icon: '📖', desc: 'trade:lessons + Qdrant hafıza' },
  { id: 'stream', label: 'Canlı Akış', icon: '📡', desc: 'Pipeline olayları ve heartbeat' },
  { id: 'strategy', label: 'Strateji Analizi', icon: '📊', desc: 'Coin profilleri, SQS, sinyal' },
  { id: 'doc', label: 'Strateji Belgesi', icon: '📋', desc: 'Sistem mimarisi ve kurallar' },
  { id: 'llm', label: 'LLM Durum', icon: '🔌', desc: 'Groq, Ollama, ajan debati' },
  { id: 'command', label: 'Emir Merkezi', icon: '⚡', desc: 'Manuel long/short/kapat/debate' },
]

export const PROMOTION_CRITERIA = [
  { key: 'trades', label: 'Min işlem', target: 100, unit: '', invert: false },
  { key: 'sharpe', label: 'Sharpe', target: 1.5, unit: '', invert: false },
  { key: 'win_rate', label: 'Win rate', target: 52, unit: '%', invert: false },
  { key: 'max_drawdown', label: 'Max DD', target: 10, unit: '%', invert: true },
]

export const CURRICULUM: { id: string; title: string; level: string; body: string }[] = [
  {
    id: 'c1',
    title: 'Order book & imbalance',
    level: 'Derinlik',
    body: 'imbalance_5 > 0.25 bid baskısı; < -0.25 ask baskısı. Prometheus features:latest içinde ob_imbalance_1/5/10/20 ile kaydedilir. Kapanış derslerinde imbalance kaydedilir.',
  },
  {
    id: 'c2',
    title: 'Funding & crowded trades',
    level: 'Perp',
    body: 'Yüksek pozitif funding = crowded long. learning_engine avoid_hint üretir; signal_engine learn_adjust confidence düşürür.',
  },
  {
    id: 'c3',
    title: 'Regime + crisis çarpanı',
    level: 'Bağlam',
    body: 'context_engine: trending_up/down, ranging, volatile. crisis_level 0-4. Kriz≥2 iken immunity ve guard agresif boyutu kısar.',
  },
  {
    id: 'c4',
    title: '9 ajan + debate',
    level: 'AI',
    body: 'Bull/Bear/Neutral + Technical/News/Macro/OnChain + Risk/Evolution → debate_agent JSON verdict. Güven < %60 → sinyal flat.',
  },
  {
    id: 'c5',
    title: 'Shadow → canlı kapı',
    level: 'Risk',
    body: 'SHADOW_A paper: 100 işlem, Sharpe≥1.5, WR≥52%, DD<10%. Sonra DRY_RUN=false + LIVE_TRADING_CONFIRMED=true.',
  },
  {
    id: 'c6',
    title: 'Position guard (~1s)',
    level: 'Koruma',
    body: 'Açık pozisyonlar öncelikli izlenir. FLAT verdict, zarar limiti, kriz → ch:position:guard → OMS/shadow kapatır.',
  },
]

export function stageColor(stage?: string): string {
  switch (stage) {
    case 'L3': return 'text-green-400'
    case 'L2': return 'text-cyan-400'
    case 'L1': return 'text-yellow-400'
    default: return 'text-gray-500'
  }
}

export function buildStrategyDocument(data: {
  symbols_tracked: number
  profiles_count: number
  promotion: { approved: boolean; reason: string | null }
  dry_run: boolean
}): string {
  return `# Prometheus — Canlı Strateji Özeti
Oluşturulma: ${new Date().toISOString()}

## Evren
- İzlenen sembol: ~${data.symbols_tracked}
- Öğrenilmiş profil: ${data.profiles_count}

## Sinyal üretimi
1. feature_engine → 40+ özellik (RSI, MACD, OB depth, funding, OI)
2. context_engine → regime + crisis + drift
3. learning_engine → learn:profile (L0→L3)
4. agent_system → 9 ajan debate → agents:verdict
5. signal_engine → ensemble (agent + NEAT + RL), min confidence %60

## Risk (değiştirilemez)
- Max kaldıraç 3×, pozisyon %5, günlük kayıp %2, max 3 açık pozisyon

## Canlı mod
- DRY_RUN: ${data.dry_run ? 'true (paper)' : 'false'}
- Promotion: ${data.promotion.approved ? 'ONAYLI' : 'BEKLİYOR'}
- Sebep: ${data.promotion.reason ?? '—'}

## Manuel emir (dashboard)
- Emir Merkezi → force_signal / close / debate / learning refresh
- Paper modda OMS+shadow Redis sinyallerini okur; immunity her emri doğrular.
`
}
