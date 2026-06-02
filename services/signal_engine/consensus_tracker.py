"""
Market Consensus Tracker — piyasanın genel yönünü hesaplar.

Her 30s'de tüm signal:latest:* anahtarlarını okur ve şu metrikleri üretir:
  market_bull_pct      : bullish sinyal yüzdesi (0-1)
  market_bear_pct      : bearish sinyal yüzdesi (0-1)
  market_flat_pct      : flat sinyal yüzdesi (0-1)
  market_consensus     : -1 (tam ayı) → +1 (tam boğa)
  market_long_conf     : long sinyallerin ortalama güveni
  market_short_conf    : short sinyallerin ortalama güveni
  market_active_count  : geçerli (non-flat) sinyal sayısı
  btc_trend            : BTC'nin anlık trendi (-1/0/+1)

Sonuç market:consensus Redis anahtarına yazılır (TTL 90s).
Feature engine bu veriyi her sembolün feature setine enjekte eder.
"""
import asyncio
import json
import logging
import time

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

CONSENSUS_INTERVAL = 30
CONSENSUS_KEY      = "market:consensus"
CONSENSUS_TTL      = 90


async def consensus_loop(redis: aioredis.Redis) -> None:
    """Tüm signal:latest:* anahtarlarını tarayıp market:consensus'u günceller."""
    await asyncio.sleep(20)  # Signal engine'in ilk sinyallerini üretmesini bekle

    while True:
        try:
            sig_keys = await redis.keys("signal:latest:*")
            if not sig_keys:
                await asyncio.sleep(CONSENSUS_INTERVAL)
                continue

            pipe = redis.pipeline()
            for k in sig_keys:
                pipe.get(k)
            raws = await pipe.execute()

            long_confs:  list[float] = []
            short_confs: list[float] = []
            flat_count = 0
            total = 0

            for raw in raws:
                if not raw:
                    continue
                try:
                    sig = json.loads(raw)
                except Exception:
                    continue

                if not sig.get("is_valid", False):
                    continue

                total += 1
                direction  = sig.get("direction", "flat")
                confidence = float(sig.get("confidence", 0))

                if direction == "long":
                    long_confs.append(confidence)
                elif direction == "short":
                    short_confs.append(confidence)
                else:
                    flat_count += 1

            if total == 0:
                await asyncio.sleep(CONSENSUS_INTERVAL)
                continue

            long_count  = len(long_confs)
            short_count = len(short_confs)

            bull_pct = long_count  / total
            bear_pct = short_count / total
            flat_pct = flat_count  / total

            long_conf_avg  = sum(long_confs)  / max(long_count,  1)
            short_conf_avg = sum(short_confs) / max(short_count, 1)

            # Consensus: boğa-ayı farkı × ortalama güven ağırlığı → -1..+1
            conf_weight = (long_conf_avg + short_conf_avg) / 2 + 0.5
            consensus   = max(-1.0, min(1.0, (bull_pct - bear_pct) * conf_weight))

            # BTC trendini ayrıca al (piyasa barometresi)
            btc_raw   = await redis.get("signal:latest:BTCUSDT")
            btc_trend = 0
            if btc_raw:
                try:
                    btc_sig = json.loads(btc_raw)
                    if btc_sig.get("direction") == "long":
                        btc_trend = 1
                    elif btc_sig.get("direction") == "short":
                        btc_trend = -1
                except Exception:
                    pass

            # ETH trendini de ekle (ikinci büyük market göstergesi)
            eth_raw   = await redis.get("signal:latest:ETHUSDT")
            eth_trend = 0
            if eth_raw:
                try:
                    eth_sig = json.loads(eth_raw)
                    if eth_sig.get("direction") == "long":
                        eth_trend = 1
                    elif eth_sig.get("direction") == "short":
                        eth_trend = -1
                except Exception:
                    pass

            # Major coin alignment: BTC + ETH aynı yönde mi?
            major_align = 1 if btc_trend == 1 and eth_trend == 1 else \
                         -1 if btc_trend == -1 and eth_trend == -1 else 0

            consensus_data = {
                "ts":                   time.time(),
                "total_signals":        total,
                "market_bull_pct":      round(bull_pct,        4),
                "market_bear_pct":      round(bear_pct,        4),
                "market_flat_pct":      round(flat_pct,        4),
                "market_consensus":     round(consensus,       4),
                "market_long_conf":     round(long_conf_avg,   4),
                "market_short_conf":    round(short_conf_avg,  4),
                "market_active_count":  long_count + short_count,
                "btc_trend":            btc_trend,
                "eth_trend":            eth_trend,
                "major_align":          major_align,
            }

            await redis.set(CONSENSUS_KEY, json.dumps(consensus_data), ex=CONSENSUS_TTL)

            mood = (
                "GÜÇLÜ BOĞA" if consensus > 0.5 else
                "BOĞA"       if consensus > 0.2 else
                "GÜÇLÜ AYI"  if consensus < -0.5 else
                "AYI"        if consensus < -0.2 else
                "NÖTR"
            )
            log.info(
                f"Market consensus: {mood} ({consensus:+.2f}) | "
                f"bull=%{bull_pct*100:.0f} bear=%{bear_pct*100:.0f} | "
                f"BTC={btc_trend:+d} ETH={eth_trend:+d} | "
                f"{total} sinyal"
            )

        except Exception as e:
            log.error(f"Consensus tracker hatası: {e}")

        await asyncio.sleep(CONSENSUS_INTERVAL)
