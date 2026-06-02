/**
 * Multi-provider LLM client with automatic fallback.
 * Order: Groq → Cerebras → SambaNova → OpenRouter
 */

interface Provider {
  name: string
  url: string
  keyEnv: string
  model: string
  extraHeaders?: Record<string, string>
}

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
    model: 'llama-3.3-70b',
  },
  {
    name: 'SambaNova',
    url: 'https://api.sambanova.ai/v1/chat/completions',
    keyEnv: 'SAMBANOVA_API_KEY',
    model: 'Meta-Llama-3.3-70B-Instruct',
  },
  {
    name: 'OpenRouter',
    url: 'https://openrouter.ai/api/v1/chat/completions',
    keyEnv: 'OPENROUTER_API_KEY',
    model: 'mistralai/mistral-7b-instruct:free',
    extraHeaders: {
      'HTTP-Referer': 'https://prometheus-trading.io',
      'X-Title': 'Prometheus Trading',
    },
  },
]

export async function chatCompletion(
  prompt: string,
  options: { system?: string; temperature?: number; maxTokens?: number } = {},
): Promise<{ content: string; provider: string }> {
  const { system = '', temperature = 0.1, maxTokens = 1024 } = options

  const messages = []
  if (system) messages.push({ role: 'system', content: system })
  messages.push({ role: 'user', content: prompt })

  let lastError = 'tüm sağlayıcılar denendi'

  for (const p of PROVIDERS) {
    const apiKey = process.env[p.keyEnv]
    if (!apiKey) continue

    try {
      const res = await fetch(p.url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${apiKey}`,
          ...p.extraHeaders,
        },
        body: JSON.stringify({ model: p.model, messages, temperature, max_tokens: maxTokens }),
      })

      if (res.status === 429) {
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
      return { content, provider: p.name }
    } catch (err) {
      lastError = `${p.name}: ${err}`
    }
  }

  throw new Error(`Tüm LLM sağlayıcıları başarısız. Son hata: ${lastError}`)
}
