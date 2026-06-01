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

    result = await debate.run_debate(symbol, features, context, _training_context)

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


_current_regime: str = "unknown"
_training_context: str = ""


async def reload_training_context(redis: aioredis.Redis) -> str:
    """Load operator training docs + recent trade lessons from Redis."""
    sections = []

    try:
        raw = await redis.get("training:docs")
        if raw:
            docs = json.loads(raw)
            if docs:
                parts = [f"[{d.get('title','doc')}]\n{d.get('content','')}" for d in docs[:8]]
                sections.append("PDF TRAINING DOCUMENTS:\n" + "\n---\n".join(parts))
    except Exception:
        pass

    try:
        lesson_raws = await redis.lrange("training:lessons", 0, 9)
        if lesson_raws:
            lessons = []
            for lr in lesson_raws:
                try:
                    ld = json.loads(lr)
                    lessons.append(ld.get("lesson", ""))
                except Exception:
                    pass
            if lessons:
                sections.append(
                    "RECENT TRADE LESSONS (AI-generated from actual trades — avoid repeating these mistakes):\n"
                    + "\n\n".join(lessons)
                )
    except Exception:
        pass

    return "\n\n===\n\n".join(sections)


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


async def _process_training_queue(redis: aioredis.Redis):
    """Process one pending PDF from training:queue using Groq.
    Returns True if an item was processed (or failed), False if queue empty."""
    item_raw = await redis.lindex("training:queue", 0)  # peek oldest
    if not item_raw:
        return False

    item: dict = {}
    item_id = ""
    try:
        item = json.loads(item_raw)
        item_id = item.get("id", "")

        # Skip if already processed
        status_raw = await redis.get(f"training:queue:status:{item_id}")
        if status_raw:
            status = json.loads(status_raw)
            if status.get("status") == "done":
                await redis.lpop("training:queue")
                return True

        # Mark as processing
        await redis.set(
            f"training:queue:status:{item_id}",
            json.dumps({"status": "processing", "started_at": time.time()}),
            ex=3600,
        )

        analysed = await _groq_analyze_queued(item.get("raw_text", ""), item.get("filename", "doc"))

        # Add to training:docs
        docs_raw = await redis.get("training:docs")
        docs = json.loads(docs_raw) if docs_raw else []
        docs.insert(0, {
            "id": item_id,
            "title": item.get("title", item.get("filename", "PDF")),
            "content": analysed,
            "source": "pdf",
            "filename": item.get("filename", ""),
            "created_at": item.get("created_at", time.time()),
        })
        await redis.set("training:docs", json.dumps(docs))

        # Mark done and remove from queue
        await redis.set(
            f"training:queue:status:{item_id}",
            json.dumps({"status": "done", "processed_at": time.time()}),
            ex=86400 * 7,
        )
        await redis.lpop("training:queue")
        log.info(f"Training queue: '{item.get('title','')}' öğrenildi ({item.get('filename','')})")
        return True

    except ValueError as e:
        if "429" in str(e) or "rate_limit" in str(e):
            log.warning("Training queue: Groq rate limit — bir sonraki döngüde tekrar denenecek")
            if item_id:
                await redis.set(
                    f"training:queue:status:{item_id}",
                    json.dumps({"status": "pending", "error": "rate_limit", "retry_after": time.time() + 65}),
                    ex=86400,
                )
        else:
            log.error(f"Training queue error: {e}")
            if item_id:
                await redis.set(
                    f"training:queue:status:{item_id}",
                    json.dumps({"status": "error", "error": str(e)}),
                    ex=86400,
                )
            await redis.lpop("training:queue")  # skip broken item
        return False
    except Exception as e:
        log.error(f"Training queue unexpected error: {e}")
        return False


async def training_reload_loop(redis: aioredis.Redis):
    """Process PDF queue + reload training context every 60 seconds."""
    global _training_context
    while True:
        # Process one queued PDF (rate-limit safe: one per 60s cycle)
        try:
            await _process_training_queue(redis)
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

        await asyncio.sleep(60)


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
                    _current_regime = regime

            # Combine learned weights + regime multipliers
            new_weights = get_weights_for_regime(_current_regime, learned)
            debate.weights.update(new_weights)

            # Persist blended weights to Redis for dashboard display
            await redis.set("agents:weights", json.dumps(new_weights), ex=600)
        except Exception as e:
            log.warning(f"Weight update error: {e}")
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
    )


if __name__ == "__main__":
    asyncio.run(main())
