@echo off
chcp 65001 >nul
title Robot Mutaxassis Bot - O'rnatish

echo ╔═══════════════════════════════════════════════════╗
echo ║    ROBOT MUTAXASSIS BOT - O'RNATISH DASTURI      ║
echo ╚═══════════════════════════════════════════════════╝
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

echo [1/4] Python topildi:
python --version
echo.

:: Virtual muhit yaratish
echo [2/4] Virtual muhit yaratilmoqda...
if not exist "venv" (
    python -m venv venv
    echo     Virtual muhit yaratildi.
) else (
    echo     Virtual muhit allaqachon mavjud.
)
echo.

:: Kutubxonalarni o'rnatish
echo [3/4] Kutubxonalar o'rnatilmoqda (Pillow, Telethon va boshqalar)...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo     Barcha kutubxonalar o'rnatildi.
echo.

:: .env faylini yaratish
echo [4/4] Sozlamalar fayli tekshirilmoqda...
if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo ╔══════════════════════════════════════════════════════════╗
    echo ║  MUHIM: .env faylini to'ldiring!                        ║
    echo ║                                                          ║
    echo ║  1. .env faylini Notepad bilan oching                    ║
    echo ║  2. BOT_TOKEN — @BotFather dan oling                     ║
    echo ║  3. MANAGER_IDS — o'z Telegram ID'ingiz                  ║
    echo ║  4. TASKS_GROUP_ID — topshiriqlar guruhi ID'si           ║
    echo ║  5. EXECUTION_GROUP_ID — ijro guruhi ID'si               ║
    echo ║                                                          ║
    echo ║  AI uchun (BEPUL variant tavsiya etiladi):               ║
    echo ║  6. USE_OLLAMA=true deb yozing                           ║
    echo ║  7. Ollama yuklab o'rnating: https://ollama.ai           ║
    echo ║  8. Buyruq: ollama pull llama3                           ║
    echo ║                                                          ║
    echo ║  Userbot uchun (ixtiyoriy):                              ║
    echo ║  9. python generate_session.py ni ishga tushiring        ║
    echo ╚══════════════════════════════════════════════════════════╝
) else (
    echo     .env fayli allaqachon mavjud.
)

echo.
echo ═══════════════════════════════════════════════════
echo  O'rnatish tugadi!
echo  Keyingi qadam: .env faylini to'ldirib, start.bat bosing.
echo ═══════════════════════════════════════════════════
echo.
pause
