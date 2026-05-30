import numpy as np

class CryptoFeatureBuilder:
    def build(self, crypto: dict) -> dict:
        features = {}
        funding = float(crypto.get("funding_rate", 0))
        features["funding_rate"] = float(np.clip(funding * 1000, -5, 5))
        features["funding_regime"] = 1.0 if funding > 0.001 else (-1.0 if funding < -0.001 else 0.0)
        oi_change = float(crypto.get("oi_change_pct", 0))
        features["oi_change_1h"] = float(np.clip(oi_change, -20, 20)) / 20
        ls_ratio = float(crypto.get("ls_ratio", 1))
        features["ls_ratio_z"] = float(np.clip(np.log(max(ls_ratio, 0.01)), -2, 2)) / 2
        liq_buy = float(crypto.get("liquidation_buy", 0))
        liq_sell = float(crypto.get("liquidation_sell", 0))
        total_liq = liq_buy + liq_sell
        features["liq_pressure"] = float((liq_sell - liq_buy) / total_liq) if total_liq > 0 else 0.0
        features["liq_intensity"] = float(min(total_liq / 1_000_000, 1))
        fg = float(crypto.get("fear_greed", 50))
        features["fear_greed_norm"] = fg / 100
        features["fear_greed_regime"] = -1.0 if fg > 80 else (1.0 if fg < 20 else 0.0)
        inflow = float(crypto.get("exchange_inflow", 0))
        outflow = float(crypto.get("exchange_outflow", 0))
        net_flow = outflow - inflow
        features["onchain_netflow"] = float(np.clip(net_flow / 1000, -1, 1))
        reddit = float(crypto.get("reddit_sentiment", 0))
        features["reddit_sentiment"] = float(np.clip(reddit, -1, 1))
        news = float(crypto.get("news_sentiment", 0))
        features["news_sentiment"] = float(np.clip(news, -1, 1))
        vix = float(crypto.get("vix_level", 20))
        features["vix_level"] = float(np.clip(vix / 100, 0, 1))
        features["dxy_change_1d"] = float(np.clip(crypto.get("dxy_change_1d", 0) / 5, -1, 1))
        features["btc_dominance"] = float(np.clip(crypto.get("btc_dominance", 0.5), 0, 1))
        return features
