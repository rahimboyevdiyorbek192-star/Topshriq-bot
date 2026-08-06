"""Topshiriqlarni qabul qilish: guruh, shaxsiy xabar, forward.

Muammolar va yechimlar:
  • DM fayl yo'qolishi: _pending_dm dict orqali fayl saqlanadi, tugma bosilganda qo'llaniladi.
  • Auto-register: ijro guruhida xabar yozgan har kim ro'yxatga tushadi.
  • Re-submission: xodim qayta yuborsa — eng yangi fayl saqlanadi.
"""
from __future__ import annotations

import re
from typing import Any

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

# DM topshirish: fayl kutilmoqda
# {user_id: {"file_id": ..., "file_name": ..., "note": ..., "msg_id": ...}}
_pending_dm: dict[int, dict] = {}


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
        task    = await db.get_task(task_id)
        if task:
            return task_id
    return None


async def _record_submission(
    message: Message,
    task_id: int,
    db: Database,
    file_id: str | None = None,
    file_name: str | None = None,
    note: str | None = None,
) -> None:
    """Topshirishni DBga yozib, tasdiq xabari yuboradi."""
    user = message.from_user
    if not user:
        return

    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, _full_name(user), user.username)

    if file_id is None:
        info      = extract_file(message)
        file_id   = info[0] if info else None
        file_name = info[1] if info else None
    if note is None:
        note = message_text(message)[:1000] or None

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
            f"✅ <b>#{task_id}-topshiriq</b> bo'yicha ishingiz {verb}.\n"
            f"({len(submitted)}/{total} xodim topshirdi)",
            disable_notification=True,
        )
    except Exception:
        pass


# ── /mening — o'z topshiriqlari holati ──────────────────────

@router.message(Command("mening", "my"))
async def cmd_my_tasks(
    message: Message, db: Database, config: Config
) -> None:
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


# ── GURUH: ijro guruhida topshiriq qabul qilish ──────────────

@router.message(
    (F.chat.type.in_({"group", "supergroup"}))
    & ~F.from_user.is_bot
    & (F.text | F.caption | F.document | F.photo | F.video | F.audio | F.voice)
)
async def handle_group_submission(
    message: Message, db: Database, config: Config
) -> None:
    # Faqat ijro guruhida ishlaydi
    if config.execution_group_id is not None:
        if message.chat.id != config.execution_group_id:
            return
    else:
        # Ijro guruhi sozlanmagan — topshiriqlar/kanal guruhida ham ishlashini oldini olish
        if config.tasks_group_id and message.chat.id == config.tasks_group_id:
            return
        if config.tasks_channel_id and message.chat.id == config.tasks_channel_id:
            return

    user = message.from_user
    if not user:
        return

    # Auto-register: ijro guruhida xabar yozgan har kim xodim sifatida qo'shiladi
    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, _full_name(user), user.username)

    task_id = await _resolve_task_id(message, db)
    if task_id is None:
        return

    await _record_submission(message, task_id, db)


# ── DM: xodim botga shaxsiy xabar yuboradi ───────────────────

