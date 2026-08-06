"""AI mutaxassis: suhbat, hisobot umumlashtirish (ZIP), va analitika."""
from __future__ import annotations

import io
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)

from ..config import Config
from ..database import Database
from ..utils.consolidator import (
    auto_consolidate,
    build_zip,
    detect_template_format,
    extract_table_from_file,
    extract_table_from_xlsx,
)
from ..utils.extract import extract_text

logger = logging.getLogger(__name__)
router = Router()


def _ai_client(ai):
    return ai  # None yoki AIClient/OllamaClient


# ── Kontekst ma'lumoti ────────────────────────────────────────

async def _build_context(db: Database, config: Config, user_id: int) -> str:
    parts = []

    # Ochiq topshiriqlar
    tasks = await db.list_open_tasks()
    emp_cnt = await db.count_employees()
    if tasks:
        lines = []
        for t in tasks:
            sub = await db.submitted_employee_ids(t["id"])
            lines.append(f"#{t['id']} {t['title']} — {len(sub)}/{emp_cnt} bajardi")
        parts.append("Ochiq topshiriqlar:\n" + "\n".join(lines))

    # Reyting
    ranking = await db.employee_ranking()
    if ranking:
        top = ranking[:5]
        bottom = ranking[-3:] if len(ranking) > 5 else []
        top_str    = ", ".join(f"{r['full_name']}({r['done_count']})" for r in top)
        bottom_str = ", ".join(f"{r['full_name']}({r['done_count']})" for r in bottom)
        parts.append(f"Top 5 faol: {top_str}")
        if bottom_str:
            parts.append(f"Eng oz bajarganlar: {bottom_str}")

    # Foydalanuvchi
    if config.is_manager(user_id):
        parts.append("Foydalanuvchi roli: Rahbar")
    else:
        emp = await db.get_employee(user_id)
        if emp:
            parts.append(f"Foydalanuvchi: {emp['full_name']} (xodim)")

    return "\n\n".join(parts)


# ── /ai — erkin suhbat ────────────────────────────────────────

@router.message(Command("ai"))
async def cmd_ai_chat(
    message: Message, command: CommandObject, config: Config, db: Database,
    ai=None,
) -> None:
    client = _ai_client(ai)
    if not client:
        await message.reply(
            "🤖 AI o'chirilgan.\n"
            "Yoqish uchun:\n"
            "• Bepul: <code>USE_OLLAMA=true</code> + Ollama o'rnating\n"
            "• Pullik: <code>ANTHROPIC_API_KEY</code> ni to'ldiring"
        )
        return
    question = (command.args or "").strip()
    if not question:
        await message.reply(
            "ℹ️ Foydalanish: <code>/ai savol matni</code>\n\n"
            "Masalan: <code>/ai Qaysi hodim topshiriqlarni bajarmayapti?</code>"
        )
        return

    wait  = await message.reply("🤖 O'ylamoqda...")
    extra = await _build_context(db, config, message.from_user.id if message.from_user else 0)
    answer = await client.chat([{"role": "user", "content": question}], extra_context=extra)
    try:
        await wait.edit_text(f"🤖 {answer}")
    except Exception:
        await message.reply(f"🤖 {answer}")


# ── /umumlashtir — jadvallarni birlashtirib ZIP ───────────────

