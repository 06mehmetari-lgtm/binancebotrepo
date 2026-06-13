@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo   Arka plan build durumu
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
%PY% scripts\check_bg_build.py
pause
