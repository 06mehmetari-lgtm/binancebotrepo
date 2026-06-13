@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   PROMETHEUS DEPLOY — tek tik
echo   Git push + akilli servis guncelleme + dashboard versiyon
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )
%PY% scripts\smart_deploy.py
pause
