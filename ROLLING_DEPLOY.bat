@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   ROLLING DEPLOY
echo   Faz1: kod cek + hemen calistir (~3-5 dk)
echo   Faz2: tum servisler arka planda build (dashboard dahil)
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )

echo [GIT] PC -^> GitHub...
git add -A 2>nul
git commit -m "deploy: rolling" 2>nul
git push origin master 2>nul
if errorlevel 1 (
    echo [GIT] push uyarisi — devam ediliyor
)

%PY% scripts\vps_rolling_deploy.py
echo.
echo Arka plan build durumu icin: BG_BUILD_DURUM.bat
pause
