/**
 * Çıkış tahmini — services/shared/profit_rules.py + shadow_system/main.py ile uyumlu.
 * Anlık tarama: TP/SL, stale_flat, breakeven, guard, momentum → en yakın kapanış.
 */

export const EXIT_RULES = {
  MAX_HOLD_SEC: 3600,
  STALE_VERDICT_SEC: 1800,
  STALE_EXIT_GRACE_SEC: 900,
  STALE_EXIT_MIN_LOSS_PCT: -0.25,
  RECOVERY_HOLD_UPNL_MIN: -0.55,
  RECOVERY_HOLD_UPNL_MAX: 0.35,
  SCRATCH_EXIT_MAX_LOSS_PCT: -0.12,
  SOFT_STOP_LOSS_PCT: -0.85,
  RECOVERY_BOUNCE_MIN_PCT: 0.12,
  LOSS_TO_PROFIT_TARGET_PCT: 0.05,
  TRAIL_TIER_1_PEAK: 1.5,
  TRAIL_TIER_1_GIVE: 0.4,
  TRAIL_TIER_2_PEAK: 3.0,
  TRAIL_TIER_2_GIVE: 0.8,
  TRAIL_TIER_3_PEAK: 6.0,
  TRAIL_TIER_3_GIVE: 1.5,
  MIN_RECOVERY_HOLD_SEC: 300,
  RECOVERY_SIGNAL_MIN_CONF: 0.55,
  GUARD_TAKE_PROFIT_PCT: 1.2,
  BREAKEVEN_ACTIVATE_PCT: 0.35,
  BREAKEVEN_FLOOR_PCT: 0.08,
  BREAKEVEN_MIN_HOLD_SEC: 120,
  DEFAULT_SL_PCT: 1.2,
  DEFAULT_TP_PCT: 1.5,
  AGENT_STALE_CONF: 0.15,
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
  computed_at: number
}

type LadderLike = {
  stop_loss_pct?: number
  take_profit_pct?: number
  breakeven_armed?: boolean
  peak_upnl_pct?: number
  trough_upnl_pct?: number
  bounce_from_trough_pct?: number
  recovery_armed?: boolean
  trail_floor_pct?: number
}

type GuardLike = {
  action?: string
  urgency?: string
}

type Cand = ExitEstimate & { priority: number }

function fmtDur(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  return `${m}:${String(r).padStart(2, '0')}`
}

function isStaleContext(
  sigDir: string,
  posDir: string,
  vDir: string,
  vConf: number,
  rules: typeof EXIT_RULES,
): boolean {
  return (
    sigDir === 'flat'
    || (sigDir === 'long' || sigDir === 'short') && sigDir !== posDir
    || (vDir === 'flat' && vConf >= rules.AGENT_STALE_CONF)
  )
}

