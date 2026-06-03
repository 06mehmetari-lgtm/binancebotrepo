# PC kapalı — sadece VPS (7/24)

## Tek komut (önerilen)

```bash
cd ~/prometheus
git fetch origin
git checkout origin/master -- scripts/setup-vps-llm-wait-mode.sh services/shared/llm_providers.py services/agent_system/debate_agent.py docker-compose.yml
# .env içine: GOOGLE_AI_API_KEY=AIza...  (https://aistudio.google.com/apikey)
bash scripts/setup-vps-llm-wait-mode.sh
```

- **Gemini** önce (limit → bekler, kota açılınca devam)
- **Ollama** yedek
- **Groq/Cerebras** denenir (`ALLOW_GROQ_ON_VPS=true`; otomatik 1010 skip kaldırıldı)
- **PC gerekmez**

---

## Kısa cevap

| Yöntem | PC kapalıyken çalışır mı? |
|--------|---------------------------|
| Ev relay / SSH SOCKS | **HAYIR** (ev interneti gerekir) |
| VPS’ten **direkt** Groq/Cerebras | **HAYIR** (Contabo IP → 1010) |
| VPS’te **Ollama** | **EVET** (ücretsiz, 7/24) |
| VPS + **ücretli residential proxy** | **EVET** (Groq/Cerebras, 7/24) |
| **İkinci ücretsiz VPS**’te relay (Oracle US vb.) | **EVET** (PC yok, denenebilir) |

---

## Seçenek 0 — Google Gemini API (ücretsiz katman, PC yok) ← Groq yerine

`GOOGLE_AI_API_KEY` → VPS’ten direkt, çoğu zaman 1010 **yok**.

```bash
bash scripts/enable-google-gemini-vps.sh
```

Detay: `scripts/google-ip-secenekleri.md`

---

## Seçenek 1 — Ollama (ücretsiz, PC gerekmez)

Ana makinede (194.163.181.39):

```bash
cd ~/prometheus
git fetch origin
git checkout origin/master -- scripts/ensure-llm-production.sh scripts/probe-llm-keys.py docker-compose.yml services/shared/

bash scripts/ensure-llm-production.sh
```

Kontrol:

```bash
docker compose exec agent_system python3 /tmp/probe_llm_keys.py 2>/dev/null | grep OLLAMA
# OK görünmeli
```

`.env` (PC kapalı mod):

```bash
LLM_OLLAMA_ONLY=true
LLM_PROVIDER_ORDER=ollama
OLLAMA_MODEL=llama3.2:3b
```

Groq/Cerebras **bu IP’den yine çalışmaz**; bot **Ollama ile** çalışır.

---

## Seçenek 2 — Groq/Cerebras 7/24 (PC yok) → residential proxy

1. Webshare / IPRoyal / benzeri → **residential** HTTP proxy alın  
2. VPS `.env`:

```bash
HTTPS_PROXY=http://USER:PASS@gate.provider.com:PORT
LLM_OLLAMA_ONLY=false
LLM_CLOUD_BLOCKED=false
LLM_PROVIDER_ORDER=groq,cerebras,ollama
```

3. `bash scripts/enable-groq-cerebras.sh`  
4. Probe: `OK GROQ_API_KEY_1`

Aylık ~$5–15; PC kapalı kalabilir.

---

## Seçenek 3 — Ücretsiz ikinci VPS relay (PC yok, dene)

Oracle Cloud Always Free (ABD bölgesi) veya başka küçük VPS:

- Orada `docker compose --profile relay up -d llm_relay`  
- O makinenin public IP:8099 veya cloudflared  
- Ana VPS `.env`: `LLM_RELAY_URL=http://IKINCI_VPS_IP:8099`

İkinci VPS **7/24 açık** kalmalı (PC değil, bulut).

Groq yine 1010 verirse o bölge de bloklu demektir → Seçenek 2.

---

## Yapmayın

- 100 ücretsiz proxy sitesi + API anahtarı  
- PC kapalıyken `LLM_RELAY_URL` ev tüneli  
- VPS’ten proxy olmadan Groq beklemek  

---

## Sizin durumunuz için öneri

1. **Hemen:** `ensure-llm-production.sh` → Ollama 7/24  
2. **Groq şart ise:** residential proxy (Seçenek 2) veya ikinci VPS relay (Seçenek 3)  
3. **Ev PC:** sadece test için; üretimde kapalı olabilir  
