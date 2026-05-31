"""Groq / Ollama — coin-specific learning narrative (not generic templates)."""

from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

GROQ_MODEL = os.getenv("GROQ_LEARN_MODEL", "llama-3.1-70b-versatile")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")


def _get_groq():
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=key)
    except ImportError:
        return None


def _ollama_url() -> str | None:
    return os.getenv("OLLAMA_URL", "").strip() or None


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

    client = _get_groq()
    if client:
        try:
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.35,
                max_tokens=280,
            )
            data = _parse_json_response(resp.choices[0].message.content or "")
            if data and data.get("ai_insight"):
                data["llm_provider"] = "groq"
                return data
        except Exception as e:
            logger.debug(f"Groq learn {symbol}: {e}")

    ollama = _ollama_url()
    if ollama:
        try:
            payload = json.dumps({
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.35, "num_predict": 320},
            }).encode()
            req = urllib.request.Request(
                f"{ollama.rstrip('/')}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read())
            data = _parse_json_response(body.get("message", {}).get("content", ""))
            if data and data.get("ai_insight"):
                data["llm_provider"] = "ollama"
                return data
        except Exception as e:
            logger.debug(f"Ollama learn {symbol}: {e}")

    return None
