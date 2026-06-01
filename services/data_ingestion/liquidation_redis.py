"""
Liquidation stream → Redis.
Replaces the old Kafka-based liquidation.py.
Streams !forceOrder@arr and writes per-symbol liquidation data to Redis.
"""
import asyncio
import json
import logging
import time
import websockets
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

LIQ_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"


async def run(redis: aioredis.Redis):
    backoff = 1
    while True:
        try:
            log.info("Liquidation stream connecting...")
            async with websockets.connect(LIQ_URL, ping_interval=20, ping_timeout=10) as ws:
                backoff = 1
                log.info("Liquidation stream connected ✅")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        order = msg.get("o", msg)
                        symbol  = order.get("s", "").upper()
                        side    = order.get("S", "")   # BUY = short liq, SELL = long liq
                        qty     = float(order.get("q", 0))
                        price   = float(order.get("ap", order.get("p", 0)))
                        usd     = qty * price
                        ts      = time.time()

                        entry = json.dumps({"side": side, "usd": usd, "price": price, "t": ts})

                        # Per-symbol rolling list (last 200 liquidations)
                        key = f"liq:recent:{symbol}"
                        await redis.lpush(key, entry)
                        await redis.ltrim(key, 0, 199)
                        await redis.expire(key, 300)

                        # Global feed for dashboard
                        await redis.lpush("liq:global", entry)
                        await redis.ltrim("liq:global", 0, 499)
                        await redis.expire("liq:global", 3600)

                        if usd > 100_000:
                            log.info(f"Large liq: {symbol} {side} ${usd:,.0f} @ {price}")

                    except Exception as e:
                        log.warning(f"Liquidation parse error: {e}")

        except Exception as e:
            log.error(f"Liquidation stream error: {e} — retry in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
