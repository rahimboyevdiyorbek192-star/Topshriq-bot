"""Umumiy komandalar: /start, /help, /id."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from ..config import Config
from .buttons import main_reply_kb

router = Router()

HELP_MANAGER = """\
<b>🤖 Robot Mutaxassis — Rahbar uchun</b>

<b>📋 Topshiriq berish</b>
Topshiriqlar guruhiga istalgan xabar yuboring — bot avtomatik qabul qiladi.
Muddat: <code>Muddat: 10.08.2026 18:00</code>
Shablon: Excel/Word/PPT faylni biriktiring.

<b>Pastdagi tugmalar orqali:</b>
📋 <b>Topshiriqlar</b> — barcha ochiq topshiriqlar
📊 <b>Svodka</b> — rasm + matn holat hisoboti
📈 <b>Reyting</b> — xodimlar samaradorligi
📄 <b>Excel</b> — to'liq hisobot fayli
🤖 <b>AI Suhbat</b> — AI bilan tahlil va maslahat
👥 <b>Xodimlar</b> — ro'yxat, qo'shish, o'chirish

<b>Komandalar:</b>
/svodka · /excel · /reyting · /eslatma N
/ai savol · /umumlashtir N"""

HELP_EMPLOYEE = """\
<b>🤖 Robot Mutaxassis — Xodim uchun</b>

<b>Topshiriqni qanday topshiraman?</b>

1️⃣ <b>Ijro guruhida</b> — topshiriq xabariga <b>reply</b> qilib fayl yuboring
2️⃣ <b>Botga to'g'ridan-to'g'ri</b> — shu botga fayl yuboring, topshiriq so'raladi
3️⃣ <b>#T3 bilan</b> — xabar boshida raqam yozing: <code>#T3 fayl</code>

Fayl turlari: Excel, Word, PPT, PDF, rasm (jadval surati)

<b>Pastdagi tugmalar:</b>
📌 <b>Ishlarim</b> — mening topshiriqlarim holati
📋 <b>Topshiriqlar</b> — barcha ochiq topshiriqlar
🤖 <b>AI Yordam</b> — savolga javob

<b>Komandalar:</b>
/mening · /ruyxatdan_otish · /ai savol"""


def _webapp_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Mini App ochish", web_app=WebAppInfo(url=url))
    ]])


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    name   = (message.from_user.first_name or "Xush kelibsiz") if message.from_user else "Xush kelibsiz"
    role   = "rahbar" if is_mgr else "xodim"

    await message.answer(
        f"👋 Salom, <b>{name}</b>!\n\n"
        f"🤖 <b>Robot Mutaxassis</b> — topshiriqlar boshqaruv tizimiga xush kelibsiz.\n"
        f"Siz <b>{role}</b> sifatida kirgansiz.\n\n"
        "Quyidagi tugmalardan foydalaning 👇",
        reply_markup=main_reply_kb(is_mgr, config.webapp_url),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    await message.answer(
        HELP_MANAGER if is_mgr else HELP_EMPLOYEE,
        reply_markup=main_reply_kb(is_mgr, config.webapp_url),
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    user  = message.from_user
    lines = [
        "<b>ℹ️ ID Ma'lumot</b>",
        f"Chat ID: <code>{message.chat.id}</code>",
        f"Chat turi: {message.chat.title or message.chat.type}",
    ]
    if user:
        lines.append(f"Sizning ID: <code>{user.id}</code>")
        if user.username:
            lines.append(f"Username: @{user.username}")
    await message.answer("\n".join(lines))
