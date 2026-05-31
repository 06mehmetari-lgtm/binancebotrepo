"""
Auto-discovers active USDM perpetual futures from Binance.
Returns top N symbols by 24h quote volume.
"""
import json
import logging
import urllib.request

log = logging.getLogger(__name__)

EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
TICKER_24H_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"

# Stablecoins and low-quality pairs to skip
_SKIP_SUFFIXES = ("BUSD", "USDC", "TUSD", "USDP", "DAI")
_SKIP_SYMBOLS = {"BTCDOMUSDT", "DEFIUSDT", "BTCSTUSDT"}


def fetch_top_symbols(top_n: int = 100) -> list[str]:
    try:
        # Get all active perpetual contracts
        with urllib.request.urlopen(EXCHANGE_INFO_URL, timeout=10) as r:
            info = json.loads(r.read())
        active = {
            s["symbol"]
            for s in info["symbols"]
            if s["contractType"] == "PERPETUAL"
            and s["status"] == "TRADING"
            and s["symbol"].endswith("USDT")
            and not any(s["symbol"].startswith(skip) for skip in _SKIP_SUFFIXES)
            and s["symbol"] not in _SKIP_SYMBOLS
        }

        # Get 24h volume for ranking
        with urllib.request.urlopen(TICKER_24H_URL, timeout=10) as r:
            tickers = json.loads(r.read())

        volumes = {
            t["symbol"]: float(t["quoteVolume"])
            for t in tickers
            if t["symbol"] in active
        }

        ranked = sorted(volumes.items(), key=lambda x: x[1], reverse=True)
        top = [sym for sym, _ in ranked[:top_n]]
        log.info(f"Symbol discovery: {len(active)} active perpetuals, selected top {len(top)}")
        return top

    except Exception as e:
        log.warning(f"Symbol discovery failed: {e} — using fallback")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
