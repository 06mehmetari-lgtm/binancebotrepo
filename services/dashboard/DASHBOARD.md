# Prometheus Dashboard — Kapsamlı Kullanım ve Mimari Rehberi

Next.js 14 (App Router) tabanlı web arayüzü. Port **3000**. Tüm veri **Redis** üzerinden okunur; vektör hafıza için **Qdrant**, sohbet için **Ollama**, LLM durumu için **agent_system** → `system:llm:status`.

```
Binance WS → data_ingestion → feature_engine → context_engine
                                    ↓
              learning_engine ← agent_system → signal_engine
                                    ↓
              shadow_system / OMS / immunity_system
                                    ↓
                            Redis (+ Qdrant)
                                    ↓
                         Dashboard API (route.ts)
                                    ↓
                         Sayfalar (page.tsx)
```

---

## Genel kabuk (her sayfada)

**Dosya:** `src/app/layout.tsx`

| Bileşen | API | Yenileme | Açıklama |
|---------|-----|----------|----------|
| Üst ticker (fiyat + yön) | `GET /api/ticker` | 10 sn | En yüksek güvenli sinyaller, coin detayına link |
| Bildirim zili | `GET /api/notifications` | 10 sn | `activity:feed` son 20 olay |
| SmartAlerts (sağ alt) | SSE `ch:signal:*` + `/api/notifications` yedek | anlık | Güven ≥ %80 toast |
| AlertPanel (sol alt) | SSE + `POST /api/alerts` | anlık | Aksiyonlu uyarılar (kapat, detay, sinyal) |
| SSE stream | `GET /api/stream` | sürekli | Redis pub/sub → EventSource |

**Menü sırası (kod):**

| Menü | URL | Tür |
|------|-----|-----|
| Dashboard | `/` | Genel özet |
| 🖥 Sistem | `/system` | Pipeline sağlığı |
| 🤖 AI Analiz | `/analiz` | SQS fırsat listesi |
| 📈 AI Öğrenme | `/learning` | Öğrenme merkezi + emir |
| 💬 Chat | `/chat` | Ollama + RAG sohbet |
| 💼 Positions | `/positions` | Açık pozisyon + PnL |
| 🔬 Otopsi | `/autopsy` | Kapanan işlem otopsi |
| ⚖ Compare | `/compare` | Çoklu coin karşılaştırma |
| 🔍 Scanner | `/scanner` | Evren tarayıcı |
| Markets | `/markets` | Tüm coin feature tablosu |
| Signals | `/signals` | Aktif sinyal kartları |
| Agents | `/agents` | 9 ajan oyları |
| Evolution | `/evolution` | NEAT genom havuzu |
| Shadow | `/shadow` | Paper trading liderlik |
| Risk | `/risk` | Immunity + kriz |
| AI Memory | `/memory` | Aktivite + öğrenme + Qdrant |
| 📈 Backtest | `/backtest` | Tarihsel simülasyon |
| (gizli nav) | `/coin/[symbol]` | Tek coin derin analiz |

---

## Paylaşılan kütüphaneler

### `src/lib/positions.ts`

OMS + shadow pozisyonlarını birleştirir. Kullanan API: `/api/positions`, `/api/learning`, `/api/memory`, `/api/risk`.

**Okunan Redis anahtarları (sembol başına):**

- `portfolio:state:v1`, `oms:position:{SYMBOL}`, `shadow:positions:{SHADOW_ID}:{SYMBOL}`
- `binance:ticker:{symbol}`, `features:latest:{SYMBOL}`, `context:latest:{SYMBOL}`
- `signal:latest:{SYMBOL}`, `agents:verdict:{SYMBOL}`, `agents:verdicts:{SYMBOL}`
- `guard:position:{SYMBOL}` (saniye bazlı guard)

Aynı sembol+yön için tek satır (dedupe); unrealized PnL ticker mid veya feature close ile.

