# Ücretsiz Groq/Cerebras (VPS → ev internet çıkışı)

**Ücretli residential proxy yok.** Ücretsiz yollar:

| Yöntem | Maliyet | Ev PC açık kalmalı |
|--------|---------|---------------------|
| **A) LLM relay + Cloudflare Tunnel** | 0 ₺ | Evde relay çalışırken |
| **B) SSH SOCKS (ev → VPS tünel)** | 0 ₺ | SSH bağlantısı açıkken |
| **C) Farklı ücretsiz VPS (Oracle US)** | 0 ₺* | Hayır (*Groq yine 1010 verebilir) |

---

## A) LLM relay + Cloudflare (önerilen, zaten repoda)

Ev PC Groq’a **doğrudan** gider (ev IP). VPS sadece tünel URL’sine istek atar.

```bash
# === EV PC ===
export LLM_RELAY_SECRET="uzun-rastgele-sifre"
cd binancebotrepo
docker compose --profile relay up -d llm_relay

# cloudflared kur, sonra:
cloudflared tunnel --url http://127.0.0.1:8099
# Çıkan URL: https://xxxx.trycloudflare.com
```

```bash
# === VPS (194.163.181.39) ===
cd ~/prometheus
nano .env   # ekle:
# LLM_RELAY_URL=https://xxxx.trycloudflare.com
# LLM_RELAY_SECRET=uzun-rastgele-sifre

git fetch origin
git checkout origin/master -- scripts/enable-groq-cerebras.sh services/shared/llm_providers.py docker-compose.yml
bash scripts/enable-groq-cerebras.sh
```

Probe: `OK GROQ_API_KEY_1`

---

## B) SSH SOCKS — ekstra yazılım yok (sadece SSH)

Ev internetinden çıkış; VPS `ALL_PROXY` ile Groq’a gider.

### 1) Ev PC’de (Windows PowerShell veya Linux)

VPS’e **ters tünel** aç (ev PC bunu çalıştırır, VPS IP’sini bilir):

```bash
# EV PC — VPS root şifresi / key ile
ssh -N -R 1080:127.0.0.1:1080 root@194.163.181.39
```

Bu, VPS üzerinde `127.0.0.1:1080` → ev PC’nin internet çıkışına SOCKS proxy açar.

Kalıcı için ev PC’de `autossh` veya Windows Görev Zamanlayıcı ile bu komutu sürekli çalıştırın.

VPS’te `sshd` ayarı (bir kez):

```bash
# VPS
grep -q '^AllowTcpForwarding' /etc/ssh/sshd_config || echo 'AllowTcpForwarding yes' >> /etc/ssh/sshd_config
grep -q '^GatewayPorts' /etc/ssh/sshd_config || echo 'GatewayPorts yes' >> /etc/ssh/sshd_config
systemctl reload sshd
```

### 2) VPS `.env`

```bash
ALL_PROXY=socks5://127.0.0.1:1080
LLM_OLLAMA_ONLY=false
LLM_CLOUD_BLOCKED=false
```

```bash
bash scripts/enable-groq-cerebras.sh
```

**Not:** Ev PC kapalıysa veya SSH koparsa Groq yine fail olur.

---

## C) “Ücretsiz residential proxy” siteleri

Çoğu:

- Sahte / çalıntı IP listesi  
- Groq için çalışmaz  
- Güvenlik riski  

**Önerilmez.**

---

## Hızlı kontrol (VPS)

```bash
# Relay kullanıyorsanız:
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $GROQ_API_KEY_1" \
  -H "Content-Type: application/json" \
  -d '{"model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' \
  https://api.groq.com/openai/v1/chat/completions
# 403/1010 = hâlâ blok

# SOCKS açıksa aynı curl --proxy socks5://127.0.0.1:1080 ...
```

---

## Özet

- **Ev IP gibi ücretsiz çıkış = evden relay (A) veya SSH SOCKS (B).**  
- **VPS tek başına Groq’a dokunamaz** (1010).  
- En kolay ücretsiz: **A + cloudflared** (`scripts/run-llm-relay-at-home.md`).
