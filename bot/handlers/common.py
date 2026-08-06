"""Umumiy komandalar: /start, /help, /id."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ..config import Config
from .buttons import main_menu_kb

router = Router()

HELP_MANAGER = """<b>🤖 Topshiriqlar boti — Rahbar uchun qo'llanma</b>

<b>Topshiriq yaratish</b> (Topshiriqlar guruhida):
Xabarni <code>#topshiriq</code> bilan boshlang. Namuna:
<code>#topshiriq
Oylik hisobot tayyorlash
Muddat: 07.08.2026 17:00
Har bir bo'lim bo'yicha hisobot kerak</code>
Word/Excel/PowerPoint namunalarini shu xabarga biriktiring.

<b>Svodka va hisobotlar:</b>
/svodka — umumiy holat · /svodka <code>N</code> — aniq topshiriq
/excel — Excel fayl · /topshiriqlar — ro'yxat
/yopish <code>N</code> — yopish · /eslatma <code>N</code> — eslatma

<b>AI mutaxassis:</b>
/ai <code>savol</code> — sun'iy intellekt bilan suhbat
/umumlashtir <code>N</code> — hisobotlarni umumlashtirish

<b>Xodimlar:</b>
/hodimlar · /hodim_qoshish · /hodim_ochirish <code>ID</code>

/menu — tugmali menyu · /id — ID · /help — yordam"""

HELP_EMPLOYEE = """<b>🤖 Topshiriqlar boti — Xodim uchun</b>

Topshiriqni bajarganingizda <b>Ijro guruhiga</b> tashlang:
• Botning topshiriq e'loniga <b>reply</b> qiling, yoki
• Xabaringiz boshida topshiriq raqamini yozing: <code>#T3</code>

Ishingizni (fayl, rasm yoki matn) shu tarzda yuborsangiz,
bot avtomatik qabul qiladi va rahbarga hisobga oladi.

<b>AI mutaxassis:</b>
/ai <code>savol</code> — sun'iy intellekt bilan suhbat

/mening — o'z topshiriqlarim holati
/ruyxatdan_otish — xodimlar ro'yxatiga qo'shilish
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