### `src/lib/sqs.ts` — Signal Quality Score (0–100)

**AI Analiz**, **Scanner**, **Risk** (üst SQS) sayfalarında kullanılır.

| Bileşen | Puan |
|---------|------|
| Sinyal güveni | 30 |
| Backtest Sharpe + WR | 35 |
| Shadow Sharpe + WR | 15 |
| Rejim (trending +5, volatile −5) | ±5 |
| Drift (WARNING/DRIFTING/SHOCK) | −5 / −15 / −30 |
| Order book `imbalance_5` | ±4–6 |
| Öğrenme L0/L2/L3 | stage bonus |

Derinlik etiketleri: Güçlü bid, Bid baskısı, Dengeli, Ask baskısı, Güçlü ask.

### `src/lib/learning-hub.ts`

- **Sekmeler:** `live`, `brain`, `lessons`, `stream`, `strategy`, `doc`, `llm`, `command`
- **Canlıya geçiş:** 100 işlem, Sharpe ≥ 1.5, WR ≥ 52%, max DD < 10%
- **CURRICULUM:** 6 sabit Türkçe ders
- **buildStrategyDocument():** evren/profil/promotion’dan otomatik markdown

### `src/lib/system-health.ts`

25 Docker konteyneri (`check.sh` ile uyumlu): postgres, timescale, redis, qdrant, ollama, data, features, context, learning, sentiment, macro, signal, agents, shadow, immunity, oms, neat, rl, autopsy, rag, scenarios, backtest, dashboard, prometheus, grafana.

### `src/lib/llm-providers.ts` + `llm-status-redis.ts`

LLM sekmesi: önce Redis `system:llm:status` (agent_system yazar), yoksa konteyner `process.env`. Groq `GROQ_API_KEY_1..N`, Cerebras `CEREBRAS_API_KEY_1..N`.

### `src/hooks/useStream.ts` + `src/lib/stream-events.ts`

`EventSource('/api/stream')` — Redis kanalları: `ch:signal:*`, `ch:agents:*`, `ch:learn:*`, `ch:features:*`, `ch:trade_closed`, `ch:position:guard`, `ch:portfolio:update`. `useStreamInvalidate` ile sayfa yenileme tetiklenir.

### `src/lib/alerts.ts` + `src/lib/api-handler.ts` + `src/lib/stale.ts`

Alert öncelik skoru, `POST /api/learning/command` aksiyonları, API route cache (5s), heartbeat STALE rozeti (`HEARTBEAT_STALE_SEC=120`).

---

## Sayfa sayfa detay

---

### 1. Dashboard — `/`

**Amaç:** Tek bakışta sistem nabzı — WebSocket, sinyal dağılımı, backtest liderleri, canlı fırsatlar, RSI ısı haritası, shadow sıralaması.

| | |
|---|---|
| **Yenileme** | 5 sn |
| **API** | `/api/markets`, `/api/signals`, `/api/shadow`, `/api/status`, `/api/backtest` |

**UI blokları:**

1. **Stat kartları** — WS durumu, aktif sembol, long/short sayısı, açık pozisyon, Fear & Greed, VIX, en iyi NEAT fitness
2. **Top Performers** — backtest Sharpe × WR; canlı sinyalle zenginleştirilmiş
3. **Live Opportunities** — en yüksek güvenli 10 sinyal
4. **RSI Heatmap** — ilk 40 market (aşırı alım/satım renkleri)
5. **Shadow Leaderboard** — paper strateji karşılaştırması

**Arka plan servisleri:** `data_ingestion`, `feature_engine`, `signal_engine`, `shadow_system`, `backtest`, `neat_evolution`, `sentiment`, `macro`

---

### 2. 🖥 Sistem — `/system`

**Amaç:** Türkçe operasyon paneli — pipeline skoru 0–100, hangi servis ayakta, kaç sembol/feature/sinyal/öğrenme profili var.

