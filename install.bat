@echo off
chcp 65001 >nul
title Topshiriq Bot - O'rnatish

echo ╔══════════════════════════════════════════╗
echo ║   TOPSHIRIQ BOTI - O'RNATISH DASTURI    ║
echo ╚══════════════════════════════════════════╝
echo.

:: Python mavjudligini tekshirish
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [XATO] Python topilmadi!
    echo.
    echo Python 3.11+ ni https://www.python.org/downloads/ dan yuklab o'rnating.
    echo O'rnatayotganda "Add Python to PATH" degan katakchani belgilang!
    echo.
    pause
    exit /b 1
)

echo [1/3] Python topildi:
python --version
echo.

:: Virtual muhit yaratish
echo [2/3] Virtual muhit yaratilmoqda...
if not exist "venv" (
    python -m venv venv
    echo     Virtual muhit yaratildi.
) else (
    echo     Virtual muhit allaqachon mavjud.
)
echo.

:: Kutubxonalarni o'rnatish
echo [3/3] Kutubxonalar o'rnatilmoqda...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo     Barcha kutubxonalar o'rnatildi.
echo.

:: .env faylini yaratish
if not exist ".env" (
    copy .env.example .env >nul
    echo ╔══════════════════════════════════════════════════╗
    echo ║  MUHIM: .env faylini to'ldiring!                ║
    echo ║                                                  ║
    echo ║  1. .env faylini Notepad bilan oching            ║
    echo ║  2. BOT_TOKEN ni @BotFather dan oling            ║
    echo ║  3. MANAGER_IDS ga o'z ID'ingizni yozing         ║
    echo ║  4. Guruh ID'larni botga /id yozib aniqlang      ║
    echo ║  5. AI uchun ANTHROPIC_API_KEY ni to'ldiring      ║
    echo ╚══════════════════════════════════════════════════╝
    echo.
    echo .env fayli yaratildi. Uni to'ldirgandan keyin start.bat ni ishga tushiring.
) else (
    echo .env fayli allaqachon mavjud.
    echo.
    echo O'rnatish tugadi! Botni ishga tushirish uchun start.bat ni bosing.
)

echo.
pause
