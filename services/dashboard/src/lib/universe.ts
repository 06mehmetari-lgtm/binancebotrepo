import type { Redis } from 'ioredis'

/** Prefer pre-built universe snapshot (O(1)); fallback to SCAN not KEYS. */
export async function discoverSymbols(redis: Redis): Promise<string[]> {
  const snap = await redis.get('snapshot:universe:v1')
  if (snap) {
    try {
      const data = JSON.parse(snap)
      if (Array.isArray(data.symbols)) return data.symbols as string[]
    } catch { /* fall through */ }
  }

  const symbols: string[] = []
  let cursor = '0'
  do {
    const [next, keys] = await redis.scan(cursor, 'MATCH', 'features:latest:*', 'COUNT', 500)
    cursor = next
    for (const k of keys) {
      symbols.push(k.replace('features:latest:', ''))
    }
  } while (cursor !== '0')

  return symbols.sort()
}

export async function getUniverseSnapshot<T>(redis: Redis): Promise<T | null> {
  const raw = await redis.get('snapshot:universe:v1')
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

/** Non-blocking key discovery — never use KEYS at scale. */
/** /api/signals returns a bare array or { signals: [] } */
export function parseSignalsResponse(data: unknown): unknown[] {
  if (Array.isArray(data)) return data
  if (data && typeof data === 'object' && Array.isArray((data as { signals?: unknown[] }).signals)) {
    return (data as { signals: unknown[] }).signals
  }
  return []
}

export async function scanKeys(redis: Redis, pattern: string): Promise<string[]> {
  const keys: string[] = []
  let cursor = '0'
  do {
    const [next, batch] = await redis.scan(cursor, 'MATCH', pattern, 'COUNT', 300)
    cursor = next
    keys.push(...batch)
  } while (cursor !== '0')
  return keys
}