| | |
|---|---|
| **Yenileme** | 5 sn |
| **API** | `GET /api/system` |

**UI:**

- Sistem skoru ve özet metrikler
- `trading_halted` uyarısı
- Servis listesi: `data_ingestion` (ws), `feature_engine`, `learning_engine`, `agent_system`, `signal_engine` — heartbeat yaşı
- Sorunlu servisler vurgusu

**Redis:** `features:latest:*`, `signal:latest:*`, `agents:verdict:*`, `learn:profile:*`, `system:heartbeat:*`, `ws:status`, `immunity:status`, `system:promotion:status`, `system:trading:halted`, `activity:feed`, `shadow:leaderboard`, `portfolio:state:v1`

---

### 3. 🤖 AI Analiz — `/analiz`

**Amaç:** Tüm evrende **SQS** ile sıralanmış en iyi long/short fırsatları — order book imbalance, öğrenme seviyesi, backtest, AI verdict bir arada.

| | |
|---|---|
| **Yenileme** | 4 sn |
| **API** | `GET /api/analiz?limit=80&min_sqs=40..85` |

**UI:**

- Min SQS kaydırıcısı
- En yüksek SQS tablosu (top 30)
- LONG fırsatları | SHORT fırsatları (yan yana)

**Kolonlar:** SQS, sembol, yön, güven, RSI, imbalance etiketi, öğrenme stage, backtest Sharpe/WR, verdict özeti

**Arka plan:** `feature_engine`, `context_engine`, `signal_engine`, `agent_system`, `learning_engine`, `backtest`, `shadow_system`

---

### 4. 📈 AI Öğrenme — `/learning`

**Amaç:** Prometheus’un “beyin merkezi” — shadow’dan canlıya geçiş, Ollama, dersler, pipeline akışı, strateji belgesi, LLM anahtar durumu, **manuel emir merkezi**.

| | |
|---|---|
| **Yenileme** | 3 sn |
| **API** | `GET /api/learning?symbol=BTCUSDT`, `POST /api/learning/command` |

#### Sekmeler

| Sekme | İçerik |
|-------|--------|
| **live** | Canlıya geçiş adımları, shadow leaderboard, kriterler, açık pozisyonlar |
| **brain** | Ollama model listesi (`/api/tags`) |
| **lessons** | Sabit müfredat + `trade:lessons:*` + Qdrant nokta sayısı |
| **stream** | Heartbeat’ler + `activity:feed` canlı akış |
| **strategy** | Odak sembol sinyal/verdict JSON + L0–L3 profil tablosu |
| **doc** | Otomatik strateji belgesi (kopyala) |
| **llm** | Groq/Cerebras/… sağlayıcı kartları, model havuzları, swarm ayarları |
| **command** | LONG / SHORT / FLAT / kapat / debate yenile / öğrenme tetikle |

#### Emir merkezi (`POST /api/learning/command`)

| Aksiyon | Etki |
|---------|------|
| `force_signal` | `signal:latest:{SYMBOL}` yazar (paper sinyal) |
| `close_symbol` | `ch:position:guard` — pozisyon kapat |
| `refresh_debate` | `ch:learn:{SYMBOL}` — debate yenile |
| `refresh_learning` | `ch:features:{SYMBOL}` — öğrenme taraması |
| `close_all` | `system:trading:halted` + acil kapat |
| `resume_trading` | halt kaldır + `ch:trading:restart` |

**Dış servisler:** Ollama (`OLLAMA_URL`), Qdrant (`trade_memories`), Groq (env + Redis `system:llm:status`)

**Arka plan:** `learning_engine`, `agent_system`, `signal_engine`, `shadow_system`, `immunity_system`, `oms`, `position_guard`, `rag_memory`

---

### 5. 💬 Chat — `/chat`

**Amaç:** Türkçe soru-cevap — seçili coin için öğrenme profili, sinyal, verdict, geçmiş dersler; isteğe bağlı Ollama üretimi + Qdrant RAG.

