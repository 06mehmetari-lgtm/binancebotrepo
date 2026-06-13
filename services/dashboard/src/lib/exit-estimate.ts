/** Shadow/OMS çıkış kuralları — profit_rules.py ile uyumlu varsayılanlar */

export const EXIT_RULES = {
  MAX_HOLD_SEC: 3600,
  STALE_VERDICT_SEC: 1800,
  BREAKEVEN_ACTIVATE_PCT: 0.35,
  BREAKEVEN_FLOOR_PCT: 0.08,
  BREAKEVEN_MIN_HOLD_SEC: 120,
  DEFAULT_SL_PCT: 1.2,
  DEFAULT_TP_PCT: 1.5,
} as const

export type ExitUrgency = 'now' | 'imminent' | 'normal'

export type ExitEstimate = {
  trigger: string
  label: string
  countdown_sec: number
  estimated_close_at: number
  urgency: ExitUrgency
  detail: string
  secondary?: string
}

type LadderLike = {
  stop_loss_pct?: number
  take_profit_pct?: number
  breakeven_armed?: boolean
  peak_upnl_pct?: number
}

type GuardLike = {
  action?: string
  urgency?: string
}

function fmtDur(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  return `${m}:${String(r).padStart(2, '0')}`
}

export function computeExitEstimate(input: {
  entry_time?: number
  direction: string
  unrealized_pct: number
  ladder?: LadderLike
  guard?: GuardLike
  current_signal_direction?: string
  now?: number
  rules?: Partial<typeof EXIT_RULES>
}): ExitEstimate {
  const rules = { ...EXIT_RULES, ...input.rules }
  const now = input.now ?? Date.now() / 1000
  const entry = input.entry_time ?? 0
  const holdSec = entry > 0 ? now - entry : 0
  const upnl = input.unrealized_pct
  const ladder = input.ladder ?? {}
  const sl = Number(ladder.stop_loss_pct ?? rules.DEFAULT_SL_PCT)
  const tp = Number(ladder.take_profit_pct ?? rules.DEFAULT_TP_PCT)
  const sigDir = input.current_signal_direction ?? 'flat'
  const breakevenArmed = Boolean(ladder.breakeven_armed)
  const peak = Number(ladder.peak_upnl_pct ?? upnl)

  type Cand = ExitEstimate & { priority: number }
  const cands: Cand[] = []

  const guard = input.guard
  if (guard?.action === 'emergency_close' || guard?.action === 'close') {
    cands.push({
      priority: 1,
      trigger: 'guard',
      label: 'GUARD kapanış',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: guard.action === 'emergency_close' ? 'Acil kapanış tetiklendi' : 'Guard satış önerisi',
    })
  }

  if (upnl <= -sl) {
    cands.push({
      priority: 2,
      trigger: 'stop_loss',
      label: 'STOP (SL)',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `SL -${sl.toFixed(1)}% aşıldı (${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}%)`,
    })
  } else if (upnl <= -(sl - 0.25)) {
    cands.push({
      priority: 3,
      trigger: 'stop_near',
      label: 'STOP yakın',
      countdown_sec: Math.max(30, (upnl + sl) / 0.05 * 60),
      estimated_close_at: now + Math.max(30, (upnl + sl) / 0.05 * 60),
      urgency: 'imminent',
      detail: `SL -${sl.toFixed(1)}%'ye ${(sl + upnl).toFixed(2)}% kaldı`,
    })
  }

  if (upnl >= tp) {
    cands.push({
      priority: 2,
      trigger: 'take_profit',
      label: 'TP (kâr)',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `TP +${tp.toFixed(1)}% hedefi (${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}%)`,
    })
  } else if (upnl >= tp - 0.25) {
    cands.push({
      priority: 3,
      trigger: 'tp_near',
      label: 'TP yakın',
      countdown_sec: 45,
      estimated_close_at: now + 45,
      urgency: 'imminent',
      detail: `TP +${tp.toFixed(1)}%'ye ${(tp - upnl).toFixed(2)}% kaldı`,
    })
  }

  if (breakevenArmed && holdSec >= rules.BREAKEVEN_MIN_HOLD_SEC && upnl <= rules.BREAKEVEN_FLOOR_PCT) {
    cands.push({
      priority: 4,
      trigger: 'breakeven',
      label: 'Breakeven stop',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `Zirve +${peak.toFixed(2)}% → şimdi ${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}%`,
    })
  }

  if (
    sigDir !== 'flat' &&
    sigDir !== input.direction &&
    holdSec >= 60
  ) {
    cands.push({
      priority: 5,
      trigger: 'signal_reverse',
      label: 'Sinyal ters',
      countdown_sec: 30,
      estimated_close_at: now + 30,
      urgency: 'imminent',
      detail: `Anlık sinyal ${sigDir} — ters yön kapanışı beklenir`,
    })
  }

  const staleReady =
    holdSec >= rules.STALE_VERDICT_SEC &&
    (sigDir === 'flat' || sigDir !== input.direction)
  if (staleReady) {
    cands.push({
      priority: 6,
      trigger: 'stale_flat',
      label: 'Stale verdict',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `${Math.floor(holdSec / 60)}dk tutuldu, sinyal ${sigDir}`,
    })
  } else if (sigDir === 'flat' && entry > 0) {
    const remain = rules.STALE_VERDICT_SEC - holdSec
    if (remain > 0) {
      cands.push({
        priority: 8,
        trigger: 'stale_countdown',
        label: 'Flat sinyal limiti',
        countdown_sec: remain,
        estimated_close_at: now + remain,
        urgency: remain < 300 ? 'imminent' : 'normal',
        detail: `Sinyal flat — ${fmtDur(remain)} sonra stale kapanış`,
      })
    }
  }

  const maxRemain = rules.MAX_HOLD_SEC - holdSec
  if (maxRemain > 0 && entry > 0) {
    cands.push({
      priority: 9,
      trigger: 'max_hold',
      label: 'Max tutma',
      countdown_sec: maxRemain,
      estimated_close_at: now + maxRemain,
      urgency: maxRemain < 300 ? 'imminent' : 'normal',
      detail: `Zorunlu kapanış ${fmtDur(maxRemain)} (${rules.MAX_HOLD_SEC / 60}dk limit)`,
    })
  } else if (holdSec >= rules.MAX_HOLD_SEC) {
    cands.push({
      priority: 7,
      trigger: 'max_hold_over',
      label: 'Max tutma aşıldı',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `${Math.floor(holdSec / 60)}dk — kapanış bekleniyor`,
    })
  }

  // Anlık PnL hızına göre TP/SL tahmini (momentum)
  if (holdSec >= 120 && entry > 0) {
    const vel = upnl / holdSec
    if (vel > 0.00002 && upnl < tp && upnl > 0) {
      const eta = (tp - upnl) / vel
      if (eta > 30 && eta < maxRemain) {
        cands.push({
          priority: 7,
          trigger: 'tp_momentum',
          label: 'TP tahmini',
          countdown_sec: eta,
          estimated_close_at: now + eta,
          urgency: eta < 600 ? 'imminent' : 'normal',
          detail: `Hız +${(vel * 3600).toFixed(2)}%/sa → TP ~${fmtDur(eta)}`,
        })
      }
    }
    if (vel < -0.00002 && upnl > -sl) {
      const eta = (upnl + sl) / Math.abs(vel)
      if (eta > 30 && eta < maxRemain) {
        cands.push({
          priority: 7,
          trigger: 'sl_momentum',
          label: 'SL tahmini',
          countdown_sec: eta,
          estimated_close_at: now + eta,
          urgency: 'imminent',
          detail: `Hız ${(vel * 3600).toFixed(2)}%/sa → SL ~${fmtDur(eta)}`,
        })
      }
    }
  }

  if (!cands.length) {
    return {
      trigger: 'hold',
      label: 'Tutuluyor',
      countdown_sec: maxRemain > 0 ? maxRemain : rules.MAX_HOLD_SEC,
      estimated_close_at: now + (maxRemain > 0 ? maxRemain : rules.MAX_HOLD_SEC),
      urgency: 'normal',
      detail: `SL -${sl.toFixed(1)}% · TP +${tp.toFixed(1)}%`,
    }
  }

  const nowCands = cands.filter(c => c.countdown_sec <= 0)
  if (nowCands.length) {
    nowCands.sort((a, b) => a.priority - b.priority)
    const w = nowCands[0]
    return {
      trigger: w.trigger,
      label: w.label,
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: w.detail,
      secondary: nowCands[1]?.label,
    }
  }

  cands.sort((a, b) => a.countdown_sec - b.countdown_sec || a.priority - b.priority)
  const winner = cands[0]
  const runner = cands.find(c => c.trigger !== winner.trigger && c.countdown_sec > 0)

  return {
    trigger: winner.trigger,
    label: winner.label,
    countdown_sec: winner.countdown_sec,
    estimated_close_at: winner.estimated_close_at,
    urgency: winner.urgency,
    detail: winner.detail,
    secondary: runner ? `${runner.label} ${fmtDur(runner.countdown_sec)}` : undefined,
  }
}

export function formatCountdown(sec: number): string {
  if (sec <= 0) return 'ŞİMDİ'
  return fmtDur(sec)
}
