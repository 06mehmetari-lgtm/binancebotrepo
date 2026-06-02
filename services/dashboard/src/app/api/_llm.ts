/**
 * Multi-provider LLM client with automatic fallback.
 * Order: Anthropic → Groq → Cerebras → SambaNova → OpenRouter → Ollama
 */

const OLLAMA_URL   = process.env.OLLAMA_URL   ?? 'http://ollama:11434'
const OLLAMA_MODEL = process.env.OLLAMA_MODEL ?? 'llama3.1:8b'

// Per-provider rate limit cooldown (ms timestamp) — persists across requests in same process
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

async function callAnthropic(
  messages: { role: string; content: string }[],
  system: string,
  temperature: number,
  maxTokens: number,
): Promise<string> {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) throw new Error('ANTHROPIC_API_KEY yok')

  // Anthropic: system ayrı alan, messages sadece user/assistant
  const userMessages = messages.filter(m => m.role !== 'system')

  const res = await withTimeout(
    fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: maxTokens,
        temperature,
        system: system || 'You are a helpful assistant.',
        messages: userMessages,
      }),
    }),
    30_000,
  )

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Anthropic ${res.status}: ${text.slice(0, 120)}`)
  }
  const data = await res.json()
  const content = data.content?.[0]?.text ?? ''
  if (!content) throw new Error('Anthropic boş yanıt')
  return content
}

export async function chatCompletion(
  prompt: string,
  options: { system?: string; temperature?: number; maxTokens?: number } = {},
): Promise<{ content: string; provider: string }> {
  const { system = '', temperature = 0.1, maxTokens = 1024 } = options

  const messages: { role: string; content: string }[] = []
  if (system) messages.push({ role: 'system', content: system })
  messages.push({ role: 'user', content: prompt })

  // 1. Anthropic — en güvenilir, birinci sıra
  try {
    const content = await callAnthropic(messages, system, temperature, maxTokens)
    return { content, provider: 'Anthropic' }
  } catch (err) {
    console.warn(`LLM [Anthropic] hata: ${err} — sonraki sağlayıcıya geçiliyor`)
  }

  // 2. Free cloud providers
  const CLOUD_PROVIDERS = [
    {
      name: 'Groq',
      url: 'https://api.groq.com/openai/v1/chat/completions',
      keyEnv: 'GROQ_API_KEY',
      model: 'llama-3.3-70b-versatile',
      extraHeaders: {} as Record<string, string>,
    },
    {
      name: 'Cerebras',
      url: 'https://api.cerebras.ai/v1/chat/completions',
      keyEnv: 'CEREBRAS_API_KEY',
      model: 'llama3.1-8b',
      extraHeaders: {} as Record<string, string>,
    },
    {
      name: 'SambaNova',
      url: 'https://api.sambanova.ai/v1/chat/completions',
      keyEnv: 'SAMBANOVA_API_KEY',
      model: 'Meta-Llama-3.1-8B-Instruct',
      extraHeaders: {} as Record<string, string>,
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
  ]

  const now = Date.now()
  let lastError = 'tüm cloud sağlayıcılar başarısız'

  for (const p of CLOUD_PROVIDERS) {
    const apiKey = process.env[p.keyEnv]
    if (!apiKey) continue

    const cooldownUntil = providerCooldown[p.name] ?? 0
    if (now < cooldownUntil) continue

    try {
      const res = await withTimeout(
        fetch(p.url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${apiKey}`,
            ...p.extraHeaders,
          },
          body: JSON.stringify({
            model: p.model,
            messages,
            temperature,
            max_tokens: maxTokens,
          }),
        }),
        30_000,
      )

      if (res.status === 429) {
        providerCooldown[p.name] = Date.now() + RATE_LIMIT_COOLDOWN_MS
        lastError = `${p.name} 429`
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

  // 3. Ollama — local fallback, 60s timeout
  try {
    const res = await withTimeout(
      fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: OLLAMA_MODEL,
          messages,
          stream: false,
          options: { temperature, num_predict: maxTokens },
        }),
      }),
      60_000,
    )
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Ollama ${res.status}: ${text.slice(0, 80)}`)
    }
    const data = await res.json()
    const content: string = data.message?.content ?? ''
    if (!content) throw new Error('Ollama boş yanıt')
    return { content, provider: 'Ollama' }
  } catch (err) {
    lastError = `Ollama: ${err}`
  }

  throw new Error(`Tüm LLM sağlayıcıları başarısız. Son hata: ${lastError}`)
}
