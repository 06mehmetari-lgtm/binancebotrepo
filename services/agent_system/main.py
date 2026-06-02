import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from debate_agent import DebateAgent
from regime_router import get_weights_for_regime
from groq_news_scanner import GroqNewsScanner
from lesson_writer import lesson_writer_loop
from event_learner import event_learner_loop, learn_from_debate
from strategy_extractor import strategy_extractor_loop
from system_observer import system_observer_loop
import rag_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SYMBOL_REFRESH_INTERVAL = 300

debate = DebateAgent()
news_scanner = GroqNewsScanner()


async def discover_symbols(redis: aioredis.Redis) -> list[str]:
    keys = await redis.keys("features:latest:*")
    if not keys:
        return []
    return sorted(
        (k.decode() if isinstance(k, bytes) else k).replace("features:latest:", "").upper()
        for k in keys
    )


async def run_debate_for_symbol(redis: aioredis.Redis, symbol: str):
    feat_raw = await redis.get(f"features:latest:{symbol}")
    ctx_raw = await redis.get(f"context:latest:{symbol}")

    if not feat_raw or not ctx_raw:
        return

    features = json.loads(feat_raw)
    context = json.loads(ctx_raw)

    # Faz 3: benzer geçmiş durumları Qdrant'tan çek (async, event loop bloke etmez)
    rag_block = await rag_context.fetch_similar(symbol, features, context, limit=3)

    result = await debate.run_debate(
        symbol, features, context,
        training_context=_training_context,
        rag_block=rag_block,
        learned_patterns=_learned_patterns,
    )

    # Serialize votes
    votes_payload = [
        {
            "agent": v.agent_name,
            "signal": v.signal,
            "confidence": v.confidence,
            "direction": v.signal,
        }
        for v in result.all_votes
    ]

    await redis.set(f"agents:verdicts:{symbol}", json.dumps(votes_payload), ex=180)

    # Also store final verdict for signal engine
    verdict = {
        "symbol": symbol,
        "direction": result.final_signal,
        "confidence": result.final_confidence,
        "consensus": result.consensus_strength,
        "reasoning": result.majority_reasoning,
        "vote_count": len(result.all_votes),
        "timestamp": time.time(),
    }
    await redis.set(f"agents:verdict:{symbol}", json.dumps(verdict), ex=180)
    await redis.publish(f"ch:agents:{symbol}", symbol)

    if result.final_signal != "flat":
        log.info(
            f"[{symbol}] {result.final_signal.upper()} conf={result.final_confidence:.2f} "
            f"consensus={result.consensus_strength:.0%} ({len(result.all_votes)} agents)"
        )
        # Faz 2: yüksek güvenli sinyallerden kalıp dersi üret
        try:
            feat_raw = await redis.get(f"features:latest:{symbol}")
            features = json.loads(feat_raw) if feat_raw else None
            verdict_with_regime = {
                **verdict,
                "regime": context.get("regime", features.get("regime", "unknown") if features else "unknown"),
            }
            await learn_from_debate(redis, symbol, verdict_with_regime, features)
        except Exception as _e:
            log.debug(f"Debate lesson hata {symbol}: {_e}")


_current_regime: str = "unknown"
_training_context: str = ""
_learned_patterns: dict = {}  # {regime:direction → win_rate, regime:direction:n → count}


