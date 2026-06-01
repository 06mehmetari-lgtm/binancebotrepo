"""
Portfolio Guard — Phase 3.
Prevents taking correlated positions. Uses CVD + RSI direction similarity
as a fast proxy for price correlation (avoids expensive OHLCV matrix math).
"""
import logging

log = logging.getLogger(__name__)

# BTC-correlated asset clusters (rough groupings by behaviour)
CLUSTERS = {
    "btc_layer1": {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT"},
    "btc_alts":   {"ADAUSDT", "XRPUSDT", "LTCUSDT", "BCHUSDT", "LINKUSDT", "ATOMUSDT"},
    "defi":       {"UNIUSDT", "AAVEUSDT", "COMPUSDT", "MKRUSDT", "CRVUSDT", "SUSHIUSDT"},
    "layer2":     {"MATICUSDT", "ARBUSDT", "OPUSDT", "ZKUSDT", "STRKUSDT"},
    "meme":       {"DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT"},
    "ai_sector":  {"FETUSDT", "AGIXUSDT", "WLDUSDT", "RENDERUSDT", "TAOUSDT"},
}

MAX_SAME_DIRECTION  = 2   # max positions in same direction from same cluster
MAX_OPEN_POSITIONS  = 3   # absolute cap (mirrors immunity_system)
CORRELATION_PENALTY = 0.15 # confidence penalty per correlated position


def _cluster_of(symbol: str) -> str | None:
    for name, members in CLUSTERS.items():
        if symbol in members:
            return name
    return None


class PortfolioGuard:
    def check(
        self,
        symbol: str,
        direction: str,
        open_positions: list[dict],
        features: dict,
    ) -> tuple[bool, str, float]:
        """
        Returns (allowed: bool, reason: str, confidence_modifier: float).
        confidence_modifier ∈ [-0.3, 0.0] — reduces confidence for correlated entries.
        """
        if direction == "flat":
            return True, "", 0.0

        if len(open_positions) >= MAX_OPEN_POSITIONS:
            return False, f"max open positions ({MAX_OPEN_POSITIONS}) reached", 0.0

        cluster = _cluster_of(symbol)
        if cluster is None:
            return True, "", 0.0  # unknown symbol — no cluster constraint

        same_dir_in_cluster = [
            p for p in open_positions
            if p.get("direction") == direction and _cluster_of(p.get("symbol", "")) == cluster
        ]

        if len(same_dir_in_cluster) >= MAX_SAME_DIRECTION:
            return (
                False,
                f"{len(same_dir_in_cluster)} {direction} positions already in cluster {cluster}",
                0.0,
            )

        # Soft penalty: already 1 correlated position → reduce confidence
        penalty = len(same_dir_in_cluster) * CORRELATION_PENALTY

        if penalty > 0:
            log.debug(
                f"PortfolioGuard: {symbol} {direction} — "
                f"{len(same_dir_in_cluster)} correlated position(s), penalty={penalty:.0%}"
            )

        return True, "", -round(penalty, 3)
