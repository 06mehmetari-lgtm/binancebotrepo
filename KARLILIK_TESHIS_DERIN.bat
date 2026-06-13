@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   DERIN KARLILIK TESHISI
echo   Tam pipeline + shadow izi + islem dongusu + LLM JSON ozeti
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )

echo [1/2] SSH test...
%PY% scripts\test_ssh_connection.py
if errorlevel 1 (
    echo.
    echo SSH basarisiz — SSH_SIFRE_DEGISTIR.bat calistirin
    pause
    exit /b 1
)
echo [2/2] Derin analiz — cikti canli akar, 30-90 sn surebilir...
echo.
%PY% scripts\profit_deep_diagnosis.py
pause
