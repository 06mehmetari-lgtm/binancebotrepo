@echo off

chcp 65001 >nul 2>&1

setlocal EnableDelayedExpansion



REM ============================================================

REM  PROMETHEUS — TEK TIKLA SUNUCU AYAGA KALDIR

REM  PROMETHEUS_AYAGA_KALDIR.bat

REM  PROMETHEUS_AYAGA_KALDIR.bat quick

REM ============================================================



cd /d "%~dp0"

set "MODE=%~1"

if "%MODE%"=="" set "MODE=full"

set "EXIT_CODE=0"



echo.

echo ================================================================

echo   PROMETHEUS — SUNUCUYU AYAGA KALDIR

echo   Hedef: http://194.163.181.39:3000

echo   Mod  : %MODE%

echo ================================================================

echo.



REM ── Python ───────────────────────────────────────────────────

set "PY="

where python >nul 2>&1 && set "PY=python"

if not defined PY where py >nul 2>&1 && set "PY=py -3"

if not defined PY (

    echo [HATA] Python bulunamadi. https://python.org

    goto :done

)

echo [OK] Python: %PY%



REM ── Gizli bilgiler ───────────────────────────────────────────

set "SECRETS=scripts\.deploy.secrets"

if not exist "%SECRETS%" goto :secrets_missing

goto :secrets_ok



:secrets_missing

echo.

echo [UYARI] %SECRETS% bulunamadi.

if exist "scripts\.deploy.secrets.example" (

    echo.

    echo Ornekten kopyalayin:

    echo   copy scripts\.deploy.secrets.example scripts\.deploy.secrets

    echo VPS_PASS ve OPENROUTER_API_KEY yazin, kaydedin, BAT'i tekrar calistirin.

    echo.

    choice /C YN /M "Ornekten simdi kopyalansin mi"

    if errorlevel 2 goto :secrets_help

    copy /Y "scripts\.deploy.secrets.example" "%SECRETS%" >nul

    echo Dosya olusturuldu — notepad aciliyor...

    notepad "%SECRETS%"

    goto :done

)

:secrets_help

echo.

echo Alternatif ortam degiskeni:

echo   set VPS_PASS=sifreniz

echo   set OPENROUTER_API_KEY=sk-or-v1-...

echo.

goto :done



:secrets_ok



REM ── Git: PC kodu once GitHub'a ───────────────────────────────

where git >nul 2>&1

if errorlevel 1 (

    echo [UYARI] git yok — VPS mevcut GitHub kodu ile devam eder.

    goto :run_deploy

)



echo.

echo [GIT 1/4] Bilgisayardaki degisiklikler hazirlaniyor...

git add -A



set "GIT_DIRTY=0"

for /f "delims=" %%L in ('git status --porcelain 2^>nul') do set "GIT_DIRTY=1"



if "!GIT_DIRTY!"=="1" (

    echo [GIT 2/4] Otomatik commit...

    git commit -m "deploy: PC sync before VPS"

    if errorlevel 1 (

        echo [HATA] git commit basarisiz — deploy durdu.

        set "EXIT_CODE=1"

        goto :done

    )

    echo [OK] Commit tamam.

) else (

    echo [OK] Commit gerekmiyor.

)



echo [GIT 3/4] git pull origin master...

git pull origin master --no-edit

if errorlevel 1 (

    echo [HATA] git pull basarisiz — deploy durdu.

    set "EXIT_CODE=1"

    goto :done

)

echo [OK] git pull tamam.



echo [GIT 4/4] git push origin master...

git push origin master

if errorlevel 1 (

    echo [HATA] git push basarisiz — deploy durdu.

    set "EXIT_CODE=1"

    goto :done

)

echo [OK] git push tamam:

git log -1 --oneline 2>nul

echo.



:run_deploy

echo.

echo [BASLIYOR] VPS deploy — mod=%MODE%

if /i "%MODE%"=="full" (
    echo            FULL: ~17 servis build, 30-45 dk — DONMEDI bekleyin
) else (
    echo            QUICK: ~7 servis build, 10-15 dk
)

echo            Ilerleme: BUILD 3/17 signal_engine gibi satirlar gelir

echo            Log: tail -f /tmp/prometheus_build.log

echo.



%PY% scripts\prometheus_full_deploy.py --mode %MODE%

set "EXIT_CODE=!errorlevel!"



echo.

if "!EXIT_CODE!"=="0" (

    echo ================================================================

    echo   TAMAMLANDI

    echo   http://194.163.181.39:3000

    echo   http://194.163.181.39:3000/system

    echo   http://194.163.181.39:3000/signals

    echo   http://194.163.181.39:3000/positions

    echo ================================================================

) else (

    echo ================================================================

    echo   HATA — tekrar: PROMETHEUS_AYAGA_KALDIR.bat quick

    echo ================================================================

)



:done

echo.

pause

exit /b %EXIT_CODE%


