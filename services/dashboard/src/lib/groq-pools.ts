/** Groq model pools from .env — one API key, many model names */

const MODEL_SLOTS = Math.min(32, Math.max(2, Number(process.env.GROQ_MODEL_SLOTS ?? 20) || 20))

const POOLS: { id: string; prefix: string; label: string }[] = [
  { id: 'fast', prefix: 'GROQ_FAST_MODELS', label: 'Fast' },
  { id: 'main', prefix: 'GROQ_MAIN_MODELS', label: 'Main' },
  { id: 'reason', prefix: 'GROQ_REASON_MODELS', label: 'Reasoning' },
  { id: 'risk', prefix: 'GROQ_RISK_MODELS', label: 'Risk' },
  { id: 'learning', prefix: 'GROQ_LEARNING_MODELS', label: 'Learning' },
  { id: 'final', prefix: 'GROQ_FINAL_MODEL', label: 'Final judge' },
  { id: 'vision', prefix: 'GROQ_VISION_MODELS', label: 'Vision' },
  { id: 'fallback', prefix: 'GROQ_FALLBACK_MODEL', label: 'Fallback' },
]

function collectModels(prefix: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  const primary = (process.env[prefix] ?? '').trim()
  if (primary && !seen.has(primary)) {
    seen.add(primary)
    out.push(primary)
  }
  for (let i = 2; i <= MODEL_SLOTS; i++) {
    const m = (process.env[`${prefix}_${i}`] ?? '').trim()
    if (m && !seen.has(m)) {
      seen.add(m)
      out.push(m)
    }
  }
  return out
}

export function getGroqPoolStatus(): { id: string; label: string; models: string[]; count: number }[] {
  return POOLS.map(p => {
    const models = collectModels(p.prefix)
    return { id: p.id, label: p.label, models, count: models.length }
  })
}
