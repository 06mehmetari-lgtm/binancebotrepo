@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ================================================================
echo   SSH SIFRE DEGISTIR
echo   Tum deploy/durum scriptleri scripts\.deploy.secrets okur
echo ================================================================
echo.

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo [HATA] Python yuklu degil
    pause
    exit /b 1
)

%PY% scripts\update_ssh_password.py
set "RC=!errorlevel!"
if not defined RC set "RC=0"

if "%RC%"=="0" (
    echo.
    echo Test icin: DURUM_KONTROL.bat
) else (
    echo.
    echo [HATA] Sifre guncellenemedi
)

pause
exit /b %RC%
