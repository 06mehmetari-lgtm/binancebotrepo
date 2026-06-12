export type ProviderHealth = {
  id: string
  status: string
  ok?: boolean
  http_code?: number | null
  message?: string
  ip_blocked?: boolean
  key_source?: string
  models?: string[]
}

export type LlmHealthPayload = {
  updated_at: number
  providers: {
    groq?: ProviderHealth
    cerebras?: ProviderHealth
    google?: ProviderHealth
    openrouter?: ProviderHealth
    ollama?: ProviderHealth
  }
  any_cloud_ok?: boolean
  cloud_blocked?: boolean
  needs_key_update?: boolean
  alert_level?: 'ok' | 'warning' | 'critical'
  alert_message?: string
  runtime_keys_active?: boolean
}

export type KeyOverridesMeta = {
  updated_at?: number
  updated_by?: string
  groq_count: number
  cerebras_count: number
  google_count: number
  openrouter_count?: number
  runtime_keys_active: boolean
  groq_masked: string[]
  cerebras_masked: string[]
  google_masked: string[]
  openrouter_masked?: string[]
  probe_results?: Record<string, ProbeSummary>
}

export type ProbeSummary = {
  ok: boolean
  http_code: number | null
  message: string
  ip_blocked: boolean
}