| | |
|---|---|
| **Yenileme** | Sadece mesaj gönderiminde |
| **API** | `POST /api/chat` `{ message, symbol, use_llm }` |

**Akış:**

1. Redis’ten profil + sinyal + verdict + dersler okunur
2. Kural tabanlı kısa cevap veya Ollama `POST /api/generate`
3. İsteğe bağlı Qdrant benzer trade araması
4. `chat:history:v1` güncellenir

**Arka plan:** `learning_engine`, `agent_system`, `signal_engine`, `rag_memory`, Ollama

---

### 6. 💼 Positions — `/positions`

**Amaç:** Paper portföy yönetimi — açık pozisyonlar, equity eğrisi, işlem geçmişi, acil durum.

| | |
|---|---|
| **Yenileme** | 2 sn |
| **API** | `/api/positions`, `/api/portfolio`, `POST /api/emergency` |

**UI:**

- Acil: tümünü kapat, işleme devam, trading restart
- Özet: açık sayı, unrealized PnL, günlük PnL, win rate
- Recharts equity curve
- Sermaye kullanım çubuğu
- Pozisyon tablosu + genişletilebilir **karar paneli** (9 ajan oyları, guard, verdict)
- Son kapanan işlemler (`oms:trade_history`)

**Redis:** `portfolio:state:v1`, `oms:*`, `shadow:positions:*`, `system:trading:halted`, `oms:daily_pnl`, `portfolio:pnl:snapshots`

**Arka plan:** `oms`, `shadow_system`, `immunity_system`, `position_guard`, `agent_system`

---

### 7. 🔍 Scanner — `/scanner`

**Amaç:** 7/24 evren taraması — her coin için SQS, teknik göstergeler, rejim, drift; sağda canlı aktivite.

| | |
|---|---|
| **Yenileme** | 5 sn |
| **API** | `/api/scanner`, `/api/activity` |

**UI:**

- WS canlı rozeti, long/short/flat istatistik
- Arama + yön filtresi
- Sayfalanmış tablo: SQS, yön, güven çubuğu, RSI, MACD, BB, ATR, hacim, drift, rejim, backtest
- Sağ kolon: `activity:feed`

**Arka plan:** `data_ingestion`, `feature_engine`, `signal_engine`, `backtest`, `shadow_system`

---

### 8. Markets — `/markets`

**Amaç:** Tüm sembollerin feature tablosu — sıralama, filtre, opsiyonel funding/OI/L-S ratio.

| | |
|---|---|
| **Yenileme** | 10 sn |
| **API** | `GET /api/markets` |

**Sıralama:** confidence, RSI, volume_ratio, ADX, funding. Sayfalama mevcut.

**Redis:** `features:latest:*` + `signal:latest:*` birleşimi

---

### 9. Signals — `/signals`

**Amaç:** Aktif sinyal kartları — güven eşiği (%60), Kelly, kriz, drift, consensus gerekçe.

| | |
|---|---|
| **Yenileme** | 5 sn |
| **API** | `GET /api/signals` |

**UI:** İstatistik satırı, flat göster/gizle, sayfalanmış kartlar

**Redis:** `signal:latest:*`, `features:latest:*`, `snapshot:universe:v1`

---

### 10. Agents — `/agents`

**Amaç:** Sembol seçerek **9 ajan** oyları, debate verdict, Kelly dağılımı, NEAT genom, öğrenme profili.

| | |
|---|---|
| **Yenileme** | 10 sn (seçili sembol) |
| **API** | `/api/agents`, `/api/symbols`, `/api/portfolio/state`, `/api/signals` |

**Ajanlar (kural + isteğe bağlı LLM):** technical, onchain, sentiment, macro, news, bull, bear, neutral, risk → **DebateAgent** sentez

**Redis:** `agents:verdicts:{SYMBOL}`, `agents:verdict:{SYMBOL}`, `neat:best_genome:{SYMBOL}`, `learn:profile:{SYMBOL}`

