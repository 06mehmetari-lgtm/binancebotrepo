/** Read LLM key slots from dashboard process.env (compose). */

const SLOTS = Math.min(64, Math.max(1, Number(process.env.LLM_KEY_SLOTS ?? 32) || 32))

export function collectKeysFromEnv(prefix: string, alt?: string): string[] {
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

export function cleanKeyList(raw: unknown, max = 32): string[] {
  if (!Array.isArray(raw)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const k = String(item ?? '').trim()
    if (!k || seen.has(k)) continue
    seen.add(k)
    out.push(k)
    if (out.length >= max) break
  }
  return out
}