/** profit_rules.stale_flat_should_exit + grace penceresi ETA */
function staleExitCandidate(
  holdSec: number,
  upnl: number,
  peak: number,
  sigDir: string,
  posDir: string,
  vDir: string,
  vConf: number,
  now: number,
  rules: typeof EXIT_RULES,
): Cand | null {
  const staleCtx = isStaleContext(sigDir, posDir, vDir, vConf, rules)
  const graceEnd = rules.STALE_VERDICT_SEC + rules.STALE_EXIT_GRACE_SEC

  if (holdSec < rules.STALE_VERDICT_SEC) {
    if (!staleCtx) return null
    const remain = rules.STALE_VERDICT_SEC - holdSec
    return {
      priority: 8,
      trigger: 'stale_window',
      label: 'Flat/ajan limiti',
      countdown_sec: remain,
      estimated_close_at: now + remain,
      urgency: remain < 300 ? 'imminent' : 'normal',
      detail: `Sinyal ${sigDir} · ajan ${vDir} ${Math.round(vConf * 100)}% → ${fmtDur(remain)} sonra stale kontrol`,
      computed_at: now,
    }
  }

  if (!staleCtx) return null

  if (upnl >= rules.GUARD_TAKE_PROFIT_PCT * 0.75) {
    return {
      priority: 2,
      trigger: 'stale_take_profit',
      label: 'Stale kâr çıkışı',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `Stale + uPnL ${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}% ≥ TP eşiği`,
      computed_at: now,
    }
  }

  if (peak >= rules.BREAKEVEN_ACTIVATE_PCT && upnl >= rules.BREAKEVEN_FLOOR_PCT) {
    const toMax = rules.MAX_HOLD_SEC - holdSec
    return {
      priority: 12,
      trigger: 'breakeven_stale_hold',
      label: 'Breakeven koruması',
      countdown_sec: Math.max(60, toMax),
      estimated_close_at: now + Math.max(60, toMax),
      urgency: 'normal',
      detail: `Zirve +${peak.toFixed(2)}% — stale ertelendi, max tutma ${fmtDur(toMax)}`,
      computed_at: now,
    }
  }

  if (
    upnl >= rules.RECOVERY_HOLD_UPNL_MIN
    && upnl <= rules.RECOVERY_HOLD_UPNL_MAX
    && holdSec < graceEnd
  ) {
    const remain = graceEnd - holdSec
    return {
      priority: 6,
      trigger: 'recovery_grace',
      label: 'Toparlanma süresi',
      countdown_sec: remain,
      estimated_close_at: now + remain,
      urgency: remain < 180 ? 'imminent' : 'normal',
      detail: `uPnL ${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}% — grace ${fmtDur(remain)}`,
      computed_at: now,
    }
  }

  if (upnl > rules.STALE_EXIT_MIN_LOSS_PCT && upnl < 0.12 && holdSec < graceEnd) {
    const remain = graceEnd - holdSec
    return {
      priority: 7,
      trigger: 'near_breakeven_grace',
      label: 'Başabaş bekleme',
      countdown_sec: remain,
      estimated_close_at: now + remain,
      urgency: remain < 180 ? 'imminent' : 'normal',
      detail: `Zarar sınırı öncesi — ${fmtDur(remain)} grace`,
      computed_at: now,
    }
  }

  if (upnl <= rules.STALE_EXIT_MIN_LOSS_PCT) {
    return {
      priority: 3,
      trigger: 'stale_flat_loss',
      label: 'Stale zarar',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `Stale zarar eşiği ${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}%`,
      computed_at: now,
    }
  }

  if (holdSec >= graceEnd) {
    return {
      priority: 4,
      trigger: 'stale_flat_timeout',
      label: 'Stale timeout',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `Grace bitti — stale kapanış (${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}%)`,
      computed_at: now,
    }
  }

  const remain = graceEnd - holdSec
  return {
    priority: 7,
    trigger: 'stale_grace',
    label: 'Stale grace',
    countdown_sec: remain,
    estimated_close_at: now + remain,
    urgency: remain < 300 ? 'imminent' : 'normal',
    detail: `Flat/ajan stale — en geç ${fmtDur(remain)}`,
    computed_at: now,
  }
}

function dynamicTrailFloor(
  peak: number,
  breakevenArmed: boolean,
  rules: typeof EXIT_RULES,
): number {
  if (peak >= rules.TRAIL_TIER_3_PEAK) return peak - rules.TRAIL_TIER_3_GIVE
  if (peak >= rules.TRAIL_TIER_2_PEAK) return peak - rules.TRAIL_TIER_2_GIVE
  if (peak >= rules.TRAIL_TIER_1_PEAK) return peak - rules.TRAIL_TIER_1_GIVE
  if (peak >= rules.BREAKEVEN_ACTIVATE_PCT || breakevenArmed) return rules.BREAKEVEN_FLOOR_PCT
  return -999
}

