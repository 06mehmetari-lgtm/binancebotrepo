'use client'

import { useCallback, useEffect, useState } from 'react'

export interface DeployStatus {
  version?: string
  commit_short?: string
  deployed_at_iso?: string
  status?: string
  summary_tr?: string
  code_applied?: boolean
  git_sync_ok?: boolean
  files_changed?: string[]
  pc_files_pending?: string[]
  services_ok?: string[]
  services_failed?: string[]
  skipped?: string[]
  plan?: {
    update_live?: string[]
    update_build?: string[]
    heal_down?: number
    skipped?: number
  }
  vps_sha?: string
  expected_sha?: string
  note?: string
}

function fmtDeployTime(iso?: string): string {
  if (!iso) return '—'
  const normalized = iso.includes('T')
    ? iso
    : iso.replace(' UTC', 'Z').replace(' ', 'T')
  const d = new Date(normalized)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('tr-TR', {
    timeZone: 'Europe/Istanbul',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function outcome(deploy: DeployStatus): { label: string; color: string; border: string } {
  if (deploy.git_sync_ok === false) {
    return {
      label: 'Kod YANSIMADI — VPS git senkronu basarisiz',
      color: 'text-red-300',
      border: 'bg-red-950/40 border-red-700/50',
    }
  }
  if (deploy.code_applied) {
    const partial = (deploy.services_failed?.length ?? 0) > 0 || deploy.status === 'partial'
    return partial
      ? { label: 'Kismi yansidi — bazi servisler guncellenemedi', color: 'text-yellow-300', border: 'bg-yellow-950/35 border-yellow-700/50' }
      : { label: 'Kod yansidi — guncelleme uygulandi', color: 'text-green-300', border: 'bg-green-950/35 border-green-700/50' }
  }
  const pcPending = deploy.pc_files_pending?.length ?? 0
  if (pcPending > 0) {
    return {
      label: 'Deploy calisti ama kod UYGULANMADI (VPS eski commit)',
      color: 'text-orange-300',
      border: 'bg-orange-950/35 border-orange-700/50',
    }
  }
  return {
    label: 'Deploy tamam — kod degisikligi yoktu',
    color: 'text-gray-300',
    border: 'bg-gray-900/60 border-gray-700/50',
  }
}

export default function DeployStatusPanel() {
  const [deploy, setDeploy] = useState<DeployStatus | null>(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/deploy-version')
      const data = await r.json()
      if (!data?.error) setDeploy(data)
    } catch { /* retry */ }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])

  if (!deploy?.version && !deploy?.deployed_at_iso) return null

  const o = outcome(deploy)
  const applied = deploy.services_ok ?? deploy.plan?.update_live ?? []
  const built = deploy.plan?.update_build ?? []
  const skipped = deploy.skipped ?? []
  const vpsFiles = deploy.files_changed ?? []
  const pcFiles = deploy.pc_files_pending ?? []

  return (
    <div className={`rounded-xl border px-4 py-3 ${o.border}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
        <div>
          <p className="text-xs uppercase tracking-wider text-gray-500 mb-0.5">Son DEPLOY.bat</p>
          <p className={`text-sm font-semibold ${o.color}`}>{o.label}</p>
          {deploy.summary_tr && (
            <p className="text-xs text-gray-400 mt-1">{deploy.summary_tr}</p>
          )}
        </div>
        <div className="text-right text-xs font-mono text-gray-400">
          <p className="text-white text-sm">{fmtDeployTime(deploy.deployed_at_iso)}</p>
          <p>v{deploy.version ?? '?'}</p>
          {deploy.vps_sha && (
            <p className="text-[10px] mt-0.5">
              VPS sha {String(deploy.vps_sha).slice(0, 12)}
              {deploy.expected_sha && deploy.git_sync_ok === false && (
                <span className="text-red-400"> ≠ {String(deploy.expected_sha).slice(0, 12)}</span>
              )}
            </p>
          )}
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 text-[11px]">
        <div className="bg-black/20 rounded-lg px-2.5 py-2 border border-gray-800/50">
          <p className="text-gray-500 mb-1">Yansiyan servisler</p>
          {applied.length || built.length ? (
            <p className="text-green-400 font-mono break-words">
              {[...applied, ...built.map(s => `${s} (build)`)]
                .filter((v, i, a) => a.indexOf(v) === i)
                .join(', ') || '—'}
            </p>
          ) : (
            <p className="text-gray-500">Hicbiri (kod degismedi veya sync hatasi)</p>
          )}
        </div>
        <div className="bg-black/20 rounded-lg px-2.5 py-2 border border-gray-800/50">
          <p className="text-gray-500 mb-1">Atlanan (ayakta, etkilenmedi)</p>
          <p className="text-gray-400 font-mono truncate" title={skipped.join(', ')}>
            {skipped.length ? `${skipped.length} servis` : deploy.plan?.skipped ?? 0}
          </p>
        </div>
        <div className="bg-black/20 rounded-lg px-2.5 py-2 border border-gray-800/50">
          <p className="text-gray-500 mb-1">VPS&apos;te degisen dosya</p>
          <p className="text-gray-300 font-mono">
            {vpsFiles.length
              ? vpsFiles.slice(0, 3).map(f => f.split('/').pop()).join(', ') + (vpsFiles.length > 3 ? ` +${vpsFiles.length - 3}` : '')
              : '0'}
          </p>
        </div>
        <div className="bg-black/20 rounded-lg px-2.5 py-2 border border-gray-800/50">
          <p className="text-gray-500 mb-1">PC&apos;de gonderilen</p>
          <p className="text-gray-300 font-mono">
            {pcFiles.length
              ? pcFiles.slice(0, 3).map(f => f.split('/').pop()).join(', ') + (pcFiles.length > 3 ? ` +${pcFiles.length - 3}` : '')
              : '—'}
          </p>
        </div>
      </div>

      {(deploy.services_failed?.length ?? 0) > 0 && (
        <p className="text-xs text-red-400 mt-2 font-mono">
          Hata: {deploy.services_failed?.join(', ')}
        </p>
      )}
    </div>
  )
}
