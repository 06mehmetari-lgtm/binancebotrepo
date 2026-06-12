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

REM ── Git durumu (errorlevel bug fix: !errorlevel! / for-f loop) ─
set "GIT_DIRTY=0"
where git >nul 2>&1
if !errorlevel! equ 0 (
    for /f "delims=" %%L in ('git status --porcelain 2^>nul') do set "GIT_DIRTY=1"
    if "!GIT_DIRTY!"=="1" (
        echo [UYARI] Yerelde commit edilmemis degisiklik var.
        echo         Sunucu GitHub master ceker — once push yapmaniz onerilir:
        echo           git add -A ^&^& git commit -m "deploy" ^&^& git push origin master
        echo.
        choice /C YN /M "Yine de deploy devam etsin mi"
        if errorlevel 2 (
            echo Iptal.
            pause
            exit /b 0
        )
    ) else (
        echo [OK] Yerel git temiz — sunucu origin/master pull yapacak.
        git rev-parse --abbrev-ref HEAD 2>nul
        git log -1 --oneline 2>nul
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
