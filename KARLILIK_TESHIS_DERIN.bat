@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo.
echo ================================================================
echo   DERIN KARLILIK TESHISI
echo ================================================================
echo.
echo   OZET PANEL [4z] bolumunde (detaydan ONCE — yuksek VPS yukunde onemli)
echo   -----------------------------------------------
echo   SINIRLAR     : Kac pozisyon alabilir? (max slot, %% portfoy, kaldirac)
echo   ANLIK        : Simdi kac acik? (shadow/oms, bos slot)
echo   TARAMA       : Kac sembol tarandi? ALIM_UYGUN kac? Blokaj dagilimi
echo   BEKLEYEN     : Alinmayi bekleyen (hazir / cooldown / slot dolu)
echo   ACIK         : Su an tutulan pozisyonlar + anlik uPnL
echo   ALINMIS      : Islem gecmisi, son 5 islem, kazanc/zarar sayisi
echo   ZARAR/KAZANC : En cok kaybettiren ve kazandiran semboller
echo.
echo   Detay: pipeline, shadow izi, ajan oylari, islem dongusu
echo   Sure: ~30-90 sn
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
echo [2/2] Derin analiz — cikti canli akar...
echo.
%PY% scripts\profit_deep_diagnosis.py
pause
