@echo off
chcp 65001 >nul
echo ===========================================
echo   ITHALAT VERGI HESAPLAMA - Yerel Sunucu
echo ===========================================
echo.
echo Proje dizini: %~dp0
echo Sunucu baslatiliyor: http://localhost:8080
echo.
echo Tarayicida ac: http://localhost:8080
echo Durdurmak icin: Ctrl+C
echo.

cd /d "%~dp0"

python -m http.server 8080 2>nul
if errorlevel 1 (
    python3 -m http.server 8080 2>nul
    if errorlevel 1 (
        npx http-server -p 8080 -c-1 2>nul
        if errorlevel 1 (
            echo HATA: Python 3 veya Node.js bulunamadi!
            echo Lutfen Python 3 (python.org) veya Node.js (nodejs.org) kurun.
            pause
        )
    )
)