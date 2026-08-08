@echo off
title Topshiriq Bot - O'rnatish

echo.
echo ===================================================
echo    TOPSHIRIQ BOTI - O'RNATISH
echo ===================================================
echo.

:: Python tekshirish
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [XATO] Python topilmadi!
    echo.
    echo Python 3.11+ ni yuklab o'rnating:
    echo https://www.python.org/downloads/
    echo.
    echo O'rnatayotganda "Add Python to PATH" ni belgilang!
    echo.
    pause
    exit /b 1
)

echo [1/4] Python topildi:
python --version
echo.

:: Virtual muhit
echo [2/4] Virtual muhit yaratilmoqda...
if not exist "venv" (
    python -m venv venv
    echo     Yaratildi.
) else (
    echo     Allaqachon mavjud.
)
echo.

:: Kutubxonalar
echo [3/4] Kutubxonalar o'rnatilmoqda...
call venv\Scripts\activate.bat
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\python.exe -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo.
    echo [XATO] O'rnatishda muammo chiqdi. Yuqoridagi xatoni rasmga olib yuboring.
    pause
    exit /b 1
)
echo     Barcha kutubxonalar o'rnatildi.
echo.

:: .env fayl
echo [4/4] Sozlamalar fayli tekshirilmoqda...
if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo ===================================================
    echo  MUHIM: .env faylini Notepad bilan oching va
    echo  quyidagilarni to'ldiring:
    echo.
    echo  BOT_TOKEN        - @BotFather dan oling
    echo  MANAGER_IDS      - o'z Telegram ID'ingiz
    echo  TASKS_GROUP_ID   - topshiriqlar guruhi ID
    echo  EXECUTION_GROUP_ID - ijro guruhi ID
    echo.
    echo  AI uchun (bepul):
    echo  USE_OLLAMA=true
    echo  ollama.ai dan Ollama yuklab o'rnating
    echo  Keyin: ollama pull llava
    echo ===================================================
) else (
    echo     .env fayli allaqachon mavjud.
)

echo.
echo ===================================================
echo  O'rnatish tugadi!
echo  Keyingi qadam: .env ni to'ldirib, start.bat bosing.
echo ===================================================
echo.
pause
