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

export async function chatCompletion(
  prompt: string,
  options: { system?: string; temperature?: number; maxTokens?: number } = {},
): Promise<{ content: string; provider: string }> {
  const { system = '', temperature = 0.1, maxTokens = 1024 } = options

  const messages: { role: string; content: string }[] = []
  if (system) messages.push({ role: 'system', content: system })
  messages.push({ role: 'user', content: prompt })

  let lastError = 'tüm sağlayıcılar denendi'

  for (const p of PROVIDERS) {
    // Ollama has no API key
    if (!p.isLocal) {
      const apiKey = process.env[p.keyEnv]
      if (!apiKey) continue
    }

    try {
      if (p.isLocal) {
        // Ollama uses /api/chat with a different payload shape
        const res = await fetch(p.url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: p.model,
            messages,
            stream: false,
            options: { temperature, num_predict: maxTokens },
          }),
        })
        if (!res.ok) {
          const text = await res.text()
          lastError = `Ollama ${res.status}: ${text.slice(0, 80)}`
          continue
        }
        const data = await res.json()
        const content: string = data.message?.content ?? ''
        return { content, provider: 'Ollama' }
      }

      // Cloud providers — OpenAI-compatible
      const apiKey = process.env[p.keyEnv]!
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
