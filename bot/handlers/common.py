"""Umumiy komandalar: /start, /help, /id."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ..config import Config
from .buttons import main_menu_kb

router = Router()

HELP_MANAGER = """<b>🤖 Robot Mutaxassis — Rahbar uchun qo'llanma</b>

<b>📋 Topshiriq berish</b> (Topshiriqlar guruhiga/kanaliga):
Istalgan xabar yuboring — bot avtomatik topshiriq qiladi.
Muddat qo'shish: <code>Muddat: 07.08.2026 17:00</code> yozing.
Namuna (Excel/Word/PPT) biriktiring — xodimlar shu shablonni to'ldiradi.

<b>📊 Svodka va hisobotlar:</b>
/svodka — rasm + matn svodka
/svodka <code>N</code> — aniq topshiriq svodkasi
/excel — Excel fayl · /reyting — kim yaxshi ishlayapti
/topshiriqlar — ro'yxat · /yopish <code>N</code> — yopish
/eslatma <code>N</code> — qo'lda eslatma

<b>🤖 AI mutaxassis:</b>
/ai <code>savol</code> — AI bilan suhbat (analitika, maslahat)
/umumlashtir <code>N</code> — barcha xodim jadvallarini birlashtirib ZIP

<b>👥 Xodimlar:</b>
/hodimlar · /hodim_qoshish · /hodim_ochirish <code>ID</code>

/menu — tugmali menyu · /id — ID · /help — yordam"""

HELP_EMPLOYEE = """<b>🤖 Robot Mutaxassis — Xodim uchun</b>

<b>Topshiriqni qanday topshiraman?</b>

1️⃣ <b>Ijro guruhida</b>:
   • Topshiriq e'loniga <b>reply</b> qilib fayl yuboring
   • Yoki xabar boshida <code>#T3</code> yozing (3 = topshiriq raqami)

2️⃣ <b>Botga to'g'ridan-to'g'ri</b> (shaxsiy chat):
   • Shu botga fayl yuboring — topshiriq so'raladi

3️⃣ <b>Rahbarga yuborgan bo'lsangiz</b>:
   • Rahbar sizning faylingizni botga forward qiladi

Fayl formatlari: Excel (.xlsx), Word (.docx), PowerPoint (.pptx), PDF, rasm

<b>🤖 AI yordamchi:</b>
/ai <code>savol</code> — savolga javob (topshiriq, muddat, maslahat)

/mening — mening topshiriqlarim holati
/ruyxatdan_otish — ro'yxatga qo'shilish
/menu — tugmali menyu · /id — ID"""


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    text = HELP_MANAGER if is_mgr else HELP_EMPLOYEE
    await message.answer(text, reply_markup=main_menu_kb(is_mgr))


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    await message.answer(HELP_MANAGER if is_mgr else HELP_EMPLOYEE, reply_markup=main_menu_kb(is_mgr))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    user = message.from_user
    lines = [
        "<b>ℹ️ Ma'lumot</b>",
        f"Chat ID: <code>{message.chat.id}</code>",
        f"Chat turi: {message.chat.title or message.chat.type}",
    ]
    if user:
        lines.append(f"Sizning ID: <code>{user.id}</code>")
        if user.username:
            lines.append(f"Username: @{user.username}")
    await message.answer("\n".join(lines))
