@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   KARLILIK TESHISI — hizli ozet
echo   Detayli analiz icin: KARLILIK_TESHIS_DERIN.bat
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
%PY% scripts\profit_diagnosis.py
pause
