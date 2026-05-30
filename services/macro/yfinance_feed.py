import asyncio
import json
import logging
import os
import time
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
TICKERS = {"^VIX": "vix", "DX-Y.NYB": "dxy", "SPY": "spy", "GLD": "gld", "TLT": "tlt"}


class YFinanceFeed:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        while True:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._fetch)
            except Exception as e:
                log.error(f"yfinance error: {e}")
            await asyncio.sleep(300)

    def _fetch(self):
        try:
            import yfinance as yf
            import asyncio as _aio

            loop = _aio.new_event_loop()
            try:
                for ticker_sym, key in TICKERS.items():
                    data = yf.download(ticker_sym, period="2d", interval="5m", progress=False)
                    if data.empty:
                        continue
                    row = data.iloc[-1]
                    prev_row = data.iloc[-2] if len(data) > 1 else row
                    close = float(row["Close"].iloc[0]) if hasattr(row["Close"], "iloc") else float(row["Close"])
                    prev_close = float(prev_row["Close"].iloc[0]) if hasattr(prev_row["Close"], "iloc") else float(prev_row["Close"])
                    change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0
                    payload = {"value": close, "change_pct": change_pct, "time": time.time()}
                    loop.run_until_complete(
                        self._redis.set(f"macro:{key}", json.dumps(payload), ex=600)
                    )
                    # VIX gets special key used by context engine
                    if key == "vix":
                        loop.run_until_complete(
                            self._redis.set("macro:vix", json.dumps(payload), ex=600)
                        )
                    elif key == "dxy":
                        loop.run_until_complete(
                            self._redis.set("macro:dxy", json.dumps(payload), ex=600)
                        )
                    log.info(f"Macro {key}={close:.2f} ({change_pct:+.2f}%)")
            finally:
                loop.close()
        except ImportError:
            log.warning("yfinance not available")
        except Exception as e:
            log.error(f"yfinance fetch error: {e}")
