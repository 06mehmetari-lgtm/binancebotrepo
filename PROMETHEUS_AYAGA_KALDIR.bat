@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

REM ============================================================
REM  PROMETHEUS — TEK TIK, TAM OTOMATIK DEPLOY
REM  PROMETHEUS_AYAGA_KALDIR.bat        → FULL (17 servis, ~30-45 dk)
REM  PROMETHEUS_AYAGA_KALDIR.bat quick → hizli (~9 servis)
REM ============================================================

cd /d "%~dp0"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=full"
set "EXIT_CODE=0"
set "SECRETS=scripts\.deploy.secrets"

echo.
echo ================================================================
echo   PROMETHEUS — TAM OTOMATIK SUNUCU DEPLOY
echo   http://194.163.181.39:3000
echo   Mod: %MODE%
echo ================================================================
echo.

REM ── Python ──
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo [HATA] Python yok — https://python.org kurun, tekrar calistirin.
    set "EXIT_CODE=1"
    goto :done
)
echo [OK] Python: %PY%

REM ── paramiko (SSH) otomatik ──
%PY% -m pip install paramiko -q 2>nul
echo [OK] paramiko hazir

REM ── Gizli bilgiler: dosya VEYA ortam degiskeni ──
set "HAS_SECRETS=0"
if exist "%SECRETS%" set "HAS_SECRETS=1"
if defined VPS_PASS set "HAS_SECRETS=1"
if "!HAS_SECRETS!"=="0" (
    echo.
    echo [HATA] VPS sifresi gerekli — bir kez ayarlayin:
    echo   copy scripts\.deploy.secrets.example scripts\.deploy.secrets
    echo   VPS_PASS ve OPENROUTER_API_KEY yazin
    echo   VEYA: set VPS_PASS=sifreniz
    echo.
    set "EXIT_CODE=1"
    goto :done
)
echo [OK] Deploy kimlik bilgileri hazir

REM ── Git: PC -^> GitHub -^> VPS (otomatik) ──
where git >nul 2>&1
if errorlevel 1 (
    echo [UYARI] git yok — VPS GitHub'daki son kodu kullanir
    goto :run_deploy
)

echo.
echo [GIT] Senkronizasyon...
git add -A

set "GIT_DIRTY=0"
for /f "delims=" %%L in ('git status --porcelain 2^>nul') do set "GIT_DIRTY=1"

if "!GIT_DIRTY!"=="1" (
    echo [GIT] Otomatik commit...
    git commit -m "deploy: PC sync before VPS"
    if errorlevel 1 (
        echo [HATA] git commit basarisiz
        set "EXIT_CODE=1"
        goto :done
    )
) else (
    echo [GIT] Commit gerekmiyor
)

echo [GIT] pull...
git pull origin master --rebase --no-edit
if errorlevel 1 (
    git stash push -u -m "deploy-autostash" 2>nul
    git pull origin master --rebase --no-edit
    if errorlevel 1 (
        echo [HATA] git pull basarisiz
        set "EXIT_CODE=1"
        goto :done
    )
    git stash pop 2>nul
)

echo [GIT] push...
git push origin master
if errorlevel 1 (
    git pull origin master --rebase --no-edit
    git push origin master
    if errorlevel 1 (
        echo [HATA] git push basarisiz
        set "EXIT_CODE=1"
        goto :done
    )
)
git log -1 --oneline 2>nul
echo [OK] GitHub guncel

:run_deploy
echo.
echo [DEPLOY] VPS bootstrap basliyor — mod=%MODE%
if /i "%MODE%"=="full" (
    echo          FULL: 17 servis build + tum konteynerler + saglik kontrolu
    echo          Sure: ~30-45 dk — pencereyi KAPATMAYIN
) else (
    echo          QUICK: 9 servis build + tum konteynerler
    echo          Sure: ~12-18 dk
)
echo.

%PY% scripts\prometheus_full_deploy.py --mode %MODE%
set "EXIT_CODE=!errorlevel!"

echo.
if "!EXIT_CODE!"=="0" (
    echo ================================================================
    echo   BASARILI — sistem ayakta, hicbir sey yapmaniz gerekmiyor
    echo   http://194.163.181.39:3000
    echo   http://194.163.181.39:3000/positions
    echo   http://194.163.181.39:3000/system
    echo ================================================================
    start "" "http://194.163.181.39:3000/system"
) else (
    echo ================================================================
    echo   HATA — log: ssh root@194.163.181.39 tail -100 /tmp/prometheus_bootstrap.log
    echo   Tekrar: PROMETHEUS_AYAGA_KALDIR.bat
    echo ================================================================
)

:done
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
