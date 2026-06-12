# Prometheus Trading System — Gerçekçi Durum Raporu

Bu belge, repodaki sistemin **ne yaptığını**, **ne yapmadığını** ve dashboard’da **nasıl izleyeceğinizi** özetler.

---

## Önemli gerçek

**Sürekli kazanan, garanti kârlı bir AI trading botu teknik olarak mümkün değildir.** Piyasa rastgelelik, haber, likidite ve manipülasyon içerir. Prometheus’un hedefi:

- Disiplinli algoritmik trade
- Risk limitleri (immunity)
- Paper/shadow ile öğrenme ve promosyon kapısı
- Çoklu sinyal kaynağı (teknik + 9 LLM ajan + NEAT + PPO)
- Şeffaf log ve dashboard

---

## Mimari (kısa)

```
Binance WS → data_ingestion → feature_engine → context_engine
                                    ↓
              learning_engine ← agent_system (9 ajan + guard)
                                    ↓
              signal_engine ← rl_agent + neat_evolution
                                    ↓
              shadow_system (paper) + oms (paper Redis)
                                    ↓
              ch:trade_closed → learning, autopsy, dashboard SSE
```

**Not:** Kafka yok; Redis pub/sub + key polling kullanılıyor.

---

## Servis olgunluğu

| Servis | Durum | Açıklama |
|--------|-------|----------|
| data_ingestion | ✅ Çalışıyor | WS ticker, kline, order book |
| feature_engine | ✅ Çalışıyor | RSI, MACD, drift, TimescaleDB |
| context_engine | ✅ Çalışıyor | Rejim + kriz tespiti |
| agent_system | ✅ Çalışıyor | 9 ajan debate; VPS’te Groq/Cerebras IP engeli olabilir |
| signal_engine | ✅ Çalışıyor | Ensemble fuse, min confidence |
| shadow_system | ✅ Çalışıyor | Paper trade, promotion metrikleri |
| oms | ✅ Paper + Live | Paper varsayılan; promosyon + `LIVE_TRADING_CONFIRMED=true` + `DRY_RUN=false` ile **BinanceExecutor** |
| learning_engine | ✅ Çalışıyor | `learn:profile:*`, trade lessons |
| rl_agent | ⚠️ Kısmi | PPO inference; model yoksa katkı düşük |
| neat_evolution | ⚠️ Kısmi | 3 saatte bir evrim; heuristic entegrasyon |
| dashboard | ✅ Çalışıyor | Next.js, SSE, Recharts equity |

---

## Dashboard — nereden ne görürsünüz?

| Sayfa | Ne gösterir | Canlı güncelleme |
|-------|-------------|------------------|
| `/` (Ana) | Equity grafiği, son işlemler, RSI heatmap, sinyaller | SSE + 5s poll |
| `/positions` | Açık pozisyonlar, unrealized P&L, equity, işlem geçmişi | SSE + 5s poll |
| `/signals` | Long/short/flat sinyaller, confidence | SSE + 60s poll |
| `/agents` | 9 ajan oyları, debate verdict | 10s poll |
| `/learning` | Öğrenme profilleri, promotion, Ollama/LLM durumu | 3s poll |
| `/shadow` | Shadow leaderboard + **equity zaman serisi** (A/B/C) | SSE + 10s poll |
| `/learning` → Canlı Akış | **NEAT fitness / win rate / PPO** grafikleri | SSE + 3s poll |
| `/agents` | Kelly paneli **canlı crisis + drift** | SSE + 10s poll |
| `/risk` | Immunity limitleri, kriz, drift | 5s poll |
| `/coin/[symbol]` | Fiyat grafiği, RSI/MACD, sinyal | 10s poll |
| `/system` | Servis heartbeat, sağlık skoru | 5s poll |

**Equity eğrisi:** Kapanan işlemler + dakikalık snapshot + **canlı unrealized** noktası birleştirilir. Yeşil nokta = işlem kapanışı; son nokta = şu anki portföy değeri.

---

## Öğrenme “çalışıyor mu?”

Evet, **kayıt ve profil oluşturma** çalışır:

- Her kapanışta: `[learn] trade_closed` logu
- Redis: `learn:profile:{SYMBOL}` (updates, learning_stage, avoid_hint)
- `signal_engine/learn_adjust.py` confidence’ı hafifçe ayarlar

**Ama:** Erken aşamada profiller çoğunlukla `L0` kalır — bu “henüz güçlü edge yok” demektir, sistem bozuk değil. LLM enrichment (`llm_enrich_count`) VPS’te Groq engeli varsa 0 kalabilir.

Kontrol:

```bash
bash scripts/check-learning-redis.sh
docker compose logs learning_engine --tail 30 | grep learn
```

---

## Bilinen sınırlamalar

1. **Canlı emir kapısı** — `DRY_RUN=false` + `LIVE_TRADING_CONFIRMED=true` + shadow promosyonu gerekir. Varsayılan paper.
2. **Groq/Cerebras Contabo VPS IP’sinde 403** — Gemini, Ollama veya home relay gerekir (`scripts/PC-KAPALI-SUNUCU-ONLY.md`).
3. **Churn kaybı** — Çok hızlı aç/kapa + fee ≈ -0.10% per trade; risk limitleri ve min confidence ile azaltılır.
4. **“Sürekli kazanma” beklentisi** — Win rate %50–55 ve Sharpe > 1.5 shadow promosyon hedefi; günlük dalgalanma normal.

---

## Sunucuda hızlı kontrol

```bash
cd ~/prometheus
docker compose ps
docker compose logs oms --tail 20
docker compose logs signal_engine --tail 20
curl -s http://localhost:3000/api/portfolio | head -c 500
```

Dashboard: `http://SUNUCU_IP:3000`

---

## Önerilen risk ayarları (başlangıç)

Dashboard `/risk` veya `/positions` → Risk Limits:

- `max_position_pct`: **0.05** (5%)
- `max_open_positions`: **3–10** (test için düşük tutun)
- `max_daily_loss_pct`: **0.02** (2%)
- `min_signal_confidence`: **0.65+**

`DRY_RUN=true` kalana kadar canlı para kullanmayın.

---

## Canlı trading (OMS)

```env
DRY_RUN=false
LIVE_TRADING_CONFIRMED=true   # manuel onay
BINANCE_TESTNET=true          # önce testnet
BINANCE_API_KEY=...
BINANCE_SECRET=...
```

Shadow promosyon kriterleri sağlanmadan canlı emir **bloklanır**.

## Son güncellemeler

- `/shadow`: SHADOW_A/B/C equity zaman serisi grafiği
- `/learning` → Canlı Akış: NEAT fitness, win rate trend, PPO eğitim logu
- `/agents`: Kelly crisis/drift canlı (`signal:latest`)
- OMS: `BinanceExecutor` promosyon sonrası market emir
- Ana sayfa + `/positions`: canlı equity + SSE

Bu repo zaten “hibrit” yapıdadır: **Python pipeline + Next.js dashboard**. Sıfırdan .NET bot yazmaya gerek yok; mevcut Prometheus’u izleyip ayarlayın.
