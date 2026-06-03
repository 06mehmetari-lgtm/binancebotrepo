"""
Güvenilir proxy/relay rotasyonu — PROXY_URL_1..N, LLM_RELAY_URL_1..N, PROXY_LIST.

Ücretsiz halka açık proxy listeleri API anahtarları için GÜVENLİ DEĞİL (çalınma riski).
Kendi proxy'leriniz: ev SOCKS, cloudflared relay, satın aldığınız residential.
"""

from __future__ import annotations

import os
import threading
import time

_lock = threading.Lock()
_proxy_idx = 0
_relay_idx = 0
_bad_proxy_until: dict[str, float] = {}
_bad_relay_until: dict[str, float] = {}

COOLDOWN_SEC = float(os.getenv("PROXY_FAIL_COOLDOWN_SEC", "300"))


def _slots() -> int:
    try:
        return max(1, min(128, int(os.getenv("PROXY_POOL_SLOTS", "64"))))
    except ValueError:
        return 64


def _collect_env_list(prefix: str, list_env: str | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    if list_env:
        raw = (os.getenv(list_env, "") or "").strip()
        if raw:
            for part in raw.split(","):
                u = part.strip()
                if u and u not in seen:
                    seen.add(u)
                    out.append(u)
    for i in range(1, _slots() + 1):
        u = (os.getenv(f"{prefix}_{i}", "") or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    primary = (os.getenv(prefix, "") or "").strip()
    if primary and primary not in seen:
        out.insert(0, primary)
    return out


def proxy_urls() -> list[str]:
    urls = _collect_env_list("PROXY_URL", "PROXY_LIST")
    for env in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        u = (os.getenv(env, "") or "").strip()
        if u and u not in urls:
            urls.insert(0, u)
    return [u for u in urls if u and not _is_bad(u, _bad_proxy_until)]


def relay_urls() -> list[str]:
    return _collect_env_list("LLM_RELAY_URL", "LLM_RELAY_LIST")


def _is_bad(url: str, bad_map: dict[str, float]) -> bool:
    until = bad_map.get(url, 0)
    return until > time.time()


def mark_proxy_bad(url: str) -> None:
    with _lock:
        _bad_proxy_until[url] = time.time() + COOLDOWN_SEC


def mark_relay_bad(url: str) -> None:
    with _lock:
        _bad_relay_until[url] = time.time() + COOLDOWN_SEC


def next_proxy() -> str | None:
    global _proxy_idx
    pool = proxy_urls()
    if not pool:
        return None
    with _lock:
        url = pool[_proxy_idx % len(pool)]
        _proxy_idx += 1
    return url


def relay_bases_for(provider: str) -> list[str]:
    """groq -> .../groq/v1  cerebras -> .../cerebras/v1"""
    relays = [r for r in relay_urls() if not _is_bad(r, _bad_relay_until)]
    if not relays:
        return []
    suffix = f"/{provider}/v1"
    return [f"{r.rstrip('/')}{suffix}" for r in relays]


def all_proxy_attempts() -> list[str | None]:
    """None = direct (no proxy). Rotated order, skips cooled-down entries."""
    pool = proxy_urls()
    if not pool:
        single = (
            os.getenv("HTTPS_PROXY")
            or os.getenv("HTTP_PROXY")
            or os.getenv("ALL_PROXY")
            or ""
        ).strip()
        return [single or None]
    global _proxy_idx
    with _lock:
        start = _proxy_idx % len(pool)
        _proxy_idx += 1
    ordered = pool[start:] + pool[:start]
    return ordered


def status_snapshot() -> dict:
    return {
        "proxy_count": len(proxy_urls()),
        "relay_count": len(relay_urls()),
        "proxy_cooled_down": len(_bad_proxy_until),
        "relay_cooled_down": len(_bad_relay_until),
    }