**Arka plan:** `agent_system`, `neat_evolution`, `learning_engine`, `signal_engine`

---

### 11. Evolution — `/evolution`

**Amaç:** NEAT evrim havuzu — fitness, nesil, durum; shadow promotion kartları yan yana.

| | |
|---|---|
| **Yenileme** | 10 sn |
| **API** | `/api/evolution`, `/api/status` |

**Redis:** `neat:best_genome:*`, `shadow:leaderboard`

**Arka plan:** `neat_evolution`, `shadow_system`

---

### 12. Shadow — `/shadow`

**Amaç:** Paper trading stratejileri (SHADOW_A/B/C…) — Sharpe, WR, işlem sayısı, drawdown; canlıya geçiş kriter çubukları.

| | |
|---|---|
| **Yenileme** | 10 sn |
| **API** | `GET /api/shadow` |

**Kriterler (sabit):** 100+ işlem, Sharpe ≥ 1.5, WR ≥ 52%, max DD < 10%

**Redis:** `shadow:leaderboard` (JSON dizi)

**Arka plan:** `shadow_system`, `promotion_engine`

---

### 13. Risk — `/risk`

**Amaç:** **Immunity System** — günlük kayıp, açık pozisyon limiti, kriz seviyesi, drift özeti, funding uyarıları, likidasyonlar, hard limit referansı.

| | |
|---|---|
| **Yenileme** | 5 sn |
| **API** | `/api/risk`, `/api/positions`, `/api/sqs`, `POST /api/emergency` |

**Sabit limitler (kodda, değiştirilemez):**

| Limit | Değer |
|-------|-------|
| Max kaldıraç | 3× |
| Max pozisyon | portföyün %5’i |
| Max günlük kayıp | %2 |
| Max açık pozisyon | 3 |
| Min sinyal güveni (sinyal motoru) | %60 |

**Redis:** `immunity:status`, `macro:vix`, `alerts:funding`, `liquidations:large`, `features` (drift), `context` (crisis)

---

### 14. AI Memory — `/memory`

**Amaç:** “Sistem İzleme” — canlı aktivite, öğrenme profilleri, 8 adımlı pipeline diyagramı, Qdrant trade hafızası, istatistikler.

| | |
|---|---|
| **Yenileme** | 5 sn |
| **API** | `GET /api/memory` |

#### Sekmeler

| Sekme | İçerik |
|-------|--------|
| **live** | Açık pozisyonlar + AI gerekçe, activity feed, sinyal/rejim dağılımı |
| **learning** | Global öğrenme özeti, son dersler, coin profilleri (L0–L3), backtest log |
| **pipeline** | Karar zinciri: veri → feature → context → ajan → sinyal → immunity → OMS/shadow |
| **memories** | Qdrant `trade_memories` kartları |
| **stats** | WR, hata kategorileri, kazanan rejimler |

**Dış:** Qdrant scroll API

**Arka plan:** `signal_engine`, `learning_engine`, `autopsy`, `rag_memory`, `data_ingestion`

---

### 15. 📈 Backtest — `/backtest`

**Amaç:** Tarihsel simülasyon kontrolü — tetikle, ilerleme, canlı log, sembol bazlı sonuçlar, aylık heatmap.

| | |
|---|---|
| **Yenileme** | 5 sn |
| **API** | `GET /api/backtest`, `POST /api/backtest` (tetik) |

**POST:** `backtest:trigger = 1` (300 sn TTL) → `backtest` servisi yaklaşık 60 sn’de bir kontrol eder

**Redis:** `backtest:results`, `backtest:status`, `backtest:log`, `backtest:symbol:{SYMBOL}`, `backtest:queue:state`

**Arka plan:** `backtest` container, `learning_engine` (sonuç tüketimi)

---

### 16. Trade Otopsi — `/autopsy`

