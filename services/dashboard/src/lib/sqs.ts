/** Signal Quality Score — scanner, analiz, learning hub ortak */

export function computeSQS(p: {
  confidence: number
  direction: string
  sharpe: number | null
  winRate: number | null
  regime: string | null
  drift: string
  shadowSharpe?: number
  shadowWr?: number
  imbalance5?: number | null
  learnStage?: string | null
}): number {
  if (p.direction === 'flat') return 0
  let score = Math.min(1, p.confidence) * 30
  if (p.sharpe != null && p.winRate != null) {
    const sn = Math.min(1, Math.max(0, p.sharpe / 3))
    const wn = Math.min(1, Math.max(0, p.winRate / 100))
    score += (sn * 0.7 + wn * 0.3) * 35
  }
  if (p.shadowSharpe != null && p.shadowWr != null) {
    const ss = Math.min(1, Math.max(0, p.shadowSharpe / 2))
    const sw = Math.min(1, Math.max(0, p.shadowWr / 100))
    score += (ss * 0.6 + sw * 0.4) * 15
  }
  if (p.regime === 'trending_up' || p.regime === 'trending_down') score += 5
  else if (p.regime === 'volatile') score -= 5
  if (p.drift === 'WARNING') score -= 5
  else if (p.drift === 'DRIFTING') score -= 15
  else if (p.drift === 'SHOCK') score -= 30
  if (p.imbalance5 != null) {
    if (p.direction === 'long' && p.imbalance5 > 0.2) score += 4
    if (p.direction === 'short' && p.imbalance5 < -0.2) score += 4
    if (p.direction === 'long' && p.imbalance5 < -0.3) score -= 6
  }
  if (p.learnStage === 'L3') score += 5
  else if (p.learnStage === 'L2') score += 2
  else if (p.learnStage === 'L0') score -= 3
  return Math.round(Math.max(0, Math.min(100, score)))
}

export function depthLabel(imb: number | null | undefined): string {
  if (imb == null || Number.isNaN(imb)) return '—'
  if (imb > 0.35) return 'Güçlü bid'
  if (imb > 0.15) return 'Bid baskısı'
  if (imb < -0.35) return 'Güçlü ask'
  if (imb < -0.15) return 'Ask baskısı'
  return 'Dengeli'
}
