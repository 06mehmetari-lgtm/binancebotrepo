import asyncio
import json
import logging
import os
import time

import redis.asyncio as aioredis

from immunity import ImmunitySystem
from circuit_breaker import CircuitBreaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
immunity = ImmunitySystem()
breaker = CircuitBreaker(max_failures=5, reset_timeout=300)

# Daily reset at UTC midnight
_last_reset_day = -1


async def order_approval_loop(redis: aioredis.Redis):
    """Listen for order requests on Redis list `immunity:requests`, respond with approval."""
    global _last_reset_day
    log.info("ImmunitySystem listening for order requests")
    while True:
        # Daily reset
        day = int(time.time() // 86400)
        if day != _last_reset_day:
            immunity.reset_daily()
            _last_reset_day = day
            log.info("Daily immunity limits reset")

        # Blocking pop from request queue (timeout 1s)
        item = await redis.blpop("immunity:requests", timeout=1)
        if not item:
            continue
        try:
            request = json.loads(item[1])
            portfolio_value = float(request.get("portfolio_value", 10000))
            daily_pnl = float(request.get("daily_pnl", 0))
            approved, reason = immunity.check_order(request, portfolio_value, daily_pnl)
            response = {"request_id": request.get("request_id"), "approved": approved, "reason": reason}
            response_key = f"immunity:response:{request.get('request_id', 'unknown')}"
            await redis.set(response_key, json.dumps(response), ex=30)
        except Exception as e:
            log.error(f"Order approval error: {e}")
            if not breaker.is_open:
                breaker.record_failure()


async def main():
    log.info("immunity_system starting — ABSOLUTE LIMITS ACTIVE")
    redis = await aioredis.from_url(REDIS_URL)
    await order_approval_loop(redis)


if __name__ == "__main__":
    asyncio.run(main())
