@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   DASHBOARD REBUILD — KASA kutusu icin (VPS build)
echo   DEPLOY takildiysa veya KASA gorunmuyorsa bunu calistirin
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )
%PY% scripts\dashboard_rebuild.py
set "RC=%errorlevel%"
if "%RC%"=="0" start "" "http://194.163.181.39:3000/positions#kasa"
pause
exit /b %RC%