| | |
|---|---|
| **Yenileme** | 15 sn |
| **API** | `GET /api/autopsy` |

**Veri:** `oms:trade_history`, `trade:lessons:{SYMBOL}`, `activity:feed` (type `autopsy`).

---

### 17. Coin karşılaştırma — `/compare`

| | |
|---|---|
| **Yenileme** | istek bazlı |
| **API** | Paralel `GET /api/coin/{SYMBOL}` (max 4) |

**URL:** `/compare?symbols=BTCUSDT,ETHUSDT,SOLUSDT` — SQS `computeSQS()` ile.

---

### 18. Coin detay — `/coin/[symbol]`

Menüde yok; ticker ve tablolardan link ile açılır.

**Amaç:** Tek coin derinlemesine — 1 saatlik mum grafik (RSI/MACD/BB/ATR), feature grid, sinyal + verdict, 9 ajan listesi, backtest istatistik + aylık heatmap, önerilen kaldıraç.

| | |
|---|---|
| **Yenileme** | 10 sn |
| **API** | `GET /api/coin/{SYMBOL}` |

**Fallback:** Redis’te kline yoksa Binance Futures REST (`fapi.binance.com`)

---

## API rotaları (sayfası olmayanlar)

| Endpoint | Kullanım |
|----------|----------|
| `GET /api/ticker` | Layout ticker |
| `GET /api/notifications` | Bildirimler + SmartAlerts |
| `GET /api/activity` | Scanner sidebar |
| `GET /api/emergency` | Positions/Risk acil işlemler |
| `GET /api/portfolio/state` | Agents portföy özeti |
| `GET /api/sqs` | Risk üst SQS listesi |
| `GET /api/symbols` | Agents sembol listesi |
| `GET /api/learn` | Eski öğrenme API (legacy) |
| `GET /api/stream` | SSE — Redis pub/sub |
| `GET /api/alerts` | Alert geçmişi (`alert:history:v1`) |
| `POST /api/alerts` | Alert kaydı + sembol debounce (5 dk) |
| `GET /api/autopsy` | Kapanan işlemler + dersler |

Tüm route’lar: `src/app/api/*/route.ts`, `dynamic = 'force-dynamic'`, Redis: `createRedis()` (`_redis.ts`).

---

## Redis anahtar kataloğu (dashboard okur)

| Anahtar | Yazan servis | Dashboard kullanımı |
|---------|--------------|---------------------|
| `features:latest:{SYMBOL}` | feature_engine | Markets, Scanner, SQS, Coin |
| `signal:latest:{SYMBOL}` | signal_engine | Signals, Agents, Learning |
| `context:latest:{SYMBOL}` | context_engine | Risk, Coin, Analiz |
| `agents:verdict:{SYMBOL}` | agent_system | Agents, Positions, Chat |
| `agents:verdicts:{SYMBOL}` | agent_system | Agents (oy listesi) |
| `learn:profile:{SYMBOL}` | learning_engine | Learning, Memory, Analiz |
| `learn:global:v1` | learning_engine | Learning, Memory |
| `trade:lessons:{SYMBOL}` | learning_engine, autopsy | Learning, Memory, Chat |
| `portfolio:state:v1` | oms | Positions, Agents |
| `shadow:leaderboard` | shadow_system | Shadow, Evolution, Dashboard |
| `system:promotion:status` | promotion_engine | Learning, Risk |
| `system:trading:halted` | dashboard/immunity | Positions, System |
| `immunity:status` | immunity_system | Risk |
| `guard:position:{SYMBOL}` | position_guard | Positions |
| `ws:status` | data_ingestion | Dashboard, System, Scanner |
| `activity:feed` | çoklu | Memory, Learning, Notifications |
| `backtest:results` | backtest | Dashboard, Analiz, Coin |
| `system:heartbeat:{service}` | her servis | System, Learning |
| `system:llm:status` | agent_system | Learning LLM sekmesi |
| `neat:best_genome:{SYMBOL}` | neat_evolution | Evolution, Agents |
| `snapshot:universe:v1` | signal_engine | Evren listesi |
| `alert:history:v1` | dashboard | Alert geçmişi (TTL 24h) |
| `alert:seen:{SYMBOL}` | dashboard | Alert debounce 5 dk |
| `api:cache:markets:v1` | dashboard | Markets API cache 5s |
| `api:cache:scanner:v1` | dashboard | Scanner API cache 5s |
| `api:cache:signals:v1` | dashboard | Signals API cache 5s |

