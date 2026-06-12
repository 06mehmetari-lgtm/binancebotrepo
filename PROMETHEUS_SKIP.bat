@echo off
REM En hizli deploy (~3 dk) — build yok, sadece git + restart
cd /d "%~dp0"
call "%~dp0PROMETHEUS_AYAGA_KALDIR.bat" skip