async def reload_training_context(redis: aioredis.Redis) -> str:
    """
    Tüm öğrenme kaynaklarını birleştir:
      1. PDF eğitim dökümanları
      2. Trade kapanış dersleri (lesson_writer)
      3. Sinyal kalıp dersleri (event_learner)
      4. Rejim değişim dersleri (event_learner)
      5. Blok dersleri — neden bloklandı (event_learner)
    """
    sections = []

    # 1. PDF dökümanları
    try:
        raw = await redis.get("training:docs")
        if raw:
            docs = json.loads(raw)
            if docs:
                parts = [f"[{d.get('title','doc')}]\n{d.get('content','')}" for d in docs[:8]]
                sections.append("PDF TRAINING DOCUMENTS:\n" + "\n---\n".join(parts))
    except Exception:
        pass

    # 2. Trade kapanış dersleri (son 8)
    try:
        raws = await redis.lrange("training:lessons", 0, 7)
        lessons = _extract_lessons(raws)
        if lessons:
            sections.append(
                "SON TRADE DERSLERİ (gerçek işlemlerden — bu hatalar tekrar edilmemeli):\n"
                + "\n\n".join(lessons)
            )
    except Exception:
        pass

    # 3. Sinyal kalıp dersleri (son 5)
    try:
        raws = await redis.lrange("training:lessons:signals", 0, 4)
        lessons = _extract_lessons(raws)
        if lessons:
            sections.append(
                "SİNYAL KALIP DERSLERİ (hangi göstergeler hangi sinyali üretiyor):\n"
                + "\n\n".join(lessons)
            )
    except Exception:
        pass

    # 4. Rejim dersleri (son 3)
    try:
        raws = await redis.lrange("training:lessons:regime", 0, 2)
        lessons = _extract_lessons(raws)
        if lessons:
            sections.append(
                "PİYASA REJİM DEĞİŞİM DERSLERİ (yeni rejimde nasıl davranılmalı):\n"
                + "\n\n".join(lessons)
            )
    except Exception:
        pass

    # 5. Blok dersleri (son 3)
    try:
        raws = await redis.lrange("training:lessons:blocked", 0, 2)
        lessons = _extract_lessons(raws)
        if lessons:
            sections.append(
                "RİSK BLOKLARI (immunity sistemi neden engelledi, gelecekte ne yapılmalı):\n"
                + "\n\n".join(lessons)
            )
    except Exception:
        pass

    # 6. AI tarafından üretilmiş strateji belgesi (en güncel)
    try:
        docs_raw = await redis.get("training:docs")
        if docs_raw:
            docs = json.loads(docs_raw)
            for doc in docs:
                if doc.get("title", "").startswith("AI Öğrenilmiş Strateji"):
                    sections.append(
                        f"AI ÖĞRENILMIŞ STRATEJİ BELGESİ ({doc['title']}):\n"
                        + doc.get("content", "")[:2000]
                    )
                    break  # sadece en yenisi
    except Exception:
        pass

    return "\n\n===\n\n".join(sections)


def _extract_lessons(raws: list) -> list[str]:
    """JSON listesinden lesson metinlerini çıkar."""
    out = []
    for r in raws:
        try:
            ld = json.loads(r)
            txt = ld.get("lesson", "")
            if txt:
                out.append(txt)
        except Exception:
            pass
    return out


async def _groq_analyze_queued(raw_text: str, filename: str) -> str:
    """Send queued PDF text to multi-provider LLM for structured analysis."""
    from llm_client import chat_completion
    truncated = raw_text[:12000]
    prompt = (
        f'Analyze this trading/financial document ("{filename}") as operator instructions '
        f"for an automated crypto futures trading system.\n\n"
        f"RAW TEXT:\n---\n{truncated}\n---\n\n"
        f"Produce a structured summary: trading rules, price levels, indicators, "
        f"chart descriptions (from captions/labels in the text), risk parameters, "
        f"author conclusions. Be specific with numbers. Write in English."
    )
    content, provider = await chat_completion(prompt, max_tokens=4096)
    log.info(f"Training queue: PDF analizi tamamlandı [{provider}]")
    return content


# Lock to prevent concurrent writes to training:docs
_docs_write_lock = asyncio.Lock()


async def _analyze_item(redis: aioredis.Redis, item_raw: str) -> tuple[dict | None, str | None, str | None]:
    """
    LLM analysis only — no Redis write to training:docs.
    Returns (item_dict, item_id, analysed_text) on success,
            (item_dict, item_id, None) on rate-limit,
            (None, None, None) on hard error.
    """
    item: dict = {}
    item_id = ""
    try:
        item = json.loads(item_raw)
        item_id = item.get("id", "")

        status_raw = await redis.get(f"training:queue:status:{item_id}")
        if status_raw and json.loads(status_raw).get("status") == "done":
            return item, item_id, "__already_done__"

        await redis.set(
            f"training:queue:status:{item_id}",
            json.dumps({"status": "processing", "started_at": time.time()}),
            ex=3600,
        )

        analysed = await _groq_analyze_queued(item.get("raw_text", ""), item.get("filename", "doc"))
        return item, item_id, analysed

    except ValueError as e:
        if "429" in str(e) or "rate_limit" in str(e):
            log.warning(f"Training queue rate limit — tekrar denenecek: {item.get('filename','')}")
            if item_id:
                await redis.set(
                    f"training:queue:status:{item_id}",
                    json.dumps({"status": "pending", "error": "rate_limit", "retry_after": time.time() + 65}),
                    ex=86400,
                )
            return item, item_id, None  # stay in queue
        else:
            log.error(f"Training queue error: {e}")
            if item_id:
                await redis.set(
                    f"training:queue:status:{item_id}",
                    json.dumps({"status": "error", "error": str(e)}),
                    ex=86400,
                )
            return item, item_id, "__error__"
    except Exception as e:
        log.error(f"Training queue unexpected error: {e}")
        if item_id:
            await redis.set(
                f"training:queue:status:{item_id}",
                json.dumps({"status": "error", "error": str(e)[:200]}),
                ex=86400,
            )
        return item, item_id, "__error__"


