@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   HOT PATCH — build YOK (~1-3 dk)
echo   Python dosyalari container'a kopyalanir + restart
echo   Karlilik fixleri icin ONERILEN
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )
%PY% scripts\vps_hot_patch.py
pause