@router.message(
    (F.chat.type == "private")
    & ~F.from_user.is_bot
    & (F.document | F.photo | F.video | F.audio | F.voice | F.caption | F.text)
)
async def handle_private_submission(
    message: Message, db: Database, config: Config, bot: Bot, ai: Any = None
) -> None:
    user = message.from_user
    if not user:
        return
    if config.is_manager(user.id):
        return  # Rahbar komandalar ishlatadi

    text = message_text(message)

    # Bot komandasi bo'lsa o'tkazib yuboramiz (boshqa handler ushlab qolgan bo'ladi)
    if text.startswith("/"):
        return

    # Topshiriq raqami ko'rsatilganmi? (#T3 yoki reply)
    task_id = await _resolve_task_id(message, db)
    if task_id:
        await _record_submission(message, task_id, db)
        _pending_dm.pop(user.id, None)
        return

    # Faylni pending ga saqlash
    info = extract_file(message)
    _pending_dm[user.id] = {
        "file_id":   info[0] if info else None,
        "file_name": info[1] if info else None,
        "note":      text[:1000] or None,
        "msg_id":    message.message_id,
    }

    # Ochiq topshiriqlarni ko'rsatib tanlash so'raymiz
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.reply(
            "📭 Hozircha ochiq topshiriqlar yo'q.\n"
            "Topshiriq raqamini #T1 ko'rinishida yozing."
        )
        return

    if len(tasks) == 1:
        # Bitta topshiriq — avtomatik bog'laymiz
        await _record_submission(
            message, tasks[0]["id"], db,
            file_id=_pending_dm[user.id]["file_id"],
            file_name=_pending_dm[user.id]["file_name"],
            note=_pending_dm[user.id]["note"],
        )
        _pending_dm.pop(user.id, None)
        return

    # Tugmalar bilan tanlash
    rows = [
        [InlineKeyboardButton(
            text=f"#{t['id']} {t['title'][:38]}",
            callback_data=f"dm_submit:{t['id']}",
        )]
        for t in tasks[:10]
    ]
    await message.reply(
        "📋 <b>Qaysi topshiriq uchun?</b>\n"
        "Faylingiz saqlanib turibdi — topshiriqni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("dm_submit:"))
async def cb_dm_submit(
    callback: CallbackQuery, db: Database
) -> None:
    task_id = int(callback.data.split(":")[1])
    user    = callback.from_user

    # Pending faylni olamiz
    pending   = _pending_dm.pop(user.id, {})
    file_id   = pending.get("file_id")
    file_name = pending.get("file_name")
    note      = pending.get("note") or "DM orqali topshirildi"

    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, _full_name(user), user.username)

    is_new = await db.add_submission(
        task_id=task_id,
        employee_id=user.id,
        message_id=pending.get("msg_id"),
        note=note,
        file_id=file_id,
        file_name=file_name,
    )

    submitted = await db.submitted_employee_ids(task_id)
    total     = await db.count_employees()
    verb      = "qabul qilindi" if is_new else "yangilandi"

    file_info = f"📎 Fayl: {file_name}" if file_name else ("📸 Rasm" if file_id else "📝 Matn")
    extra = (
        f"\n\n{file_info}\n"
        "Boshqa fayl yubormoqchi bo'lsangiz — "
        f"<code>#T{task_id}</code> deb boshlab yuboring."
        if not file_id
        else f"\n\n{file_info}"
    )

    await callback.message.edit_text(
        f"✅ <b>#{task_id}-topshiriq</b> bo'yicha ishingiz {verb}.\n"
        f"({len(submitted)}/{total} xodim topshirdi){extra}"
    )
    await callback.answer()


# ── FORWARD: rahbar xodim faylini botga forward qiladi ───────

@router.message(
    (F.chat.type == "private")
    & F.forward_origin.IS_NOT_NONE
)
async def handle_forward_from_manager(
    message: Message, db: Database, config: Config
) -> None:
    user = message.from_user
    if not user or not config.is_manager(user.id):
        return

    origin = message.forward_origin
    if not origin or not hasattr(origin, "sender_user") or not origin.sender_user:
        return
    sender = origin.sender_user
    if sender.is_bot:
        return

    task_id = await _resolve_task_id(message, db)
    if task_id is None:
        tasks = await db.list_open_tasks()
        if len(tasks) == 1:
            task_id = tasks[0]["id"]
        else:
            ids_str = ", ".join(f"#{t['id']}" for t in tasks[:5])
            await message.reply(
                f"ℹ️ Qaysi topshiriq uchun?\n"
                f"Ochiq topshiriqlar: {ids_str}\n"
                f"Javob xabarida <code>#T[raqam]</code> yozing."
            )
            return

    emp = await db.get_employee(sender.id)
    if not emp:
        full_name = _full_name(sender)
        await db.add_employee(sender.id, full_name, sender.username)

    info      = extract_file(message)
    file_id   = info[0] if info else None
    file_name = info[1] if info else None
    note      = message_text(message)[:1000] or "Rahbar orqali qabul qilindi"

    is_new   = await db.add_submission(
        task_id=task_id, employee_id=sender.id,
        message_id=message.message_id,
        note=note, file_id=file_id, file_name=file_name,
    )
    emp_name = sender.full_name or "Xodim"
    verb     = "qabul qilindi" if is_new else "yangilandi"
    await message.reply(
        f"✅ <b>{emp_name}</b> uchun #{task_id}-topshiriq {verb}."
    )
