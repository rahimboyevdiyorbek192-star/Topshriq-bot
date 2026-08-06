"""Ijro guruhida va shaxsiy xabarda xodimlar topshiriqlarini qabul qilish."""
from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ..config import Config
from ..database import Database
from ..utils.deadline import humanize_left
from ..utils.files import extract_file, message_text

router = Router()

_TASK_TAG = re.compile(r"#\s?[tTтТ]\s?(\d+)")


def _full_name(user) -> str:
    return (user.full_name or user.first_name or "Nomsiz").strip()


async def _resolve_task_id(message: Message, db: Database) -> int | None:
    if message.reply_to_message:
        task = await db.get_task_by_announce(message.reply_to_message.message_id)
        if task:
            return task["id"]
    m = _TASK_TAG.search(message_text(message))
    if m:
        task_id = int(m.group(1))
        task = await db.get_task(task_id)
        if task:
            return task_id
    return None


async def _record_submission(
    message: Message, task_id: int, db: Database
) -> None:
    """Topshiriqni DBga yozib tasdiqlaydi."""
    user = message.from_user
    if not user:
        return

    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, _full_name(user), user.username)

    info = extract_file(message)
    file_id   = info[0] if info else None
    file_name = info[1] if info else None
    note      = message_text(message)[:1000] or None

    is_new = await db.add_submission(
        task_id=task_id,
        employee_id=user.id,
        message_id=message.message_id,
        note=note,
        file_id=file_id,
        file_name=file_name,
    )

    submitted = await db.submitted_employee_ids(task_id)
    total     = await db.count_employees()
    verb      = "qabul qilindi" if is_new else "yangilandi"
    try:
        await message.reply(
            f"✅ #{task_id}-topshiriq bo'yicha ishingiz {verb}. "
            f"({len(submitted)}/{total})",
            disable_notification=True,
        )
    except Exception:
        pass


# ── /mening — o'z topshiriqlari holati ──────────────────────

@router.message(Command("mening", "my"))
async def cmd_my_tasks(message: Message, db: Database, config: Config) -> None:
    user = message.from_user
    if not user:
        return
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.reply("📭 Hozircha ochiq topshiriqlar yo'q.")
        return
    lines = ["📌 <b>Mening topshiriqlarim holati:</b>", ""]
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        mark = "✅ bajarilgan" if user.id in submitted else "❌ bajarilmagan"
        left = humanize_left(t["deadline"], config.tz)
        lines.append(f"<b>#{t['id']}</b> {t['title']} — {mark}\n   {left}")
    await message.reply("\n".join(lines))


# ── Guruh/kanal — ijro guruhida topshiriq qabul qilish ──────

@router.message(
    (F.chat.type.in_({"group", "supergroup"}))
    & ~F.from_user.is_bot
    & (F.text | F.caption | F.document | F.photo | F.video | F.audio | F.voice)
)
async def handle_group_submission(
    message: Message, db: Database, config: Config
) -> None:
    if config.execution_group_id is not None:
        if message.chat.id != config.execution_group_id:
            return
    else:
        if config.tasks_group_id and message.chat.id == config.tasks_group_id:
            return
        if config.tasks_channel_id and message.chat.id == config.tasks_channel_id:
            return

    task_id = await _resolve_task_id(message, db)
    if task_id is None:
        return

    await _record_submission(message, task_id, db)


# ── Shaxsiy xabar (DM) — xodim botga to'g'ridan-to'g'ri tashlaydi ──

