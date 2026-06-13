@echo off

chcp 65001 >nul 2>&1

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0DURUM_KONTROL.ps1"

pause

