"""Ijro guruhida xodimlar yuborgan bajarilgan ishlarni qabul qilish."""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Config
from ..database import Database
from ..utils.deadline import humanize_left
from ..utils.files import extract_file, message_text

router = Router()

_TASK_TAG = re.compile(r"#\s?[tTтТ]\s?(\d+)")


def _full_name(user) -> str:
    return (user.full_name or user.first_name or "Nomsiz").strip()


async def _resolve_task_id(message: Message, db: Database) -> int | None:
    # 1) Reply — botning e'lon xabariga javob
    if message.reply_to_message:
        task = await db.get_task_by_announce(message.reply_to_message.message_id)
        if task:
            return task["id"]
    # 2) #T<raqam> belgisi
    m = _TASK_TAG.search(message_text(message))
    if m:
        task_id = int(m.group(1))
        task = await db.get_task(task_id)
        if task:
            return task_id
    return None


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


@router.message(
    (F.chat.type.in_({"group", "supergroup"}))
    & ~F.from_user.is_bot
    & (F.text | F.caption | F.document | F.photo | F.video | F.audio | F.voice)
)
async def handle_submission(message: Message, db: Database, config: Config) -> None:
    # Faqat ijro guruhida ishlaydi
    if config.execution_group_id is not None:
        if message.chat.id != config.execution_group_id:
            return
    else:
        # Ijro guruhi sozlanmagan — topshiriqlar guruhida bo'lmasin
        if config.tasks_group_id is not None and message.chat.id == config.tasks_group_id:
            return

    task_id = await _resolve_task_id(message, db)
    if task_id is None:
        return  # Bog'lanadigan topshiriq yo'q — jimgina o'tkazamiz

    user = message.from_user
    if not user:
        return

    # Xodimni avtomatik ro'yxatga qo'shamiz (ijro guruhida ish tashlagan bo'lsa)
    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, _full_name(user), user.username)

    info = extract_file(message)
    file_id = info[0] if info else None
    file_name = info[1] if info else None
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
    total = await db.count_employees()
    verb = "qabul qilindi" if is_new else "yangilandi"
    try:
        await message.reply(
            f"✅ #{task_id}-topshiriq bo'yicha ishingiz {verb}. "
            f"({len(submitted)}/{total})",
            disable_notification=True,
        )
    except Exception:
        pass
