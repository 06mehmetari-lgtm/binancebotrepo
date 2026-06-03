/** LLM provider env checks — mirrors services/shared/llm_providers.py */

const SLOTS = Math.min(64, Math.max(1, Number(process.env.LLM_KEY_SLOTS ?? 32) || 32))

function collectKeys(prefix: string, alt?: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const env of [alt ?? prefix]) {
    const k = (process.env[env] ?? '').trim()
    if (k && !seen.has(k)) {
      seen.add(k)
      out.push(k)
    }
  }
  for (let i = 1; i <= SLOTS; i++) {
    const k = (process.env[`${prefix}_${i}`] ?? '').trim()
    if (k && !seen.has(k)) {
      seen.add(k)
      out.push(k)
    }
  }
  return out
}

export type LlmProviderStatus = {
  id: string
  name: string
  env: string
  configured: boolean
  key_count: number
  tier_note: string
}

const CATALOG: { id: string; name: string; env: string; tier: string; alt?: string }[] = [
  { id: 'groq', name: 'Groq', env: 'GROQ_API_KEY', tier: 'Ücretsiz: ~14.400 istek/gün (anahtar başı)' },
  { id: 'cerebras', name: 'Cerebras', env: 'CEREBRAS_API_KEY', tier: 'Ücretsiz: dakika başı limit (CEREBRAS_API_KEY_1..N)' },
  { id: 'sambanova', name: 'SambaNova', env: 'SAMBANOVA_API_KEY', tier: 'Ücretsiz tahmini: ~600 istek/gün' },
  { id: 'openrouter', name: 'OpenRouter', env: 'OPENROUTER_API_KEY', tier: 'Ücretsiz model: ~200 istek/gün' },
  { id: 'mistral', name: 'Mistral', env: 'MISTRAL_API_KEY', tier: 'Deneme / ücretsiz katman' },
  { id: 'together', name: 'Together AI', env: 'TOGETHER_API_KEY', tier: 'Kampanya kredisi' },
  { id: 'fireworks', name: 'Fireworks', env: 'FIREWORKS_API_KEY', tier: 'Deneme kredisi' },
  { id: 'cohere', name: 'Cohere', env: 'COHERE_API_KEY', tier: 'Deneme: ~1.000 istek/ay (~33/gün)' },
  { id: 'deepseek', name: 'DeepSeek', env: 'DEEPSEEK_API_KEY', tier: 'Token başı ücret' },
  { id: 'huggingface', name: 'HuggingFace', env: 'HUGGINGFACE_API_KEY', tier: 'Ücretsiz: dakika limiti', alt: 'HF_API_KEY' },
  { id: 'google', name: 'Google Gemini', env: 'GOOGLE_AI_API_KEY', tier: 'Ücretsiz katman', alt: 'GEMINI_API_KEY' },
  { id: 'perplexity', name: 'Perplexity', env: 'PERPLEXITY_API_KEY', tier: 'Sonar API' },
  { id: 'zai', name: 'ZAI', env: 'ZAI_API_KEY', tier: 'Plana göre değişir' },
  { id: 'anthropic', name: 'Anthropic', env: 'ANTHROPIC_API_KEY', tier: 'Token başı (resmi 9 ajan)' },
  { id: 'ollama', name: 'Ollama', env: 'OLLAMA_URL', tier: 'Yerel — sınırsız' },
]

export function getLlmProviderStatus(): LlmProviderStatus[] {
  return CATALOG.map(row => {
    if (row.id === 'ollama') {
      const ok = Boolean((process.env.OLLAMA_URL ?? '').trim())
      return {
        id: row.id,
        name: row.name,
        env: row.env,
        configured: ok,
        key_count: ok ? 1 : 0,
        tier_note: row.tier,
      }
    }
    if (row.id === 'anthropic') {
      const ok = Boolean((process.env.ANTHROPIC_API_KEY ?? '').trim())
      return {
        id: row.id,
        name: row.name,
        env: row.env,
        configured: ok,
        key_count: ok ? 1 : 0,
        tier_note: row.tier,
      }
    }
    const keys = collectKeys(row.env, row.alt)
    return {
      id: row.id,
      name: row.name,
      env: row.env,
      configured: keys.length > 0,
      key_count: keys.length,
      tier_note: row.tier,
    }
  })
}

export function anyLlmConfigured(): boolean {
  return getLlmProviderStatus().some(p => p.configured)
}
