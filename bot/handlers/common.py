"""Umumiy komandalar: /start, /help, /id."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ..config import Config

router = Router()

HELP_MANAGER = """<b>🤖 Topshiriqlar boti — Rahbar uchun qo'llanma</b>

<b>Topshiriq yaratish</b> (Topshiriqlar guruhida):
Xabarni <code>#topshiriq</code> bilan boshlang. Namuna:
<code>#topshiriq
Oylik hisobot tayyorlash
Muddat: 07.08.2026 17:00
Har bir bo'lim bo'yicha hisobot kerak</code>
Word/Excel/PowerPoint namunalarini shu xabarga biriktiring (albom bo'lsa ham bo'ladi).

<b>Svodka va hisobotlar:</b>
/svodka — barcha ochiq topshiriqlar bo'yicha umumiy holat
/svodka <code>N</code> — N-topshiriq bo'yicha kim bajardi/bajarmadi
/excel — svodkani Excel fayl ko'rinishida yuklab olish
/topshiriqlar — ochiq topshiriqlar ro'yxati
/yopish <code>N</code> — N-topshiriqni yopish
/eslatma <code>N</code> — bajarmaganlarga eslatma yuborish

<b>Xodimlar:</b>
/hodimlar — xodimlar ro'yxati
/hodim_qoshish — (xodim xabariga reply qilib) qo'shish
/hodim_ochirish <code>ID</code> — ro'yxatdan chiqarish

<b>Boshqa:</b>
/id — chat va foydalanuvchi ID'sini ko'rsatadi
/help — shu qo'llanma"""

HELP_EMPLOYEE = """<b>🤖 Topshiriqlar boti — Xodim uchun</b>

Topshiriqni bajarganingizda <b>Ijro guruhiga</b> tashlang:
• Botning topshiriq e'loniga <b>reply</b> qiling, yoki
• Xabaringiz boshida topshiriq raqamini yozing: <code>#T3</code>

Ishingizni (fayl, rasm yoki matn) shu tarzda yuborsangiz,
bot avtomatik qabul qiladi va rahbarga hisobga oladi.

/mening — o'z topshiriqlarim holati
/ruyxatdan_otish — o'zingizni xodimlar ro'yxatiga qo'shish
/id — ID'ni ko'rsatadi"""


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config) -> None:
    is_mgr = message.from_user and config.is_manager(message.from_user.id)
    text = HELP_MANAGER if is_mgr else HELP_EMPLOYEE
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    is_mgr = message.from_user and config.is_manager(message.from_user.id)
    await message.answer(HELP_MANAGER if is_mgr else HELP_EMPLOYEE)


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
