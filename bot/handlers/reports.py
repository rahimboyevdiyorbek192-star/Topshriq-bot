"""Svodka va hisobotlar: /svodka, /excel, /eslatma."""
from __future__ import annotations

from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from ..config import Config
from ..database import Database
from ..utils.deadline import format_deadline, humanize_left
from ..utils.report import (
    build_excel_report,
    build_overall_text_report,
    build_task_text_report,
)

router = Router()


@router.message(Command("svodka", "svod", "report"))
async def cmd_svodka(
    message: Message, command: CommandObject, db: Database, config: Config
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Svodka faqat rahbar uchun.")
        return
    employees = await db.list_employees()

    # Aniq topshiriq bo'yicha
    if command.args and command.args.strip().isdigit():
        task_id = int(command.args.strip())
        task = await db.get_task(task_id)
        if not task:
            await message.reply("⚠️ Bunday topshiriq topilmadi.")
            return
        submitted = await db.submitted_employee_ids(task_id)
        text = build_task_text_report(task, employees, submitted, config.tz)
        await message.reply(text)
        return

    # Umumiy svodka
    tasks = await db.list_open_tasks()
    rows = []
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        rows.append((t, submitted))
    text = build_overall_text_report(rows, employees, config.tz)
    text += "\n\n📄 Excel svodka: /excel"
    await message.reply(text)


@router.message(Command("excel", "xls"))
async def cmd_excel(
    message: Message, command: CommandObject, db: Database, config: Config, bot: Bot
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    employees = await db.list_employees()
    if not employees:
        await message.reply("👥 Avval xodimlar ro'yxatini to'ldiring.")
        return

    # Argument: 'hammasi' bo'lsa yopilganlar ham, aks holda faqat ochiqlar
    include_closed = bool(command.args and "hamma" in command.args.lower())
    if include_closed:
        cur = await db.conn.execute("SELECT * FROM tasks ORDER BY id")
        tasks = list(await cur.fetchall())
    else:
        tasks = sorted(await db.list_open_tasks(), key=lambda t: t["id"])

    if not tasks:
        await message.reply("📭 Hisobot uchun topshiriqlar yo'q.")
        return

    rows = []
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        subs = {s["employee_id"]: s for s in await db.get_submissions(t["id"])}
        rows.append((t, submitted, subs))

    data = build_excel_report(rows, employees, config.tz)
    fname = f"svodka_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.xlsx"
    await bot.send_document(
        message.chat.id,
        BufferedInputFile(data, filename=fname),
        caption=f"📄 Svodka — {len(tasks)} topshiriq, {len(employees)} xodim.",
    )


@router.message(Command("eslatma", "remind"))
async def cmd_remind(
    message: Message, command: CommandObject, db: Database, config: Config, bot: Bot
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    if not (command.args and command.args.strip().isdigit()):
        await message.reply("ℹ️ Foydalanish: <code>/eslatma N</code> (N — topshiriq raqami)")
        return
    task_id = int(command.args.strip())
    task = await db.get_task(task_id)
    if not task:
        await message.reply("⚠️ Bunday topshiriq topilmadi.")
        return
    if config.execution_group_id is None:
        await message.reply("⚠️ Ijro guruhi (EXECUTION_GROUP_ID) sozlanmagan.")
        return

    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    not_done = [e for e in employees if e["tg_id"] not in submitted]
    if not not_done:
        await message.reply(f"🎉 #{task_id}-topshiriqni hamma bajargan!")
        return

    mentions = []
    for e in not_done:
        if e["username"]:
            mentions.append(f"@{e['username']}")
        else:
            mentions.append(f'<a href="tg://user?id={e["tg_id"]}">{e["full_name"]}</a>')

    text = (
        f"⏰ <b>ESLATMA — Topshiriq #{task_id}: {task['title']}</b>\n"
        f"🗓 Muddat: {format_deadline(task['deadline'], config.tz)} "
        f"{humanize_left(task['deadline'], config.tz)}\n\n"
        f"❗️ Quyidagilar hali bajarmagan ({len(not_done)} ta):\n"
        + ", ".join(mentions)
    )
    await bot.send_message(config.execution_group_id, text)
    await message.reply(f"✅ Eslatma yuborildi ({len(not_done)} xodimga).")