@router.message(Command("umumlashtir", "consolidate"))
async def cmd_consolidate(
    message: Message, command: CommandObject, config: Config, db: Database,
    bot: Bot, ai=None,
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    if not (command.args and command.args.strip().isdigit()):
        await message.reply(
            "ℹ️ Foydalanish: <code>/umumlashtir N</code>\n"
            "N — topshiriq raqami. Xodimlar yuborgan Excel/Word/PPT fayllarni umumlashtiradi."
        )
        return
    task_id = int(command.args.strip())
    await _do_consolidate(message, bot, db, config, task_id, ai=ai)


@router.callback_query(F.data.startswith("consolidate:"))
async def cb_consolidate(
    callback: CallbackQuery, db: Database, config: Config, bot: Bot, ai=None,
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    await callback.answer("🤖 Umumlashtirish boshlanmoqda...")
    await _do_consolidate(callback.message, bot, db, config, task_id, ai=ai)


async def _do_consolidate(
    reply_to: Message, bot: Bot, db: Database, config: Config,
    task_id: int, ai=None,
) -> None:
    task = await db.get_task(task_id)
    if not task:
        await reply_to.reply("⚠️ Bunday topshiriq topilmadi.")
        return

    submissions = await db.get_submissions(task_id)
    if not submissions:
        await reply_to.reply(
            f"⚠️ #{task_id}-topshiriq bo'yicha hali hech kim ish topshirmagan."
        )
        return

    wait = await reply_to.reply(
        f"📊 #{task_id}: {task['title']}\n"
        f"🔄 {len(submissions)} ta fayl yuklanmoqda va umumlashtirilmoqda..."
    )

    # Topshiriq shablonini olish va formatini aniqlash
    task_files      = await db.get_task_files(task_id)
    task_file_names = [tf["file_name"] for tf in task_files if tf["file_name"]]
    template_format = detect_template_format(task_file_names)
    ref_headers     = None

    for tf in task_files:
        if tf["file_name"] and tf["file_name"].lower().endswith((".xlsx", ".xls")):
            try:
                tg_f = await bot.get_file(tf["file_id"])
                buf  = io.BytesIO()
                await bot.download_file(tg_f.file_path, buf)
                hdrs, _ = extract_table_from_xlsx(buf.getvalue())
                if hdrs:
                    ref_headers = hdrs
                    break
            except Exception:
                pass

    # Har bir xodim faylini yuklab olish
    employee_files: list[tuple[str, bytes, str]] = []
    text_reports:   list[tuple[str, str]]        = []

    for sub in submissions:
        emp      = await db.get_employee(sub["employee_id"])
        emp_name = emp["full_name"] if emp else f"ID:{sub['employee_id']}"

        if not sub["file_id"] or not sub["file_name"]:
            if sub["note"]:
                text_reports.append((emp_name, sub["note"]))
            continue

        try:
            tg_f = await bot.get_file(sub["file_id"])
            buf  = io.BytesIO()
            await bot.download_file(tg_f.file_path, buf)
            file_bytes = buf.getvalue()
            fname      = sub["file_name"]
            employee_files.append((emp_name, file_bytes, fname))
            text_reports.append((emp_name, extract_text(file_bytes, fname)))
        except Exception as exc:
            logger.warning("Fayl yuklashda xato (%s): %s", sub["id"], exc)

    if not employee_files and not text_reports:
        await _edit_or_reply(wait, reply_to, "⚠️ Yuklanadigan fayl topilmadi.")
        return

    # ── Jadvallarni umumlashtirish ────────────────────────────
    canonical_headers: list[str] = []
    unified_rows_count = 0
    unified_file  = b""
    unified_ext   = "xlsx"
    zip_bytes     = b""

    if employee_files:
        unified_file, unified_ext = auto_consolidate(
            reports=employee_files,
            template_format=template_format,
            reference_headers=ref_headers,
            task_title=task["title"],
            tz=config.tz,
        )
        zip_bytes = build_zip(
            employee_files=employee_files,
            unified_file=unified_file,
            unified_ext=unified_ext,
            task_id=task_id,
            task_title=task["title"],
        )

    # ── AI bilan xulosa ───────────────────────────────────────
    fmt_label = {"xlsx": "Excel", "docx": "Word", "pptx": "PowerPoint"}.get(unified_ext, unified_ext.upper())
    summary_text = (
        f"📊 <b>UMUMLASHTIRISH #{task_id}: {task['title']}</b>\n\n"
        f"📁 Qayta ishlangan fayllar: {len(employee_files)} ta\n"
        f"📝 Matn hisobotlar: {len(text_reports)} ta\n"
        f"📄 Chiqish formati: {fmt_label}\n"
    )

    if ai and text_reports:
        try:
            result = await ai.consolidate(
                task_title=task["title"],
                task_desc=task["description"] or "",
                reports=text_reports,
            )
            if result:
                if result.get("summary"):
                    summary_text += f"\n🤖 <b>AI xulosasi:</b>\n{result['summary']}\n"
                kp = result.get("key_points", [])
                if kp:
                    summary_text += "\n🔑 <b>Asosiy natijalar:</b>\n"
                    for point in kp:
                        summary_text += f"  • {point}\n"
        except Exception as exc:
            logger.warning("AI consolidate xatolik: %s", exc)

    await _edit_or_reply(wait, reply_to, summary_text)

    # Umumiy fayl yuborish (format saqlanadi: Excel/Word/PPT)
    if unified_file:
        ts    = datetime.now(config.tz).strftime("%Y%m%d_%H%M")
        fname = f"UMUMIY_{task_id}_{ts}.{unified_ext}"
        await bot.send_document(
            reply_to.chat.id,
            BufferedInputFile(unified_file, filename=fname),
            caption=f"📄 #{task_id} umumlashtirilgan jadval ({fmt_label})",
        )

    # ZIP arxiv (barcha xodim fayllar + umumiy)
    if zip_bytes:
        zname = f"Topshiriq_{task_id}.zip"
        await bot.send_document(
            reply_to.chat.id,
            BufferedInputFile(zip_bytes, filename=zname),
            caption=f"📦 #{task_id} — barcha fayllar ZIP ({len(employee_files)} xodim + umumiy {fmt_label})",
        )


async def _edit_or_reply(wait: Message, fallback: Message, text: str) -> None:
    try:
        await wait.edit_text(text)
    except Exception:
        await fallback.reply(text)
