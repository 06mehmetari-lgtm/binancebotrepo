/** SSE event shape — lightweight invalidation hints from Redis pub/sub */

export interface StreamEvent {
  ch: string
  symbol?: string
  ts: number
  hint?: string
}

const SYMBOL_CHANNEL_RE =
  /^ch:(?:signal|agents|learn|features|context):(.+)$/i

export function parseStreamChannel(channel: string, message: string): StreamEvent {
  const ts = Date.now() / 1000
  let symbol: string | undefined
  const m = channel.match(SYMBOL_CHANNEL_RE)
  if (m) symbol = m[1].toUpperCase()
  else if (message && /^[A-Z0-9]+USDT$/i.test(message.trim())) {
    symbol = message.trim().toUpperCase()
  }

  let hint: string | undefined
  if (channel.startsWith('ch:signal:')) hint = 'signal'
  else if (channel.startsWith('ch:agents:')) hint = 'agents'
  else if (channel.startsWith('ch:learn:')) hint = 'learn'
  else if (channel.startsWith('ch:features:')) hint = 'features'
  else if (channel === 'ch:trade_closed') hint = 'trade_closed'
  else if (channel === 'ch:position:guard') hint = 'guard'
  else if (channel === 'ch:portfolio:update') hint = 'portfolio'
  else if (channel === 'ch:emergency:close_all') hint = 'emergency'

  return { ch: channel, symbol, ts, hint }
}

export const STREAM_PATTERNS = [
  'ch:signal:*',
  'ch:agents:*',
  'ch:learn:*',
  'ch:features:*',
] as const

export const STREAM_CHANNELS = [
  'ch:trade_closed',
  'ch:position:guard',
  'ch:emergency:close_all',
  'ch:portfolio:update',
] as const
