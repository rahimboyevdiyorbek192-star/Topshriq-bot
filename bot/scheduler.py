"""Muddat yaqinlashganda avtomatik eslatma (APScheduler) — guruh + userbot shaxsiy."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Config
from .database import Database
from .utils.deadline import format_deadline, humanize_left
from .utils.notify import send_and_clean

logger = logging.getLogger(__name__)


async def _check_deadlines(bot: Bot, db: Database, config: Config, userbot=None) -> None:
    if config.execution_group_id is None and not config.userbot_enabled:
        return
    now   = datetime.now(config.tz)
    tasks = await db.list_open_tasks()

    for task in tasks:
        if not task["deadline"]:
            continue
        try:
            dl = datetime.fromisoformat(task["deadline"])
        except ValueError:
            continue
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=config.tz)

        minutes_left = (dl - now).total_seconds() / 60

        if minutes_left <= 0:
            if not await db.was_reminder_sent(task["id"], 0):
                await _send_reminder(bot, db, config, task, overdue=True, userbot=userbot)
                await db.mark_reminder_sent(task["id"], 0)
            continue

        for m in config.reminder_minutes:
            if minutes_left <= m and not await db.was_reminder_sent(task["id"], m):
                await _send_reminder(bot, db, config, task, overdue=False, userbot=userbot)
                await db.mark_reminder_sent(task["id"], m)


async def _send_reminder(
    bot: Bot, db: Database, config: Config, task, overdue: bool,
    userbot=None,
) -> None:
    target_sector = task["target_sector"] if "target_sector" in task.keys() else None
    employees = await db.list_employees(sector=target_sector)
    submitted = await db.submitted_employee_ids(task["id"])
    not_done  = [e for e in employees if e["tg_id"] not in submitted]
    if not not_done:
        return

    head = "🔴 <b>MUDDAT O'TDI</b>" if overdue else "⏰ <b>MUDDAT YAQIN</b>"

    # Guruh eslatmasi
    if config.execution_group_ids:
        mentions = []
        for e in not_done:
            if e["username"]:
                mentions.append(f"@{e['username']}")
            elif e["tg_id"] > 0:
                mentions.append(
                    f'<a href="tg://user?id={e["tg_id"]}">{e["full_name"]}</a>'
                )
            else:
                mentions.append(e["full_name"])
        text = (
            f"{head} — Topshiriq #{task['id']}: {task['title']}\n"
            f"🗓 {format_deadline(task['deadline'], config.tz)} "
            f"{humanize_left(task['deadline'], config.tz)}\n\n"
            f"❗️ Hali bajarmaganlar ({len(not_done)} ta):\n"
            + ", ".join(mentions)
        )
        for gid in config.execution_group_ids:
            try:
                await bot.send_message(gid, text)
            except Exception as exc:
                logger.warning("Guruh eslatmasi yuborilmadi (task %s, chat %s): %s", task["id"], gid, exc)

    # Bot orqali shaxsiy eslatma (eski xabar o'chirilib yangi yuboriladi)
    head_private = "⏰ Salom! Topshiriq muddati yaqinlashdi." if not overdue else "🔴 Topshiriq muddati o'tib ketdi!"
    private_text = (
        f"{head_private}\n\n"
        f"📋 <b>#{task['id']}: {task['title']}</b>\n"
        f"🗓 Muddat: {format_deadline(task['deadline'], config.tz)}\n"
        f"{humanize_left(task['deadline'], config.tz)}\n\n"
        "Iltimos, ishingizni tezroq sayt orqali topshiring."
    )
    for e in not_done:
        if e["tg_id"] <= 0:
            continue
        await send_and_clean(bot, db, e["tg_id"], private_text)


async def _cleanup_sessions(db: Database) -> None:
    """Muddati o'tgan web sessiyalarni tozalaydi (jadval cheksiz o'smasligi uchun)."""
    try:
        await db.cleanup_sessions()
    except Exception as exc:
        logger.warning("Sessiyalarni tozalash xatosi: %s", exc)


def setup_scheduler(
    bot: Bot, db: Database, config: Config, userbot=None
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.timezone_name)
    scheduler.add_job(
        _check_deadlines,
        "interval",
        minutes=5,
        kwargs={"bot": bot, "db": db, "config": config, "userbot": userbot},
        id="deadline_check",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _cleanup_sessions,
        "interval",
        hours=12,
        kwargs={"db": db},
        id="session_cleanup",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
