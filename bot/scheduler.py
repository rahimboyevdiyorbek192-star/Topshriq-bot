"""Muddat yaqinlashganda avtomatik eslatma yuborish (APScheduler)."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Config
from .database import Database
from .utils.deadline import format_deadline, humanize_left

logger = logging.getLogger(__name__)


async def _check_deadlines(bot: Bot, db: Database, config: Config) -> None:
    if config.execution_group_id is None or not config.reminder_minutes:
        return
    now = datetime.now(config.tz)
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

        # Muddat o'tib ketgan bo'lsa — bir marta "kechikdi" eslatmasi (minutes=0)
        if minutes_left <= 0:
            if not await db.was_reminder_sent(task["id"], 0):
                await _send_reminder(bot, db, config, task, overdue=True)
                await db.mark_reminder_sent(task["id"], 0)
            continue

        for m in config.reminder_minutes:
            # m daqiqadan kam qoldi, lekin hali eslatilmagan
            if minutes_left <= m and not await db.was_reminder_sent(task["id"], m):
                await _send_reminder(bot, db, config, task, overdue=False)
                await db.mark_reminder_sent(task["id"], m)
                break


async def _send_reminder(
    bot: Bot, db: Database, config: Config, task, overdue: bool
) -> None:
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task["id"])
    not_done = [e for e in employees if e["tg_id"] not in submitted]
    if not not_done:
        return

    mentions = []
    for e in not_done:
        if e["username"]:
            mentions.append(f"@{e['username']}")
        else:
            mentions.append(f'<a href="tg://user?id={e["tg_id"]}">{e["full_name"]}</a>')

    head = "🔴 <b>MUDDAT O'TDI</b>" if overdue else "⏰ <b>MUDDAT YAQIN</b>"
    text = (
        f"{head} — Topshiriq #{task['id']}: {task['title']}\n"
        f"🗓 {format_deadline(task['deadline'], config.tz)} "
        f"{humanize_left(task['deadline'], config.tz)}\n\n"
        f"❗️ Hali bajarmaganlar ({len(not_done)} ta):\n"
        + ", ".join(mentions)
    )
    try:
        await bot.send_message(config.execution_group_id, text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Eslatma yuborilmadi (task %s): %s", task["id"], exc)


def setup_scheduler(bot: Bot, db: Database, config: Config) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.timezone_name)
    scheduler.add_job(
        _check_deadlines,
        "interval",
        minutes=5,
        args=(bot, db, config),
        id="deadline_check",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
