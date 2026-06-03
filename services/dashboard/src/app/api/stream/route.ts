import { createRedis } from '../_redis'
import {
  parseStreamChannel,
  STREAM_CHANNELS,
  STREAM_PATTERNS,
  type StreamEvent,
} from '@/lib/stream-events'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function sseLine(event: StreamEvent): string {
  return `data: ${JSON.stringify(event)}\n\n`
}

export async function GET(req: Request) {
  const encoder = new TextEncoder()
  let closed = false
  const sub = createRedis()

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (ev: StreamEvent) => {
        if (closed) return
        try {
          controller.enqueue(encoder.encode(sseLine(ev)))
        } catch {
          closed = true
        }
      }

      send({ ch: 'stream:connected', ts: Date.now() / 1000, hint: 'connected' })

      const onMessage = (channel: string, message: string) => {
        send(parseStreamChannel(channel, message))
      }

      sub.on('pmessage', (_pat, channel, message) => {
        onMessage(channel, message ?? '')
      })
      sub.on('message', (channel, message) => {
        onMessage(channel, message ?? '')
      })

      try {
        for (const pat of STREAM_PATTERNS) {
          await sub.psubscribe(pat)
        }
        for (const ch of STREAM_CHANNELS) {
          await sub.subscribe(ch)
        }
      } catch (err) {
        console.error('[stream] subscribe failed', err)
        send({
          ch: 'stream:error',
          ts: Date.now() / 1000,
          hint: 'subscribe_failed',
        })
      }

      const ping = setInterval(() => {
        if (closed) return
        send({ ch: 'stream:ping', ts: Date.now() / 1000, hint: 'ping' })
      }, 25000)

      req.signal.addEventListener('abort', () => {
        closed = true
        clearInterval(ping)
        sub.disconnect()
        try {
          controller.close()
        } catch {
          /* already closed */
        }
      })
    },
    cancel() {
      closed = true
      sub.disconnect()
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
