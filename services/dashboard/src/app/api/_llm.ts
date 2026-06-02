/**
 * Multi-provider LLM client with automatic fallback.
 * Order: Groq → Cerebras → SambaNova → OpenRouter → Ollama (local, unlimited)
 */

interface Provider {
  name: string
  url: string
  keyEnv: string
  model: string
  extraHeaders?: Record<string, string>
  isLocal?: boolean
}

const OLLAMA_URL   = process.env.OLLAMA_URL   ?? 'http://ollama:11434'
const OLLAMA_MODEL = process.env.OLLAMA_MODEL ?? 'llama3.1:8b'

const PROVIDERS: Provider[] = [
  {
    name: 'Groq',
    url: 'https://api.groq.com/openai/v1/chat/completions',
    keyEnv: 'GROQ_API_KEY',
    model: 'llama-3.3-70b-versatile',
  },
  {
    name: 'Cerebras',
    url: 'https://api.cerebras.ai/v1/chat/completions',
    keyEnv: 'CEREBRAS_API_KEY',
    model: 'llama3.1-8b',
  },
  {
    name: 'SambaNova',
    url: 'https://api.sambanova.ai/v1/chat/completions',
    keyEnv: 'SAMBANOVA_API_KEY',
    model: 'Meta-Llama-3.1-8B-Instruct',
  },
  {
    name: 'OpenRouter',
    url: 'https://openrouter.ai/api/v1/chat/completions',
    keyEnv: 'OPENROUTER_API_KEY',
    model: 'google/gemma-2-9b-it:free',
    extraHeaders: {
      'HTTP-Referer': 'https://prometheus-trading.io',
      'X-Title': 'Prometheus Trading',
    },
  },
  {
    name: 'Ollama',
    url: `${OLLAMA_URL}/api/chat`,
    keyEnv: '',
    model: OLLAMA_MODEL,
    isLocal: true,
  },
]

// Per-provider rate limit cooldown (ms timestamp)
const providerCooldown: Record<string, number> = {}
const RATE_LIMIT_COOLDOWN_MS = 65_000

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error(`timeout after ${ms}ms`)), ms)
    ),
  ])
}

export async function chatCompletion(
  prompt: string,
  options: { system?: string; temperature?: number; maxTokens?: number } = {},
): Promise<{ content: string; provider: string }> {
  const { system = '', temperature = 0.1, maxTokens = 1024 } = options

  const messages: { role: string; content: string }[] = []
  if (system) messages.push({ role: 'system', content: system })
  messages.push({ role: 'user', content: prompt })

  let lastError = 'tüm sağlayıcılar denendi'
  const now = Date.now()

  for (const p of PROVIDERS) {
    // Skip cloud providers without API key
    if (!p.isLocal) {
      const apiKey = process.env[p.keyEnv]
      if (!apiKey) continue

      // Skip if rate-limited recently
      const cooldownUntil = providerCooldown[p.name] ?? 0
      if (now < cooldownUntil) continue
    }

    try {
      if (p.isLocal) {
        // Ollama — different payload, 90s timeout
        const res = await withTimeout(
          fetch(p.url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              model: p.model,
              messages,
              stream: false,
              options: { temperature, num_predict: maxTokens },
            }),
          }),
          90_000,
        )
        if (!res.ok) {
          const text = await res.text()
          lastError = `Ollama ${res.status}: ${text.slice(0, 80)}`
          continue
        }
        const data = await res.json()
        const content: string = data.message?.content ?? ''
        if (!content) { lastError = 'Ollama boş yanıt'; continue }
        return { content, provider: 'Ollama' }
      }

      // Cloud providers — OpenAI-compatible, 30s timeout
      const apiKey = process.env[p.keyEnv]!
      const res = await withTimeout(
        fetch(p.url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${apiKey}`,
            ...p.extraHeaders,
          },
          body: JSON.stringify({ model: p.model, messages, temperature, max_tokens: maxTokens }),
        }),
        30_000,
      )

      if (res.status === 429) {
        providerCooldown[p.name] = Date.now() + RATE_LIMIT_COOLDOWN_MS
        lastError = `${p.name} 429 rate limit`
        continue
      }
      if (!res.ok) {
        const text = await res.text()
        lastError = `${p.name} ${res.status}: ${text.slice(0, 80)}`
        continue
      }
      const data = await res.json()
      const content: string = data.choices?.[0]?.message?.content ?? ''
      if (!content) { lastError = `${p.name} boş yanıt`; continue }
      return { content, provider: p.name }
    } catch (err) {
      lastError = `${p.name}: ${err}`
    }
  }

  throw new Error(`Tüm LLM sağlayıcıları başarısız. Son hata: ${lastError}`)
}
