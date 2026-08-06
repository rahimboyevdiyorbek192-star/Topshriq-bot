"""Xodimlarni boshqarish komandalar."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..config import Config
from ..database import Database

router = Router()


def _full_name(user) -> str:
    name = user.full_name or user.first_name or "Nomsiz"
    return name.strip()


@router.message(Command("ruyxatdan_otish", "register"))
async def cmd_self_register(message: Message, db: Database) -> None:
    """Xodim o'zini ro'yxatga qo'shadi."""
    user = message.from_user
    if not user:
        return
    await db.add_employee(user.id, _full_name(user), user.username)
    await message.reply(
        f"✅ Ro'yxatdan o'tdingiz: <b>{_full_name(user)}</b>.\n"
        f"Endi topshiriqlaringizni ijro guruhiga tashlashingiz mumkin."
    )


@router.message(Command("hodim_qoshish", "add_employee"))
async def cmd_add_employee(message: Message, db: Database, config: Config) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    target = message.reply_to_message
    if not target or not target.from_user:
        await message.reply(
            "ℹ️ Xodimni qo'shish uchun uning istalgan xabariga <b>reply</b> qilib "
            "<code>/hodim_qoshish</code> yozing."
        )
        return
    user = target.from_user
    if user.is_bot:
        await message.reply("⚠️ Botni xodim sifatida qo'shib bo'lmaydi.")
        return
    await db.add_employee(user.id, _full_name(user), user.username)
    total = await db.count_employees()
    await message.reply(
        f"✅ Xodim qo'shildi: <b>{_full_name(user)}</b>\n"
        f"👥 Jami xodimlar: {total}"
    )


@router.message(Command("hodim_ochirish", "remove_employee"))
async def cmd_remove_employee(
    message: Message, command: CommandObject, db: Database, config: Config
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    tg_id: int | None = None
    if command.args and command.args.strip().lstrip("-").isdigit():
        tg_id = int(command.args.strip())
    elif message.reply_to_message and message.reply_to_message.from_user:
        tg_id = message.reply_to_message.from_user.id
    if tg_id is None:
        await message.reply(
            "ℹ️ Foydalanish: <code>/hodim_ochirish ID</code> yoki xodim xabariga reply qiling."
        )
        return
    ok = await db.remove_employee(tg_id)
    await message.reply(
        "✅ Xodim ro'yxatdan chiqarildi." if ok else "⚠️ Bunday xodim topilmadi."
    )


@router.message(Command("hodimlar", "employees"))
async def cmd_list_employees(message: Message, db: Database, config: Config) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    employees = await db.list_employees()
    if not employees:
        await message.reply(
            "👥 Xodimlar ro'yxati bo'sh.\n\n"
            "Qo'shish uchun: xodim guruhda xabar yozganida uning xabariga reply qilib "
            "<code>/hodim_qoshish</code> yuboring, yoki xodimlar <code>/ruyxatdan_otish</code> yozsin."
        )
        return
    lines = [f"👥 <b>Xodimlar ({len(employees)} ta):</b>", ""]
    for i, e in enumerate(employees, 1):
        uname = f" (@{e['username']})" if e["username"] else ""
        lines.append(f"{i}. {e['full_name']}{uname} — <code>{e['tg_id']}</code>")
    await message.reply("\n".join(lines))
