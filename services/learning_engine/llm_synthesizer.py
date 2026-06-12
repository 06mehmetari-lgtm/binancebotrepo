"""Multi-provider LLM — coin-specific learning narrative."""

from __future__ import annotations

import json
import logging
import os

from llm_providers import chat_completion

logger = logging.getLogger(__name__)

GROQ_MODEL = os.getenv("GROQ_LEARN_MODEL", "llama-3.3-70b-versatile")


def _parse_json_response(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def synthesize_coin_insight(symbol: str, profile: dict) -> dict | None:
    """
    Returns { ai_insight, best_entry_hint?, avoid_hint?, llm_provider } or None.
    """
    stage = profile.get("learning_stage", "L0")
    if stage in ("L0",) and profile.get("updates", 0) < 10:
        return None

    drivers = profile.get("drivers", [])[:5]
    fp = profile.get("fingerprint", {})
    transitions = profile.get("regime_transitions", [])[:4]

    prompt = (
        f"Sen kripto vadeli işlem öğrenme motorusun. {symbol} için SADECE verilen istatistiklere dayan; "
        f"genel şablon kullanma. Her coin farklı olmalı.\n\n"
        f"Seviye: {stage} | Gözlem: {profile.get('updates', 0)} | Rejim: {profile.get('current_regime')}\n"
        f"Parmak izi: RSI ort={fp.get('rsi_avg', '?')}, funding ort={fp.get('funding_avg', '?')}, "
        f"MACD ort={fp.get('macd_avg', '?')}, vol oranı={fp.get('volume_ratio_avg', '?')}\n"
        f"Faktörler (3 adım sonrası doğruluk): {json.dumps(drivers, ensure_ascii=False)}\n"
        f"Rejim geçişleri: {json.dumps(transitions, ensure_ascii=False)}\n"
        f"Mevcut giriş ipucu: {profile.get('best_entry_hint', '')}\n"
        f"Mevcut kaçın: {profile.get('avoid_hint', '')}\n\n"
        "Yanıt YALNIZCA JSON:\n"
        '{"ai_insight":"2-3 cümle Türkçe — bu coine özel davranış ve edge",'
        '"best_entry_hint":"tek satır giriş kuralı",'
        '"avoid_hint":"tek satır kaçınma kuralı"}'
    )

    raw, provider = chat_completion(
        prompt,
        max_tokens=320,
        temperature=0.35,
        model_pool="learning",
    )
    if not raw:
        return None
    data = _parse_json_response(raw)
    if data and data.get("ai_insight"):
        data["llm_provider"] = provider or "llm"
        return data
    return None


def synthesize_position_track(symbol: str, payload: dict) -> dict | None:
    """Ollama/yerel LLM — 3 grafik (blueprint/canlı/analiz) dersi, kâr odaklı."""
    mismatch = payload.get("mismatch") or {}
    tick = payload.get("tick") or {}
    sev = mismatch.get("severity", "ok")
    consensus = payload.get("consensus") or {}
    if sev not in ("warn", "critical", "drift") and consensus.get("action") == "hold":
        return None

    blueprint = payload.get("blueprint") or {}
    rolling = payload.get("rolling") or {}
    why_move = payload.get("why_move") or rolling.get("narrative") or ""

    prompt = (
        f"Sen kripto grafik beyni koçusun. {symbol} açık pozisyon — 3 katman birlikte değerlendir:\n"
        f"1) AL BLUEPRINT (donmuş plan): {blueprint.get('narrative', '')[:200]}\n"
        f"   Nedenler: {blueprint.get('reasons', [])}\n"
        f"2) CANLI GRAFİK: fiyat {tick.get('price')} PnL {tick.get('upnl_pct', 0):+.2f}% "
        f"RSI bağlam | hacim {tick.get('volume_ratio', 1)}\n"
        f"3) SÜREKLİ ANALİZ: {rolling.get('narrative', '')[:180]}\n"
        f"Neden hareket: {why_move[:200]}\n"
        f"Sapma: {mismatch.get('pct', 0):.2f}% ({mismatch.get('why', '')}) | "
        f"Konsensüs: {consensus.get('action')} — {consensus.get('reasons', [])}\n"
        "GÖREV: Neden düşüyor/çıkıyor açıkla. Kâr koru, zarar kes. Türkçe 2-3 cümle.\n"
        'JSON: {"lesson":"...","why_up_down":"...","action":"hold|tighten_stop|take_partial|close",'
        '"profit_focus":"...","chart_pattern":"false_breakout|plan_aligned|momentum_fade|..."}'
    )
    raw, provider = chat_completion(
        prompt,
        max_tokens=200,
        temperature=0.25,
        model_pool="learning",
    )
    if not raw:
        return None
    data = _parse_json_response(raw)
    if data and data.get("lesson"):
        data["llm_provider"] = provider or "ollama"
        return data
    return None
