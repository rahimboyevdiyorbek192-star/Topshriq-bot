"""Svodka va hisobotlar: /svodka, /excel, /eslatma, /reyting."""
from __future__ import annotations

from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from ..config import Config
from ..database import Database
from ..utils.deadline import format_deadline, humanize_left
from ..utils.image_report import PIL_AVAILABLE, build_svodka_image
from ..utils.report import (
    build_excel_report,
    build_overall_text_report,
    build_task_text_report,
)

router = Router()


# ── /svodka ──────────────────────────────────────────────────

@router.message(Command("svodka", "svod", "report"))
async def cmd_svodka(
    message: Message, command: CommandObject, db: Database, config: Config, bot: Bot
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

    # Umumiy svodka — rasm + matn
    tasks = await db.list_open_tasks()
    rows  = []
    submitted_map: dict[int, set[int]] = {}
    for t in tasks:
        sub_ids = await db.submitted_employee_ids(t["id"])
        submitted_map[t["id"]] = sub_ids
        rows.append((t, sub_ids))

    # Rasm
    if tasks and PIL_AVAILABLE:
        img_bytes = build_svodka_image(tasks, employees, submitted_map, config.tz)
        if img_bytes:
            fname = f"svodka_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.png"
            await bot.send_photo(
                message.chat.id,
                BufferedInputFile(img_bytes, filename=fname),
                caption="📊 Topshiriqlar svodkasi",
            )
            # Matn ham qo'shamiz
            text = build_overall_text_report(rows, employees, config.tz)
            text += "\n\n📄 Excel: /excel"
            await message.reply(text)
            return

    # Pillow yo'q yoki topshiriq yo'q → faqat matn
    text = build_overall_text_report(rows, employees, config.tz)
    text += "\n\n📄 Excel: /excel"
    await message.reply(text)


# ── /excel ────────────────────────────────────────────────────

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

    data  = build_excel_report(rows, employees, config.tz)
    fname = f"svodka_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.xlsx"
    await bot.send_document(
        message.chat.id,
        BufferedInputFile(data, filename=fname),
        caption=f"📄 Svodka — {len(tasks)} topshiriq, {len(employees)} xodim.",
    )


# ── /eslatma ──────────────────────────────────────────────────

@router.message(Command("eslatma", "remind"))
async def cmd_remind(
    message: Message, command: CommandObject, db: Database, config: Config, bot: Bot
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    if not (command.args and command.args.strip().isdigit()):
        await message.reply("ℹ️ Foydalanish: <code>/eslatma N</code>")
        return
    task_id = int(command.args.strip())
    task    = await db.get_task(task_id)
    if not task:
        await message.reply("⚠️ Bunday topshiriq topilmadi.")
        return
    if config.execution_group_id is None:
        await message.reply("⚠️ Ijro guruhi (EXECUTION_GROUP_ID) sozlanmagan.")
        return

    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    not_done  = [e for e in employees if e["tg_id"] not in submitted]
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


# ── /reyting — xodimlar samaradorligi ────────────────────────

@router.message(Command("reyting", "ranking", "samaradorlik"))
async def cmd_ranking(
    message: Message, db: Database, config: Config
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return

    stats    = await db.employee_open_task_stats()
    open_cnt = (stats[0]["open_count"] if stats else 0) or 0

    if not stats:
        await message.reply("👥 Xodimlar ro'yxati bo'sh.")
        return
    if open_cnt == 0:
        await message.reply("📭 Ochiq topshiriqlar yo'q.")
        return

    lines = [
        f"🏆 <b>XODIMLAR REYTINGI</b> — {open_cnt} ochiq topshiriq",
        "",
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(stats):
        done  = row["done_count"]
        total = open_cnt
        pct   = round(done / total * 100) if total else 0
        bar   = "▓" * (pct // 10) + "░" * (10 - pct // 10)
        medal = medals[i] if i < 3 else f"{i+1}."
        uname = f" (@{row['username']})" if row["username"] else ""
        lines.append(
            f"{medal} {row['full_name']}{uname}\n"
            f"   {bar} {done}/{total} ({pct}%)"
        )

    await message.reply("\n".join(lines))
