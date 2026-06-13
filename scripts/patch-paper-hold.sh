#!/usr/bin/env bash
# Paper churn fix — guard/signal_engine pozisyonları AI FLAT ile anında kapatmasın
set -euo pipefail
cd "$(dirname "$0")/.."

GUARD="services/agent_system/position_guard.py"
SIGNAL="services/signal_engine/main.py"

if [[ ! -f "$GUARD" || ! -f "$SIGNAL" ]]; then
  echo "Hata: $GUARD veya $SIGNAL bulunamadı"
  exit 1
fi

python3 <<'PY'
from pathlib import Path

guard = Path("services/agent_system/position_guard.py")
signal = Path("services/signal_engine/main.py")
g = guard.read_text(encoding="utf-8")
s = signal.read_text(encoding="utf-8")
changed = []

if "PAPER_MIN_HOLD_SEC" not in g:
    g = g.replace(
        'TAKE_PROFIT_PCT = float(os.getenv("GUARD_TAKE_PROFIT_PCT", "0.5"))\n',
        'TAKE_PROFIT_PCT = float(os.getenv("GUARD_TAKE_PROFIT_PCT", "0.5"))\n'
        'PAPER_MIN_HOLD_SEC = float(os.getenv("PAPER_MIN_HOLD_SEC", "120"))\n',
    )
    changed.append("guard: PAPER_MIN_HOLD_SEC")

if "paper_mode = is_paper_unlimited()" not in g:
    g = g.replace(
        '    avoid = str((learn or {}).get("avoid_hint", "") or "")\n\n    checks: dict = {',
        '    avoid = str((learn or {}).get("avoid_hint", "") or "")\n\n'
        '    try:\n'
        '        from risk_limits import is_paper_unlimited\n'
        '        paper_mode = is_paper_unlimited()\n'
        '    except Exception:\n'
        '        paper_mode = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")\n\n'
        '    entry_time = float(pos.get("entry_time", 0) or 0)\n'
        '    hold_sec = time.time() - entry_time if entry_time > 0 else 9999.0\n\n'
        '    checks: dict = {',
    )
    changed.append("guard: paper_mode block")

old_flat_exit = '''    if trade_action == "close" or (
        sig_dir == "flat" and v_dir == "flat" and v_conf >= flat_close_conf
    ):
        return GuardDecision(
            symbol, source, direction, "close", "high",
            "AI çıkış (FLAT) — sinyal ve verdict uyumlu",
            upnl, v_conf, trade_action, checks, time.time(),
        )

    if v_dir == "flat" and direction in ("long", "short"):
        return GuardDecision(
            symbol, source, direction, "close", "high",
            f"AI FLAT ({v_conf:.0%}) — yön uyumsuz pozisyon kapatılıyor",
            upnl, v_conf, trade_action, checks, time.time(),
        )'''

new_flat_exit = '''    flat_exit = trade_action == "close" or (
        sig_dir == "flat" and v_dir == "flat" and v_conf >= flat_close_conf
    )
    if flat_exit:
        if paper_mode and hold_sec < PAPER_MIN_HOLD_SEC and upnl > -EMERGENCY_LOSS_PCT:
            pass
        else:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                "AI çıkış (FLAT) — sinyal ve verdict uyumlu",
                upnl, v_conf, trade_action, checks, time.time(),
            )

    if v_dir == "flat" and direction in ("long", "short"):
        if paper_mode and v_conf < 0.55:
            pass
        elif paper_mode and hold_sec < PAPER_MIN_HOLD_SEC:
            pass
        else:
            return GuardDecision(
                symbol, source, direction, "close", "high",
                f"AI FLAT ({v_conf:.0%}) — yön uyumsuz pozisyon kapatılıyor",
                upnl, v_conf, trade_action, checks, time.time(),
            )'''

if old_flat_exit in g and "flat_exit = trade_action" not in g:
    g = g.replace(old_flat_exit, new_flat_exit)
    changed.append("guard: flat exit logic")

