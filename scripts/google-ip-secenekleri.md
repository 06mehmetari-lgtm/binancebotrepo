# “Google IP” ile Groq / LLM (PC kapalı, sadece sunucu)

## Ne demek?

| Anlama | PC kapalı 7/24? | Groq aynı mı? |
|--------|------------------|----------------|
| **A) Gemini API** (Google AI Studio anahtarı) | ✅ VPS’ten direkt | Hayır → **Gemini** modeli |
| **B) GCP’de relay** (Google Cloud çıkış IP’si) | ✅ VM/Cloud Run açık | ✅ Groq **olabilir** (Contabo gibi değil) |
| **C) “Google IP taklit”** | ❌ | ❌ İşe yaramaz |

---

## A) Gemini — en kolay (ücretsiz katman, önerilen)

Groq değil; Google’ın **Gemini** API’si. Çoğu VPS’te **1010 olmaz** (farklı servis).

1. https://aistudio.google.com/apikey → API key  
2. VPS `.env`:

```bash
GOOGLE_AI_API_KEY=AIza...
GOOGLE_AI_MODEL=gemini-2.0-flash
LLM_PROVIDER_ORDER=google,ollama,groq,cerebras
LLM_OLLAMA_ONLY=false
```

3. `bash scripts/enable-google-gemini-vps.sh`

**PC gerekmez.** Kota: ücretsiz katman sınırlı (günlük istek).

---

## B) Google Cloud (GCP) üzerinde Groq relay

İstek **Google datacenter IP**’sinden Groq’a gider.

1. GCP hesabı → Compute Engine **e2-micro** (Always Free, `us-central1`)  
2. Orada:

```bash
git clone .../binancebotrepo && cd binancebotrepo
export LLM_RELAY_SECRET=uzun-sifre
docker compose --profile relay up -d llm_relay
# Firewall: TCP 8099 açık
```

3. Ana VPS (Contabo) `.env`:

```bash
LLM_RELAY_URL=http://GCP_PUBLIC_IP:8099
LLM_RELAY_SECRET=uzun-sifre
LLM_OLLAMA_ONLY=false
bash scripts/enable-groq-cerebras.sh
```

GCP VM **7/24** açık kalmalı (PC değil).  
Hâlâ 1010 olursa → Gemini (A) veya residential proxy.

---

## C) Groq’u “Google IP” diye ücretsiz almak

Yok. Google soket satmaz. Ya **Gemini API** ya **GCP relay** ya **proxy**.

---

## Sizin için özet (PC hep kapalı)

1. **Hemen:** `bash scripts/enable-google-gemini-vps.sh` (Gemini anahtarı ile)  
2. **Groq şart:** GCP relay (B) veya ücretli proxy  
3. **Yedek:** `bash scripts/ensure-llm-production.sh` (Ollama)

Üçü birden `.env` sırası:

```bash
LLM_PROVIDER_ORDER=google,ollama,groq,cerebras
```
