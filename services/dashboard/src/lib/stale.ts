/** Heartbeat staleness for dashboard STALE badges */

export const HEARTBEAT_STALE_SEC = 120

export interface HeartbeatStatus {
  service: string
  ageSec: number | null
  stale: boolean
}

export function parseHeartbeatAge(raw: string | null): number | null {
  if (!raw) return null
  const ts = Number(raw)
  if (!Number.isFinite(ts) || ts <= 0) return null
  return Math.max(0, Date.now() / 1000 - ts)
}

export function isStale(ageSec: number | null, threshold = HEARTBEAT_STALE_SEC): boolean {
  if (ageSec == null) return true
  return ageSec > threshold
}

export const PIPELINE_HEARTBEATS = [
  { key: 'system:heartbeat:data_ingestion', label: 'data_ingestion' },
  { key: 'system:heartbeat:feature_engine', label: 'feature_engine' },
  { key: 'system:heartbeat:context_engine', label: 'context_engine' },
  { key: 'system:heartbeat:agent_system', label: 'agent_system' },
  { key: 'system:heartbeat:signal_engine', label: 'signal_engine' },
  { key: 'system:heartbeat:learning_engine', label: 'learning_engine' },
  { key: 'system:heartbeat:shadow_system', label: 'shadow_system' },
  { key: 'system:heartbeat:immunity_system', label: 'immunity_system' },
  { key: 'system:heartbeat:oms', label: 'oms' },
] as const
