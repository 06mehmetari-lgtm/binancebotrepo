@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   HIZLI DEPLOY — 4 servis build (~5-12 dk)
echo   shadow + agent + signal + oms (dashboard YOK)
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )

echo [GIT] PC -^> GitHub...
git add -A 2>nul
git commit -m "deploy: minimal" 2>nul
git push origin master 2>nul

%PY% scripts\vps_minimal_deploy.py
pause
