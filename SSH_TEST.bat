@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   SSH BAGLANTI TESTI
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )
%PY% scripts\test_ssh_connection.py
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" (
    echo Baglanti OK — KARLILIK_TESHIS.bat calistirabilirsiniz.
) else (
    echo Baglanti BASARISIZ — once SSH_SIFRE_DEGISTIR.bat
)
pause
exit /b %RC%
