import { NextResponse } from 'next/server'
import http from 'http'

// Maps dashboard service names → Docker container names
const SERVICE_CONTAINER: Record<string, string> = {
  feature_engine:  'prometheus_features',
  signal_engine:   'prometheus_signal',
  context_engine:  'prometheus_context',
  agent_system:    'prometheus_agents',
  rl_agent:        'prometheus_rl',
  neat_evolution:  'prometheus_neat',
  shadow_system:   'prometheus_shadow',
  oms:             'prometheus_oms',
  autopsy:         'prometheus_autopsy',
  data_ingestion:  'prometheus_data',
  sentiment:       'prometheus_sentiment',
  macro:           'prometheus_macro',
}

function dockerRestart(container: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        socketPath: '/var/run/docker.sock',
        path: `/containers/${container}/restart`,
        method: 'POST',
      },
      (res) => resolve(res.statusCode ?? 0),
    )
    req.on('error', reject)
    req.setTimeout(15_000, () => { req.destroy(); reject(new Error('Docker socket timeout')) })
    req.end()
  })
}

export async function POST(
  _req: Request,
  { params }: { params: { service: string } },
) {
  const container = SERVICE_CONTAINER[params.service]
  if (!container) {
    return NextResponse.json({ error: `Unknown service: ${params.service}` }, { status: 400 })
  }
  try {
    const status = await dockerRestart(container)
    // 204 = restart accepted, 304 = container already restarting
    if (status === 204 || status === 304) {
      return NextResponse.json({ ok: true, container, status })
    }
    return NextResponse.json(
      { error: `Docker returned HTTP ${status}`, container },
      { status: 500 },
    )
  } catch (e) {
    return NextResponse.json(
      { error: String(e), hint: 'Docker socket not mounted — rebuild dashboard container' },
      { status: 500 },
    )
  }
}