guard.write_text(g, encoding="utf-8")

old_open_pos = '''    if open_pos:
        pos_dir = open_pos.get("direction", "long")
        signal_dict["has_position"] = True
        signal_dict["position_direction"] = pos_dir
        if final_dir == "flat" or v_dir == "flat":
            signal_dict["direction"] = "flat"
            signal_dict["trade_action"] = "close"
            signal_dict["is_valid"] = True
            signal_dict["reject_reason"] = ""
            signal_dict["close_reason"] = (
                "ensemble_flat" if final_dir == "flat" else "verdict_flat"
            )
        elif final_dir == pos_dir:
            signal_dict["trade_action"] = "hold"
            if v_conf < 0.35:
                signal_dict["trade_action"] = "close"
                signal_dict["close_reason"] = "low_ai_confidence"
                signal_dict["direction"] = "flat"
                signal_dict["is_valid"] = True
                signal_dict["reject_reason"] = ""
        elif final_dir in ("long", "short") and final_dir != pos_dir:
            signal_dict["trade_action"] = "reverse"'''

new_open_pos = '''    if open_pos:
        pos_dir = open_pos.get("direction", "long")
        signal_dict["has_position"] = True
        signal_dict["position_direction"] = pos_dir
        try:
            from risk_limits import is_paper_unlimited
            paper_hold = is_paper_unlimited()
        except Exception:
            paper_hold = False

        if final_dir in ("long", "short") and final_dir == pos_dir:
            signal_dict["trade_action"] = "hold"
            if not paper_hold and v_conf < 0.35:
                signal_dict["trade_action"] = "close"
                signal_dict["close_reason"] = "low_ai_confidence"
                signal_dict["direction"] = "flat"
                signal_dict["is_valid"] = True
                signal_dict["reject_reason"] = ""
        elif final_dir in ("long", "short") and final_dir != pos_dir:
            signal_dict["trade_action"] = "reverse"
        elif final_dir == "flat" or (v_dir == "flat" and not paper_hold):
            if paper_hold and final_dir != "flat":
                signal_dict["trade_action"] = "hold"
            else:
                signal_dict["direction"] = "flat"
                signal_dict["trade_action"] = "close"
                signal_dict["is_valid"] = True
                signal_dict["reject_reason"] = ""
                signal_dict["close_reason"] = (
                    "ensemble_flat" if final_dir == "flat" else "verdict_flat"
                )'''

if "paper_hold = is_paper_unlimited()" not in s:
    if old_open_pos in s:
        s = s.replace(old_open_pos, new_open_pos)
        changed.append("signal: open_pos paper_hold")
    else:
        print("UYARI: signal_engine/main.py beklenen blok bulunamadı — elle kontrol et")

signal.write_text(s, encoding="utf-8")

if not changed:
    print("Zaten güncel — değişiklik yok")
else:
    print("Uygulandı:", ", ".join(changed))
    Path("/tmp/patch_paper_hold_changed").write_text("1")
PY

if [[ ! -f /tmp/patch_paper_hold_changed ]]; then
  echo "==> Rebuild atlandı (kod zaten güncel)"
  exit 0
fi
rm -f /tmp/patch_paper_hold_changed

grep -q "PAPER_MIN_HOLD_SEC" "$GUARD" && grep -q "paper_hold" "$SIGNAL" || {
  echo "Patch doğrulaması başarısız"
  exit 1
}

echo "==> Rebuild agent_system + signal_engine"
docker compose build agent_system signal_engine
docker compose up -d agent_system signal_engine

echo "==> Doğrula"
docker compose exec agent_system grep -c "PAPER_MIN_HOLD_SEC" position_guard.py
docker compose exec signal_engine grep -c "paper_hold" main.py
echo "Tamam. 2-3 dk sonra: KEYS oms:position:* | wc -l"
