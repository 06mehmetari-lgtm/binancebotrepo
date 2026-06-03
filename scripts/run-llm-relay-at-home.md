# Groq/Cerebras — ev PC relay (ücretsiz, 1010 bypass)

VPS (Contabo) Cloudflare **1010** veriyor. Relay’i **ev bilgisayarında** çalıştırın; VPS relay üzerinden Groq’a gider.

## 1) Ev PC — relay başlat

```bash
git clone https://github.com/06mehmetari-lgtm/binancebotrepo.git
cd binancebotrepo
export LLM_RELAY_SECRET="uzun-rastgele-bir-sifre-buraya"
docker compose --profile relay build llm_relay
docker compose --profile relay up -d llm_relay
curl http://127.0.0.1:8099/health
```

## 2) Ev PC — Cloudflare Tunnel (port açmadan)

```bash
# cloudflared kur: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
cloudflared tunnel --url http://127.0.0.1:8099
```

Çıktıdaki `https://xxxx.trycloudflare.com` URL’sini kopyalayın.

## 3) VPS — `.env`

```bash
LLM_RELAY_URL=https://xxxx.trycloudflare.com
LLM_RELAY_SECRET=uzun-rastgele-bir-sifre-buraya
LLM_OLLAMA_ONLY=false
LLM_CLOUD_BLOCKED=false
LLM_PROVIDER_ORDER=groq,cerebras,ollama
```

```bash
cd ~/prometheus
bash scripts/enable-groq-cerebras.sh
```

## 4) Test

Probe’da `OK GROQ_API_KEY_1` görmelisiniz.

## Alternatif: sadece proxy (relay yok)

Residential proxy satın alın, VPS `.env`:

```bash
HTTPS_PROXY=http://USER:PASS@gate.proxy-provider.com:PORT
```

Sonra `bash scripts/enable-groq-cerebras.sh`