@router.message(
    F.chat.type == "private"
    & ~F.from_user.is_bot
    & (F.text | F.caption | F.document | F.photo | F.video | F.audio | F.voice)
)
async def handle_private_submission(
    message: Message, db: Database, config: Config, bot: Bot
) -> None:
    user = message.from_user
    if not user:
        return
    if config.is_manager(user.id):
        return  # Rahbar komandalar ishlatadi

    text = message_text(message)

    # Topshiriq raqami ko'rsatilganmi?
    task_id = await _resolve_task_id(message, db)
    if task_id:
        await _record_submission(message, task_id, db)
        return

    # Ochiq topshiriqlarni ko'rsatib, tanlash so'rash
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.reply(
            "📭 Hozircha ochiq topshiriqlar yo'q.\n"
            "Qaysi topshiriq uchun yuboryapsiz? Raqamini #T1 ko'rinishida yozing."
        )
        return

    if len(tasks) == 1:
        # Bitta topshiriq — avtomatik
        await _record_submission(message, tasks[0]["id"], db)
        return

    # Tugmalar bilan tanlash
    rows = []
    for t in tasks[:10]:
        rows.append([
            InlineKeyboardButton(
                text=f"#{t['id']} {t['title'][:35]}",
                callback_data=f"dm_submit:{t['id']}",
            )
        ])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await message.reply(
        "📋 Qaysi topshiriq uchun yuborayapsiz?",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("dm_submit:"))
async def cb_dm_submit(
    callback: CallbackQuery, db: Database, config: Config
) -> None:
    task_id = int(callback.data.split(":")[1])
    msg = callback.message

    user = callback.from_user
    if not user:
        await callback.answer()
        return

    # Foydalanuvchi callback bosganidan keyin asl xabarni topamiz
    # (callback.message — bizning javobimiz, asl xabar u emas)
    # Shuning uchun pending submission ni saqlash uchun oddiy yo'l:
    # Bo'sh submission yozib, faqat employee_id va task_id ni bog'laymiz

    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, user.full_name or "Nomsiz", user.username)

    is_new = await db.add_submission(
        task_id=task_id,
        employee_id=user.id,
        message_id=None,
        note="Shaxsiy xabar orqali topshirildi",
        file_id=None,
        file_name=None,
    )

    submitted = await db.submitted_employee_ids(task_id)
    total     = await db.count_employees()
    verb      = "qabul qilindi" if is_new else "yangilandi"

    await callback.message.edit_text(
        f"✅ #{task_id}-topshiriq bo'yicha ishingiz {verb}. "
        f"({len(submitted)}/{total})\n\n"
        "Fayl bilan qayta yuboring — <code>#T"
        + str(task_id)
        + "</code> deb boshlab, fayl biriktiring.",
    )
    await callback.answer()


# ── Rahbarga kelgan forward → topshiriq sifatida qabul ────────────

@router.message(
    F.chat.type == "private"
    & F.forward_origin.IS_NOT_NONE
)
async def handle_forward_from_manager(
    message: Message, db: Database, config: Config
) -> None:
    """Rahbar private chatida boshqadan forward qilingan xabarni qayta ishlaydi."""
    user = message.from_user
    if not user or not config.is_manager(user.id):
        return

    # Originalning egasini aniqlash
    origin = message.forward_origin
    if not origin or not hasattr(origin, "sender_user") or not origin.sender_user:
        return
    sender = origin.sender_user
    if sender.is_bot:
        return

    # Ochiq topshiriqlardan mosini topamiz
    task_id = await _resolve_task_id(message, db)
    if task_id is None:
        tasks = await db.list_open_tasks()
        if len(tasks) == 1:
            task_id = tasks[0]["id"]
        else:
            await message.reply(
                "ℹ️ Qaysi topshiriq uchun? "
                f"Javob xabarida <code>#T[raqam]</code> yozing."
            )
            return

    emp = await db.get_employee(sender.id)
    if not emp:
        full_name = (sender.full_name or sender.first_name or "Nomsiz").strip()
        await db.add_employee(sender.id, full_name, sender.username)

    info      = extract_file(message)
    file_id   = info[0] if info else None
    file_name = info[1] if info else None
    note      = message_text(message)[:1000] or "Rahbar orqali qabul qilindi"

    is_new = await db.add_submission(
        task_id=task_id,
        employee_id=sender.id,
        message_id=message.message_id,
        note=note,
        file_id=file_id,
        file_name=file_name,
    )
    emp_name = (sender.full_name or "Xodim")
    verb = "qabul qilindi" if is_new else "yangilandi"
    await message.reply(
        f"✅ {emp_name} uchun #{task_id}-topshiriq {verb}."
    )
