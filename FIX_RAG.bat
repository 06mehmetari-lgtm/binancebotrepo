@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   RAG MEMORY HIZLI DUZELTME
echo   REDIS_URL + container recreate (~2-5 dk, tam deploy degil)
echo ================================================================
echo.
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( echo Python yok & pause & exit /b 1 )
%PY% scripts\fix_rag_memory_vps.py
pause
