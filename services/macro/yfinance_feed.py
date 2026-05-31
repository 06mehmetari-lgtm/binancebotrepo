import asyncio
import json
import logging
import os
import time
import urllib.request
import urllib.error
import csv
import io
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
TICKERS = {"^VIX": "vix", "DX-Y.NYB": "dxy", "SPY": "spy", "GLD": "gld", "TLT": "tlt"}


def _fetch_vix_cboe() -> float | None:
    """Fetch latest VIX from CBOE public CSV — no API key needed."""
    try:
        url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        last = None
        for row in reader:
            last = row
        if last and "CLOSE" in last:
            return float(last["CLOSE"])
    except Exception as e:
        log.debug(f"CBOE VIX fallback failed: {e}")
    return None


def _fetch_yfinance(ticker_sym: str) -> tuple[float, float] | None:
    """Returns (close, prev_close) or None on failure."""
    try:
        import yfinance as yf
        data = yf.download(ticker_sym, period="2d", interval="5m", progress=False, auto_adjust=True)
        if data.empty:
            return None
        close_col = data["Close"]
        close = float(close_col.iloc[-1])
        prev_close = float(close_col.iloc[-2]) if len(close_col) > 1 else close
        return close, prev_close
    except Exception as e:
        log.debug(f"yfinance {ticker_sym} failed: {e}")
        return None


class YFinanceFeed:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._redis = await aioredis.from_url(REDIS_URL)
        while True:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._fetch)
            except Exception as e:
                log.error(f"macro feed error: {e}")
            await asyncio.sleep(300)

    def _write(self, loop: asyncio.AbstractEventLoop, key: str, payload: dict, ex: int = 600):
        loop.run_until_complete(self._redis.set(key, json.dumps(payload), ex=ex))

    def _fetch(self):
        import asyncio as _aio
        loop = _aio.new_event_loop()
        try:
            for ticker_sym, key in TICKERS.items():
                result = _fetch_yfinance(ticker_sym)

                if result is None and key == "vix":
                    # CBOE fallback for VIX (daily close only, no change_pct)
                    vix_val = _fetch_vix_cboe()
                    if vix_val is not None:
                        payload = {"value": vix_val, "change_pct": 0.0, "time": time.time(), "source": "cboe"}
                        self._write(loop, "macro:vix", payload)
                        self._write(loop, "macro:vix", payload)
                        log.info(f"Macro vix={vix_val:.2f} (CBOE fallback)")
                    continue

                if result is None:
                    log.warning(f"Macro {key}: no data from yfinance, skipping")
                    continue

                close, prev_close = result
                change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0
                payload = {"value": close, "change_pct": change_pct, "time": time.time(), "source": "yfinance"}
                self._write(loop, f"macro:{key}", payload)
                if key == "vix":
                    self._write(loop, "macro:vix", payload)
                elif key == "dxy":
                    self._write(loop, "macro:dxy", payload)
                log.info(f"Macro {key}={close:.2f} ({change_pct:+.2f}%)")
        finally:
            loop.close()