async def _save_doc(redis: aioredis.Redis, item: dict, item_id: str, analysed: str):
    """Write one doc to training:docs under lock — prevents parallel overwrite."""
    async with _docs_write_lock:
        docs_raw = await redis.get("training:docs")
        docs = json.loads(docs_raw) if docs_raw else []
        # Avoid duplicates
        if any(d.get("id") == item_id for d in docs):
            return
        docs.insert(0, {
            "id": item_id,
            "title": item.get("title", item.get("filename", "PDF")),
            "content": analysed,
            "source": "pdf",
            "filename": item.get("filename", ""),
            "created_at": item.get("created_at", time.time()),
        })
        await redis.set("training:docs", json.dumps(docs))

    await redis.set(
        f"training:queue:status:{item_id}",
        json.dumps({"status": "done", "processed_at": time.time()}),
        ex=86400 * 7,
    )
    log.info(f"Training queue: '{item.get('title','')}' öğrenildi ({item.get('filename','')})")


async def _process_training_queue_batch(redis: aioredis.Redis, batch_size: int = 4):
    """Analyse up to batch_size PDFs in parallel, then save results sequentially."""
    all_items = await redis.lrange("training:queue", 0, -1)
    if not all_items:
        return

    # Collect pending (skip done/in-flight)
    pending = []
    done_ids: set[str] = set()
    for raw in all_items:
        try:
            item = json.loads(raw)
            item_id = item.get("id", "")
            status_raw = await redis.get(f"training:queue:status:{item_id}")
            if status_raw:
                st = json.loads(status_raw).get("status")
                if st == "done":
                    done_ids.add(item_id)
                    continue
                if st == "processing":
                    continue
            pending.append((item_id, raw))
        except Exception:
            continue

    # Drain fully-done items from queue head
    while True:
        head_raw = await redis.lindex("training:queue", 0)
        if not head_raw:
            break
        try:
            head_id = json.loads(head_raw).get("id", "")
        except Exception:
            head_id = ""
        if head_id in done_ids:
            await redis.lpop("training:queue")
            done_ids.discard(head_id)
        else:
            break

    if not pending:
        return

    batch = pending[:batch_size]
    log.info(f"Training queue: {len(pending)} bekliyor — {len(batch)} paralel analiz ediliyor")

    results = await asyncio.gather(
        *[_analyze_item(redis, raw) for _, raw in batch],
        return_exceptions=True,
    )

    # Save results sequentially (lock prevents race condition on training:docs)
    to_remove: list[str] = []
    for (item_id, raw), result in zip(batch, results):
        if isinstance(result, Exception):
            log.error(f"Training batch exception: {result}")
            continue
        item, rid, analysed = result
        if analysed == "__already_done__" or analysed == "__error__":
            to_remove.append(raw)
        elif analysed is None:
            pass  # rate-limited, leave in queue
        else:
            await _save_doc(redis, item, rid, analysed)
            to_remove.append(raw)

    for raw in to_remove:
        await redis.lrem("training:queue", 1, raw)


async def _refresh_learned_patterns(redis: aioredis.Redis):
    """
    Trade geçmişinden (regime × yön) → kazanma oranı istatistikleri çıkar.
    Minimum 5 trade olmayan kombinasyonlar göz ardı edilir.
    Bu veriler LLM olmadan da sinyallere etki eder.
    """
    global _learned_patterns
    try:
        raws = await redis.lrange("training:lessons", 0, 299)
        counts: dict[str, dict] = {}
        for r in raws:
            try:
                lesson = json.loads(r)
            except Exception:
                continue
            outcome = lesson.get("outcome")
            regime  = lesson.get("regime", "unknown")
            side    = lesson.get("side", "")
            if outcome not in ("WIN", "LOSS") or not side:
                continue
            key = f"{regime}:{side}"
            c = counts.setdefault(key, {"wins": 0, "losses": 0})
            if outcome == "WIN":
                c["wins"] += 1
            else:
                c["losses"] += 1

        patterns: dict = {}
        for key, c in counts.items():
            total = c["wins"] + c["losses"]
            if total >= 5:
                patterns[key] = c["wins"] / total
                patterns[f"{key}:n"] = total

        ctx_raw = await redis.get("context:latest:BTCUSDT")
        if ctx_raw:
            ctx = json.loads(ctx_raw)
            patterns["current_regime"] = ctx.get("regime", "unknown")

        _learned_patterns = patterns
        if patterns:
            log.info(f"Learned patterns updated: {len([k for k in patterns if ':n' not in k and k != 'current_regime'])} combos")
    except Exception as e:
        log.debug(f"Learned patterns refresh error: {e}")


