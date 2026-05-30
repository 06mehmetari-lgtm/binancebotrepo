import asyncio
import json
import logging
import os
import time
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
FRED_KEY = os.getenv("FRED_API_KEY", "")
SERIES = ["DFF", "T10Y2Y", "CPIAUCSL", "UNRATE", "M2SL"]


class FredFeed:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        while True:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._fetch)
            except Exception as e:
                log.error(f"FRED error: {e}")
            await asyncio.sleep(3600)

    def _fetch(self):
        if not FRED_KEY:
            log.warning("FRED_API_KEY not set — skipping")
            return
        try:
            from fredapi import Fred
            import asyncio as _aio
            fred = Fred(api_key=FRED_KEY)
            loop = _aio.new_event_loop()
            try:
                for series_id in SERIES:
                    series = fred.get_series(series_id).dropna()
                    if series.empty:
                        continue
                    value = float(series.iloc[-1])
                    payload = {"series": series_id, "value": value, "time": time.time()}
                    loop.run_until_complete(
                        self._redis.set(f"macro:fred:{series_id}", json.dumps(payload), ex=86400)
                    )
                    log.info(f"FRED {series_id}={value:.4f}")
            finally:
                loop.close()
        except ImportError:
            log.warning("fredapi not available")
        except Exception as e:
            log.error(f"FRED fetch error: {e}")
