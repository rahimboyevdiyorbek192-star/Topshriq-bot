@echo off
chcp 65001 >nul
title Topshiriq Bot - Ishga tushirish

echo ╔══════════════════════════════════════════╗
echo ║   TOPSHIRIQ BOTI - ISHGA TUSHIRISH      ║
echo ╚══════════════════════════════════════════╝
echo.

:: Virtual muhit mavjudligini tekshirish
if not exist "venv\Scripts\activate.bat" (
    echo [XATO] Virtual muhit topilmadi!
    echo Avval install.bat ni ishga tushiring.
    echo.
    pause
    exit /b 1
)

:: .env mavjudligini tekshirish
if not exist ".env" (
    echo [XATO] .env fayli topilmadi!
    echo Avval install.bat ni ishga tushiring va .env ni to'ldiring.
    echo.
    pause
    exit /b 1
)

:: Virtual muhitni faollashtirish va botni ishga tushirish
call venv\Scripts\activate.bat

echo Bot ishga tushmoqda...
echo To'xtatish uchun: Ctrl+C
echo.
echo ─────────────────────────────────────────
echo.

python run.py

echo.
echo Bot to'xtatildi.
pause
