"""Fetch historical kline data from Binance USDM Futures REST API (public, no auth needed)."""
import json
import logging
import time
import urllib.request
import urllib.error

log = logging.getLogger(__name__)
BINANCE_URL = "https://fapi.binance.com"


def fetch_klines(symbol: str, interval: str = "1h", days: int = 365) -> list:
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    all_klines: list = []
    cursor = start_ms

    while cursor < end_ms:
        url = (
            f"{BINANCE_URL}/fapi/v1/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={cursor}&limit=1500"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "prometheus-backtest/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                chunk = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            log.warning(f"[{symbol}] HTTP {e.code}: {e.reason}")
            break
        except Exception as e:
            log.warning(f"[{symbol}] Fetch error: {e}")
            break

        if not chunk:
            break

        all_klines.extend(chunk)
        cursor = int(chunk[-1][0]) + 1

        if len(chunk) < 1500:
            break

        time.sleep(0.15)  # ~6 req/s — well within Binance 1200 req/min limit

    log.info(f"[{symbol}] fetched {len(all_klines)} x {interval} bars")
    return all_klines


def fetch_top_symbols(n: int = 25) -> list[str]:
    """Return top-n USDM futures symbols by 24h quote volume."""
    try:
        url = f"{BINANCE_URL}/fapi/v1/ticker/24hr"
        req = urllib.request.Request(url, headers={"User-Agent": "prometheus-backtest/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            tickers = json.loads(resp.read())
        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        usdt.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
        symbols = [t["symbol"] for t in usdt[:n]]
        log.info(f"Top {n} symbols by volume: {symbols}")
        return symbols
    except Exception as e:
        log.warning(f"Symbol discovery failed: {e}, using defaults")
        return [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
            "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT",
            "LINKUSDT", "UNIUSDT", "LTCUSDT", "ATOMUSDT", "NEARUSDT",
            "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
            "SUIUSDT", "SEIUSDT", "TIAUSDT", "JUPUSDT", "WIFUSDT",
        ]
