@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

REM ============================================================
REM  PROMETHEUS TRADING SYSTEM — TEK TIKLA SUNUCU AYAĞA KALDIR
REM  Kullanım: Bu dosyaya çift tıkla VEYA komut satırından:
REM    PROMETHEUS_AYAGA_KALDIR.bat
REM    PROMETHEUS_AYAGA_KALDIR.bat quick     (hızlı — sadece pipeline)
REM    PROMETHEUS_AYAGA_KALDIR.bat full      (tam — tüm servisler)
REM ============================================================

cd /d "%~dp0"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=full"

echo.
echo ================================================================
echo   PROMETHEUS — SUNUCUYU AYAGA KALDIR
echo   Hedef: http://194.163.181.39:3000
echo   Mod  : %MODE%
echo ================================================================
echo.

REM ── Python bul ──────────────────────────────────────────────
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo [HATA] Python bulunamadi. Python 3.10+ kurun: https://python.org
    pause
    exit /b 1
)
echo [OK] Python: %PY%

REM ── Gizli bilgiler dosyasi ──────────────────────────────────
set "SECRETS=scripts\.deploy.secrets"
if not exist "%SECRETS%" (
    echo.
    echo [UYARI] %SECRETS% bulunamadi.
    echo.
    if exist "scripts\.deploy.secrets.example" (
        echo Ornek dosyadan kopyalayin:
        echo   copy scripts\.deploy.secrets.example scripts\.deploy.secrets
        echo Sonra VPS_PASS ve OPENROUTER_API_KEY doldurun.
        echo.
        choice /C YN /M "Simdi ornekten kopyalansin mi"
        if errorlevel 2 goto :need_secrets
        copy /Y "scripts\.deploy.secrets.example" "%SECRETS%" >nul
        echo.
        echo %SECRETS% olusturuldu — SIMDI SIFRE VE API KEY YAZIN, kaydedin, tekrar calistirin.
        notepad "%SECRETS%"
        pause
        exit /b 0
    )
    :need_secrets
    echo.
    echo Alternatif — ortam degiskeni:
    echo   set VPS_PASS=sifreniz
    echo   set OPENROUTER_API_KEY=sk-or-v1-...
    echo.
)

REM ── Opsiyonel: yerel degisiklikleri push et ─────────────────
where git >nul 2>&1
if %errorlevel%==0 (
    git status --porcelain 2>nul | findstr /R "." >nul
    if %errorlevel%==0 (
        echo [BILGI] Yerelde commit edilmemis degisiklik var.
        echo         Sunucu git pull ile master ceker — once push yapin:
        echo           git add -A ^&^& git commit -m "deploy" ^&^& git push origin master
        echo.
        choice /C YN /M "Yine de deploy devam etsin mi"
        if errorlevel 2 (
            echo Iptal.
            pause
            exit /b 0
        )
    ) else (
        echo [BILGI] Yerel temiz — sunucu master pull yapacak.
        choice /C YN /M "Once git push origin master yapilsin mi"
        if not errorlevel 2 (
            git push origin master 2>nul
            if !errorlevel! neq 0 echo [UYARI] git push basarisiz — sunucu mevcut master ile devam eder.
        )
    )
)

REM ── Deploy calistir ─────────────────────────────────────────
echo.
echo [BASLIYOR] VPS deploy — bu 10-45 dakika surebilir (%MODE% mod)...
echo            Takilirsa sunucuda: tail -f /tmp/prometheus_bootstrap.log
echo.

%PY% scripts\prometheus_full_deploy.py --mode %MODE%
set "EXIT_CODE=%errorlevel%"

echo.
if %EXIT_CODE%==0 (
    echo ================================================================
    echo   TAMAMLANDI — Tarayicida acin:
    echo   http://194.163.181.39:3000
    echo   http://194.163.181.39:3000/system
    echo   http://194.163.181.39:3000/signals
    echo   http://194.163.181.39:3000/positions
    echo ================================================================
) else (
    echo ================================================================
    echo   HATA veya KISMI BASARI — tekrar deneyin veya:
    echo   PROMETHEUS_AYAGA_KALDIR.bat quick
    echo ================================================================
)

pause
exit /b %EXIT_CODE%
