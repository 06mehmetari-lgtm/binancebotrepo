@echo off
REM Prometheus — Sunucuya Deploy Scripti
REM Kullanim: deploy_to_server.bat
REM Gereksinim: OpenSSH (Windows 10+ dahili)

SET SERVER_IP=194.163.181.39
SET SERVER_USER=root
SET SERVER_PATH=/opt/prometheus

echo.
echo ================================================
echo  PROMETHEUS TRADING SYSTEM - DEPLOY
echo  Sunucu: %SERVER_USER%@%SERVER_IP%
echo ================================================
echo.

REM 1. Adim: setup scriptini gonder ve calistir
echo [1/4] Kurulum scripti gonderiliyor...
scp -o StrictHostKeyChecking=no setup_server.sh %SERVER_USER%@%SERVER_IP%:/root/setup_server.sh
echo [1/4] Kurulum scripti calistiriliyor (2-5 dakika surebilir)...
ssh -o StrictHostKeyChecking=no %SERVER_USER%@%SERVER_IP% "bash /root/setup_server.sh"

REM 2. Adim: Proje dosyalarini gonder
echo.
echo [2/4] Proje dosyalari sunucuya kopyalaniyor...
scp -o StrictHostKeyChecking=no -r . %SERVER_USER%@%SERVER_IP%:%SERVER_PATH%/
echo [2/4] Kopyalama tamamlandi.

REM 3. Adim: .env dosyasini kontrol et
echo.
echo [3/4] .env dosyasi kontrol ediliyor...
ssh -o StrictHostKeyChecking=no %SERVER_USER%@%SERVER_IP% "ls -la %SERVER_PATH%/.env 2>/dev/null && echo '.env MEVCUT' || echo 'UYARI: .env eksik, cp .env.example .env yapip doldurun'"

REM 4. Adim: Servisleri baslat
echo.
echo [4/4] Docker servisleri baslatiliyor...
ssh -o StrictHostKeyChecking=no %SERVER_USER%@%SERVER_IP% "cd %SERVER_PATH% && docker compose up -d 2>&1 | tail -20"

echo.
echo ================================================
echo  DEPLOY TAMAMLANDI
echo  Dashboard : http://%SERVER_IP%:3000
echo  Grafana   : http://%SERVER_IP%:3001
echo  Prometheus: http://%SERVER_IP%:9090
echo ================================================
pause