function momentumEta(
  upnl: number,
  target: number,
  velPctPerSec: number,
  holdSec: number,
  maxRemain: number,
  now: number,
  kind: 'tp' | 'sl',
): Cand | null {
  if (holdSec < 90 || Math.abs(velPctPerSec) < 1e-8) return null
  const delta = kind === 'tp' ? target - upnl : upnl + target
  if (delta <= 0) return null
  const eta = delta / Math.abs(velPctPerSec)
  if (eta < 15 || eta > Math.min(maxRemain, 7200)) return null
  const perHour = velPctPerSec * 3600
  return {
    priority: kind === 'tp' ? 5 : 5,
    trigger: kind === 'tp' ? 'tp_momentum' : 'sl_momentum',
    label: kind === 'tp' ? 'TP momentum' : 'SL momentum',
    countdown_sec: eta,
    estimated_close_at: now + eta,
    urgency: eta < 600 ? 'imminent' : 'normal',
    detail: `Hız ${perHour >= 0 ? '+' : ''}${perHour.toFixed(2)}%/sa → ~${fmtDur(eta)}`,
    computed_at: now,
  }
}

export function computeExitEstimate(input: {
  entry_time?: number
  direction: string
  unrealized_pct: number
  ladder?: LadderLike
  guard?: GuardLike
  current_signal_direction?: string
  current_signal_confidence?: number
  agent_verdict_direction?: string
  agent_verdict_confidence?: number
  pnl_velocity_pct_per_sec?: number
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
  const vDir = input.agent_verdict_direction ?? 'flat'
  const vConf = Number(input.agent_verdict_confidence ?? 0)
  const breakevenArmed = Boolean(ladder.breakeven_armed)
  const peak = Number(ladder.peak_upnl_pct ?? upnl)
  const vel = input.pnl_velocity_pct_per_sec ?? 0
  const maxRemain = Math.max(0, rules.MAX_HOLD_SEC - holdSec)

  const trough = Number(ladder.trough_upnl_pct ?? upnl)
  const bounce = Number(ladder.bounce_from_trough_pct ?? (upnl - trough))
  const recoveryArmed = Boolean(ladder.recovery_armed)
  const trailFloor = Number(
    ladder.trail_floor_pct ?? dynamicTrailFloor(peak, breakevenArmed, rules),
  )
  const sigConf = Number(input.current_signal_confidence ?? 0)
  const sigSupports =
    (sigDir === input.direction && sigConf >= rules.RECOVERY_SIGNAL_MIN_CONF)
    || (vDir === input.direction && vConf >= 0.38)
    || (sigDir === input.direction && vDir === input.direction)
  const recoveryHold =
    upnl < 0
    && (
      (upnl >= rules.RECOVERY_HOLD_UPNL_MIN && upnl <= rules.RECOVERY_HOLD_UPNL_MAX && sigSupports)
      || bounce >= rules.RECOVERY_BOUNCE_MIN_PCT
      || recoveryArmed
    )

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
      computed_at: now,
    })
  }

  if (upnl <= -sl && !recoveryHold) {
    cands.push({
      priority: 2,
      trigger: 'stop_loss',
      label: 'STOP (SL)',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `SL -${sl.toFixed(1)}% aşıldı (${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}%)`,
      computed_at: now,
    })
  } else if (upnl <= rules.SOFT_STOP_LOSS_PCT && !recoveryHold) {
    cands.push({
      priority: 4,
      trigger: 'soft_stop',
      label: 'Soft stop',
      countdown_sec: recoveryHold ? 180 : 45,
      estimated_close_at: now + (recoveryHold ? 180 : 45),
      urgency: 'imminent',
      detail: `Akıllı kesim ${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}% (hard SL öncesi)`,
      computed_at: now,
    })
  } else if (upnl <= -(sl - 0.2)) {
    const mom = momentumEta(upnl, -sl, vel, holdSec, maxRemain, now, 'sl')
    const eta = mom?.countdown_sec ?? Math.max(20, ((sl + upnl) / 0.04) * 30)
    cands.push({
      priority: 3,
      trigger: 'stop_near',
      label: 'STOP yakın',
      countdown_sec: eta,
      estimated_close_at: now + eta,
      urgency: 'imminent',
      detail: `SL -${sl.toFixed(1)}%'ye ${(sl + upnl).toFixed(2)}% kaldı`,
      computed_at: now,
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
      computed_at: now,
    })
  } else if (upnl >= tp - 0.25) {
    cands.push({
      priority: 3,
      trigger: 'tp_near',
      label: 'TP yakın',
      countdown_sec: 25,
      estimated_close_at: now + 25,
      urgency: 'imminent',
      detail: `TP +${tp.toFixed(1)}%'ye ${(tp - upnl).toFixed(2)}% kaldı`,
      computed_at: now,
    })
  }

  if (recoveryArmed && upnl >= rules.LOSS_TO_PROFIT_TARGET_PCT) {
    cands.push({
      priority: 2,
      trigger: 'recovery_profit',
      label: 'Zarardan kâr',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `Dip ${trough >= 0 ? '+' : ''}${trough.toFixed(2)}% → +${upnl.toFixed(2)}% realize`,
      computed_at: now,
    })
  }

  if (trailFloor > -900 && holdSec >= 120 && upnl <= trailFloor && peak >= rules.BREAKEVEN_ACTIVATE_PCT) {
    cands.push({
      priority: 3,
      trigger: 'trail',
      label: 'Trailing stop',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `Zirve +${peak.toFixed(2)}% taban ${trailFloor >= 0 ? '+' : ''}${trailFloor.toFixed(2)}%`,
      computed_at: now,
    })
  }

  if (breakevenArmed && holdSec >= rules.BREAKEVEN_MIN_HOLD_SEC && upnl <= rules.BREAKEVEN_FLOOR_PCT && !recoveryHold) {
    cands.push({
      priority: 4,
      trigger: 'breakeven',
      label: 'Breakeven stop',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `Zirve +${peak.toFixed(2)}% → şimdi ${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}%`,
      computed_at: now,
    })
  }

  if (recoveryHold && upnl < rules.LOSS_TO_PROFIT_TARGET_PCT) {
    const eta = recoveryArmed
      ? Math.max(30, (rules.LOSS_TO_PROFIT_TARGET_PCT - upnl) / Math.max(vel, 0.0003))
      : Math.max(60, rules.STALE_EXIT_GRACE_SEC / 3)
    cands.push({
      priority: 5,
      trigger: 'recovery_hold',
      label: 'Toparlanma',
      countdown_sec: Math.min(eta, maxRemain > 0 ? maxRemain : eta),
      estimated_close_at: now + Math.min(eta, maxRemain > 0 ? maxRemain : eta),
      urgency: 'normal',
      detail: recoveryArmed
        ? `Hedef +${rules.LOSS_TO_PROFIT_TARGET_PCT}% (dip ${trough >= 0 ? '+' : ''}${trough.toFixed(2)}%)`
        : `Bounce ${bounce >= 0 ? '+' : ''}${bounce.toFixed(2)}% · sinyal destek`,
      computed_at: now,
    })
  }

  if (
    isStaleContext(sigDir, input.direction, vDir, vConf, rules)
    && upnl > rules.SCRATCH_EXIT_MAX_LOSS_PCT
    && upnl <= rules.STALE_EXIT_MIN_LOSS_PCT
    && !recoveryHold
    && holdSec >= rules.STALE_VERDICT_SEC
  ) {
    cands.push({
      priority: 3,
      trigger: 'scratch',
      label: 'Scratch çıkış',
      countdown_sec: 15,
      estimated_close_at: now + 15,
      urgency: 'imminent',
      detail: `Stale + toparlanma yok → ${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}% kes`,
      computed_at: now,
    })
  }

  if (sigDir !== 'flat' && sigDir !== input.direction && holdSec >= 45 && !recoveryHold) {
    cands.push({
      priority: 5,
      trigger: 'signal_reverse',
      label: 'Sinyal ters',
      countdown_sec: 20,
      estimated_close_at: now + 20,
      urgency: 'imminent',
      detail: `Anlık sinyal ${sigDir} — ters yön kapanışı`,
      computed_at: now,
    })
  }

  const staleCand = staleExitCandidate(
    holdSec, upnl, peak, sigDir, input.direction, vDir, vConf, now, rules,
  )
  if (staleCand) cands.push(staleCand)

  if (vel > 0 && upnl < tp && upnl > -0.05) {
    const m = momentumEta(upnl, tp, vel, holdSec, maxRemain, now, 'tp')
    if (m) cands.push(m)
  }
  if (vel < 0 && upnl > -sl) {
    const m = momentumEta(upnl, sl, vel, holdSec, maxRemain, now, 'sl')
    if (m) cands.push(m)
  }

  if (maxRemain > 0 && entry > 0) {
    cands.push({
      priority: 11,
      trigger: 'max_hold',
      label: 'Max tutma',
      countdown_sec: maxRemain,
      estimated_close_at: now + maxRemain,
      urgency: maxRemain < 300 ? 'imminent' : 'normal',
      detail: `Zorunlu kapanış ${fmtDur(maxRemain)} (${rules.MAX_HOLD_SEC / 60}dk)`,
      computed_at: now,
    })
  } else if (holdSec >= rules.MAX_HOLD_SEC && entry > 0) {
    cands.push({
      priority: 6,
      trigger: 'max_hold_over',
      label: 'Max tutma aşıldı',
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: `${Math.floor(holdSec / 60)}dk — zorunlu kapanış bekleniyor`,
      computed_at: now,
    })
  }

  if (!cands.length) {
    return {
      trigger: 'hold',
      label: 'Tutuluyor',
      countdown_sec: maxRemain > 0 ? maxRemain : rules.MAX_HOLD_SEC,
      estimated_close_at: now + (maxRemain > 0 ? maxRemain : rules.MAX_HOLD_SEC),
      urgency: 'normal',
      detail: `SL -${sl.toFixed(1)}% · TP +${tp.toFixed(1)}%`,
      computed_at: now,
    }
  }

  const nowCands = cands.filter(c => c.countdown_sec <= 0)
  if (nowCands.length) {
    nowCands.sort((a, b) => a.priority - b.priority)
    const w = nowCands[0]
    const runner = cands
      .filter(c => c.countdown_sec > 0)
      .sort((a, b) => a.countdown_sec - b.countdown_sec)[0]
    return {
      trigger: w.trigger,
      label: w.label,
      countdown_sec: 0,
      estimated_close_at: now,
      urgency: 'now',
      detail: w.detail,
      secondary: runner ? `${runner.label} ${fmtDur(runner.countdown_sec)}` : undefined,
      computed_at: now,
    }
  }

  cands.sort((a, b) => a.countdown_sec - b.countdown_sec || a.priority - b.priority)
  const winner = cands[0]
  const runner = cands.find(c => c.trigger !== winner.trigger && c.countdown_sec > winner.countdown_sec)

  return {
    trigger: winner.trigger,
    label: winner.label,
    countdown_sec: winner.countdown_sec,
    estimated_close_at: winner.estimated_close_at,
    urgency: winner.urgency,
    detail: winner.detail,
    secondary: runner ? `${runner.label} ${fmtDur(runner.countdown_sec)}` : undefined,
    computed_at: now,
  }
}

/** Son N örnekten %/sn hız — anlık TP/SL tahmini için */
export function pnlVelocityPctPerSec(
  samples: { t: number; upnl: number }[],
  windowSec = 90,
): number {
  if (samples.length < 2) return 0
  const now = samples[samples.length - 1].t
  const cutoff = now - windowSec
  const window = samples.filter(s => s.t >= cutoff)
  if (window.length < 2) return 0
  const first = window[0]
  const last = window[window.length - 1]
  const dt = last.t - first.t
  if (dt < 5) return 0
  return (last.upnl - first.upnl) / dt
}

export function formatCountdown(sec: number): string {
  if (sec <= 0) return 'ŞİMDİ'
  return fmtDur(sec)
}