---

## Pub/Sub (dashboard dinler / yazar)

**SSE dinlenen (servisler yazar):**

| Kanal | Yazan |
|-------|-------|
| `ch:signal:{SYMBOL}` | signal_engine |
| `ch:agents:{SYMBOL}` | agent_system |
| `ch:learn:{SYMBOL}` | learning_engine, agent_system |
| `ch:features:{SYMBOL}` | learning_engine |
| `ch:trade_closed` | OMS |
| `ch:position:guard` | position_guard, dashboard command |
| `ch:portfolio:update` | OMS `portfolio_sync` |
| `ch:emergency:close_all` | OMS, dashboard |

## Pub/Sub (dashboard yazar)

| Kanal | Ne zaman |
|-------|----------|
| `ch:emergency:close_all` | Tüm pozisyonları kapat |
| `ch:trading:restart` | İşleme devam |
| `ch:immunity:clear_halt` | Immunity halt temizle |
| `ch:position:guard` | Tek sembol kapat |
| `ch:learn:{SYMBOL}` | Debate yenile |
| `ch:features:{SYMBOL}` | Öğrenme taraması tetikle |

---

## Yenileme süreleri özeti

| Mod | Sayfalar |
|-----|----------|
| **SSE** (`/api/stream`) | Positions, Signals, Analiz, layout ticker/notifications, SmartAlerts, AlertPanel |
| 60 sn yedek poll | Positions, Signals, Analiz, Markets/Scanner/Signals API cache |
| 5–15 sn poll | System, Autopsy, Learning, Dashboard ana sayfa |
| 10 sn poll | Agents, Evolution, Shadow, Coin |
| İstek | Chat (POST), Compare |

*Faz 1 fast path: kritik sayfalar polling’den SSE invalidation’a geçirildi.*

---

## Ortam değişkenleri (dashboard container)

| Değişken | Amaç |
|----------|------|
| `REDIS_URL` / `REDIS_PASSWORD` / `REDIS_HOST` | Redis bağlantısı |
| `DRY_RUN` | Paper mod göstergesi |
| `QDRANT_URL` | Vektör hafıza |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Yerel LLM |
| `GROQ_API_KEY_1..N`, `GROQ_LEARN_MODEL` | Groq (env_file) |
| `LLM_PROVIDER_ORDER`, `AI_ENABLE_SWARM` | LLM sekmesi |

**Önemli:** API anahtarları `env_file: .env` ile gelir; boş `environment:` override kullanılmaz (aksi halde key’ler silinir). `.env` Git’te **izlenmemeli** (`git reset` anahtarları siler).

---

## Yerel geliştirme

```bash
cd services/dashboard
npm install
npm run dev    # http://localhost:3000
```

Docker:

```bash
cd ~/prometheus
docker compose up -d dashboard
# Redis, Ollama, agent_system ayakta olmalı
```

Tanı scripti (sunucu):

```bash
bash scripts/check-llm-env.sh
```

---

## İlgili dokümantasyon

- Repo genel mimari: `CLAUDE.md` (kök)
- LLM orchestration: `services/shared/groq_orchestrator.py`, `.env.example`
- Deploy: `docker-compose.yml` → `dashboard` servisi

---

*Son güncelleme: dashboard menüleri ve API’ler repo `master` dalı ile uyumludur.*
