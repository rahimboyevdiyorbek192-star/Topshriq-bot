@echo off
title Topshiriq Bot - Ishga tushirish

echo.
echo ===================================================
echo    TOPSHIRIQ BOTI - ISHGA TUSHIRISH
echo ===================================================
echo.

:: Virtual muhit tekshirish
if not exist "venv\Scripts\activate.bat" (
    echo [XATO] Virtual muhit topilmadi!
    echo Avval install.bat ni ishga tushiring.
    echo.
    pause
    exit /b 1
)

:: .env tekshirish
if not exist ".env" (
    echo [XATO] .env fayli topilmadi!
    echo install.bat ni ishga tushiring va .env ni to'ldiring.
    echo.
    pause
    exit /b 1
)

:: Botni ishga tushirish
call venv\Scripts\activate.bat

echo Bot ishga tushmoqda...
echo To'xtatish uchun: Ctrl+C
echo.
echo ---------------------------------------------------
echo.

python run.py

echo.
echo Bot to'xtatildi.
pause