async def llm_stats_push_loop(redis: aioredis.Redis):
    """Push in-memory LLM provider stats to Redis every 30s for the dashboard."""
    from llm_client import get_provider_stats
    while True:
        try:
            stats = get_provider_stats()
            await redis.set("llm:provider_stats", json.dumps(stats), ex=300)
        except Exception as e:
            log.debug(f"LLM stats push: {e}")
        await asyncio.sleep(30)


async def training_reload_loop(redis: aioredis.Redis):
    """Process PDF queue in parallel batches + reload training context every 15 seconds."""
    global _training_context
    while True:
        # Process up to 4 PDFs in parallel
        try:
            await _process_training_queue_batch(redis, batch_size=4)
        except Exception as e:
            log.warning(f"Queue processor error: {e}")

        # Reload active training context into memory
        try:
            new_ctx = await reload_training_context(redis)
            if new_ctx != _training_context:
                doc_count = len([d for d in new_ctx.split("[") if d]) if new_ctx else 0
                log.info(f"Training context reloaded — {doc_count} döküman aktif")
                _training_context = new_ctx
        except Exception as e:
            log.warning(f"Training reload error: {e}")

        await asyncio.sleep(15)


async def weight_update_loop(redis: aioredis.Redis):
    """Reload learned weights + apply regime multipliers every 5 minutes."""
    global _current_regime
    while True:
        try:
            # Accuracy-based weights written by autopsy/feedback_writer
            # (separate from agents:weights to avoid collision)
            learned_raw = await redis.get("agents:learned_weights")
            learned = json.loads(learned_raw) if learned_raw else None

            # Current global regime (from context_engine via BTC context)
            ctx_raw = await redis.get("context:latest:BTCUSDT")
            if ctx_raw:
                ctx = json.loads(ctx_raw)
                regime = ctx.get("regime", "unknown")
                if regime != _current_regime:
                    log.info(f"RegimeRouter: regime changed {_current_regime} → {regime}")
                    old = _current_regime
                    _current_regime = regime
                    # Faz 2: rejim değişim olayını yayınla → event_learner dinler
                    try:
                        await redis.publish("ch:regime_changed", json.dumps({
                            "old_regime": old,
                            "new_regime": regime,
                            "ts": time.time(),
                        }))
                    except Exception:
                        pass

            # Combine learned weights + regime multipliers
            new_weights = get_weights_for_regime(_current_regime, learned)
            debate.weights.update(new_weights)

            # Persist blended weights to Redis for dashboard display
            await redis.set("agents:weights", json.dumps(new_weights), ex=600)
        except Exception as e:
            log.warning(f"Weight update error: {e}")

        # Refresh local learned patterns (regime × direction win rates)
        await _refresh_learned_patterns(redis)

        await asyncio.sleep(300)


async def main():
    log.info("agent_system starting — 9-agent debate team — dynamic symbols")
    redis = await aioredis.from_url(REDIS_URL)

    active_set: set[str] = set()
    last_refresh = 0.0
    # Limit concurrent debates to avoid overwhelming Groq/Ollama rate limits
    _sem = asyncio.Semaphore(20)

    async def _debate_one(symbol: str):
        async with _sem:
            try:
                await run_debate_for_symbol(redis, symbol)
            except Exception as e:
                log.error(f"Debate error for {symbol}: {e}")

    async def debate_loop():
        nonlocal active_set, last_refresh
        while True:
            now = time.time()
            if now - last_refresh > SYMBOL_REFRESH_INTERVAL or not active_set:
                syms = await discover_symbols(redis)
                if syms:
                    active_set = set(syms)
                    log.info(f"agent_system: {len(active_set)} symbols discovered")
                last_refresh = now

            await asyncio.gather(*[_debate_one(s) for s in list(active_set)])
            await redis.set("agents:last_run", str(time.time()))
            log.info(f"agent_system: {len(active_set)} symbols — rotating batches of 120")
            await asyncio.sleep(10)

    await asyncio.gather(
        debate_loop(),
        weight_update_loop(redis),
        training_reload_loop(redis),
        news_scanner.run(redis),
        lesson_writer_loop(REDIS_URL),
        event_learner_loop(redis, REDIS_URL),
        strategy_extractor_loop(redis),
        system_observer_loop(redis, REDIS_URL),
        llm_stats_push_loop(redis),
    )


if __name__ == "__main__":
    asyncio.run(main())
