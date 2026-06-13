@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

REM ============================================================
REM  PROMETHEUS — TEK TIK DEPLOY
REM  PROMETHEUS_AYAGA_KALDIR.bat         → QUICK (~15-45 dk, timeout 3 saat)
REM  PROMETHEUS_AYAGA_KALDIR.bat skip    → EN HIZLI (~3 dk, build yok)
REM  PROMETHEUS_AYAGA_KALDIR.bat minimal → 4 servis (~5-12 dk, dashboard yok)
REM  PROMETHEUS_AYAGA_KALDIR.bat full    → 17 servis (~30-60 dk, timeout 4 saat)
REM  ROLLING_DEPLOY.bat                   → Faz1 hemen + Faz2 arka plan build (ONERILEN)
REM  HOT_PATCH.bat                       → build YOK (~1-3 dk, kod kopyala)
REM  HIZLI_DEPLOY.bat                    → 4 servis build (~5-12 dk)
REM ============================================================

cd /d "%~dp0"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=quick"
set "EXIT_CODE=0"
set "SECRETS=scripts\.deploy.secrets"

echo.
echo ================================================================
echo   PROMETHEUS — OTOMATIK DEPLOY
echo   http://194.163.181.39:3000
echo   Mod: %MODE%
echo ================================================================
echo.

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo [HATA] Python yok
    set "EXIT_CODE=1"
    goto :done
)
echo [OK] Python: %PY%
%PY% -m pip install paramiko -q 2>nul

set "HAS_SECRETS=0"
if exist "%SECRETS%" set "HAS_SECRETS=1"
if defined VPS_PASS set "HAS_SECRETS=1"
if "!HAS_SECRETS!"=="0" (
    echo [HATA] scripts\.deploy.secrets veya VPS_PASS gerekli
    set "EXIT_CODE=1"
    goto :done
)

where git >nul 2>&1
if not errorlevel 1 (
    echo [GIT] Senkron...
    git add -A
    set "GIT_DIRTY=0"
    for /f "delims=" %%L in ('git status --porcelain 2^>nul') do set "GIT_DIRTY=1"
    if "!GIT_DIRTY!"=="1" (
        git commit -m "deploy: PC sync before VPS"
        if errorlevel 1 ( set "EXIT_CODE=1" & goto :done )
    )
    git pull origin master --rebase --no-edit 2>nul
    git push origin master 2>nul
    if errorlevel 1 (
        git pull origin master --rebase --no-edit
        git push origin master
    )
    git log -1 --oneline 2>nul
)

echo.
if /i "%MODE%"=="skip" goto deploy_skip
if /i "%MODE%"=="full" goto deploy_full
if /i "%MODE%"=="minimal" goto deploy_minimal
goto deploy_quick

:deploy_minimal
echo [DEPLOY] MINIMAL - 4 servis build, dashboard YOK, ~5-12 dk
goto deploy_run

:deploy_skip
echo [DEPLOY] SKIP - build YOK, git pull + restart, ~3 dk
goto deploy_run

:deploy_full
echo [DEPLOY] FULL - 17 servis PARALEL build, ~30-60 dk, timeout 4 saat
goto deploy_run

:deploy_quick
echo [DEPLOY] QUICK - 10 kritik servis PARALEL build, ~15-45 dk, timeout 3 saat

:deploy_run
echo.

%PY% scripts\prometheus_full_deploy.py --mode %MODE%
set "EXIT_CODE=!errorlevel!"

echo.
if "!EXIT_CODE!"=="0" (
    echo ================================================================
    echo   BASARILI — http://194.163.181.39:3000/system
    echo ================================================================
    start "" "http://194.163.181.39:3000/system"
) else (
    echo ================================================================
    echo   HATA — hizli tekrar: PROMETHEUS_AYAGA_KALDIR.bat skip
    echo   kod degisti (hizli):  HOT_PATCH.bat  veya  HIZLI_DEPLOY.bat
    echo   kod degisti (4 svc):   PROMETHEUS_AYAGA_KALDIR.bat minimal
    echo   kod degisti (10 svc):  PROMETHEUS_AYAGA_KALDIR.bat
    echo   tum servis:          PROMETHEUS_AYAGA_KALDIR.bat full
    echo ================================================================
)

:done
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
