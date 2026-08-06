"""AI mutaxassis: suhbat, jadval umumlashtirish (ZIP), analitika.

Arxitektura:
  • /ai savol          — Bosh AI bilan muloqot (to'liq kontekst)
  • /umumlashtir N     — Barcha fayllarni o'qiydi (Excel+Word+PPT+RASM), umumlashtiradi
  • cb_consolidate:N   — Inline tugma orqali umumlashtirish
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, Message

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


# ── Kontekst: ochiq topshiriqlar + reyting ────────────────────

async def _build_context(db: Database, config: Config, user_id: int) -> str:
    parts = []

    tasks = await db.list_open_tasks()
    emp_cnt = await db.count_employees()
    if tasks:
        lines = []
        for t in tasks:
            sub  = await db.submitted_employee_ids(t["id"])
            lines.append(f"#{t['id']} {t['title']} — {len(sub)}/{emp_cnt} bajardi")
        parts.append("Ochiq topshiriqlar:\n" + "\n".join(lines))

    ranking = await db.employee_ranking()
    if ranking:
        top    = ranking[:5]
        bottom = ranking[-3:] if len(ranking) > 5 else []
        parts.append(
            "Top 5 faol: " +
            ", ".join(f"{r['full_name']}({r['done_count']})" for r in top)
        )
        if bottom:
            parts.append(
                "Eng oz bajarganlar: " +
                ", ".join(f"{r['full_name']}({r['done_count']})" for r in bottom)
            )

    if config.is_manager(user_id):
        parts.append("Foydalanuvchi roli: Rahbar")
    else:
        emp = await db.get_employee(user_id)
        if emp:
            parts.append(f"Foydalanuvchi: {emp['full_name']} (xodim)")

    return "\n\n".join(parts)


# ── /ai — bosh AI bilan erkin muloqot ────────────────────────

@router.message(Command("ai"))
async def cmd_ai_chat(
    message: Message, command: CommandObject,
    config: Config, db: Database, ai: Any = None,
) -> None:
    if not ai:
        await message.reply(
            "🤖 AI o'chirilgan.\n"
            "Yoqish uchun:\n"
            "• Bepul: <code>USE_OLLAMA=true</code> + Ollama o'rnating\n"
            "  <code>ollama pull llama3</code>\n"
            "• Pullik: <code>ANTHROPIC_API_KEY</code> to'ldiring"
        )
        return
    question = (command.args or "").strip()
    if not question:
        await message.reply(
            "ℹ️ Foydalanish: <code>/ai savol matni</code>\n\n"
            "Misol: <code>/ai Qaysi xodim topshiriqlarni bajarmayapti?</code>"
        )
        return

    wait    = await message.reply("🤖 O'ylayapman...")
    ctx     = await _build_context(db, config, message.from_user.id if message.from_user else 0)
    answer  = await ai.chat([{"role": "user", "content": question}], extra_context=ctx)
    try:
        await wait.edit_text(f"🤖 {answer}")
    except Exception:
        await message.reply(f"🤖 {answer}")


# ── /umumlashtir N — jadvallarni birlashtirib ZIP ─────────────

@router.message(Command("umumlashtir", "consolidate"))
async def cmd_consolidate(
    message: Message, command: CommandObject,
    config: Config, db: Database, bot: Bot, ai: Any = None,
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    if not (command.args and command.args.strip().isdigit()):
        await message.reply(
            "ℹ️ Foydalanish: <code>/umumlashtir N</code>\n"
            "N — topshiriq raqami.\n"
            "Excel, Word, PPT va rasm fayllarni o'qib, bitta fayl + ZIP yasaydi."
        )
        return
    task_id = int(command.args.strip())
    await _do_consolidate(message, bot, db, config, task_id, ai=ai)


@router.callback_query(F.data.startswith("consolidate:"))
async def cb_consolidate(
    callback: CallbackQuery, db: Database, config: Config, bot: Bot, ai: Any = None,
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    await callback.answer("🤖 Umumlashtirish boshlanmoqda...")
    await _do_consolidate(callback.message, bot, db, config, task_id, ai=ai)


# ── Asosiy umumlashtirish mantiqi ────────────────────────────

async def _do_consolidate(
    reply_to: Message,
    bot: Bot,
    db: Database,
    config: Config,
    task_id: int,
    ai: Any = None,
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
        f"📊 <b>#{task_id}: {task['title']}</b>\n"
        f"🔄 {len(submissions)} ta fayl o'qilmoqda va umumlashtirilmoqda..."
    )

    # ── Topshiriq shabloni va formati ────────────────────────
    task_files      = await db.get_task_files(task_id)
    task_file_names = [tf["file_name"] for tf in task_files if tf["file_name"]]
    template_format = detect_template_format(task_file_names)
    ref_headers: list[str] | None = None

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

    # ── Xodim fayllarini yuklab olish va o'qish ──────────────
    employee_files: list[tuple[str, bytes, str]] = []
    text_reports:   list[tuple[str, str]]        = []
    photo_count     = 0
    error_count     = 0

    for sub in submissions:
        emp      = await db.get_employee(sub["employee_id"])
        emp_name = emp["full_name"] if emp else f"ID:{sub['employee_id']}"

        if not sub["file_id"]:
            if sub["note"]:
                text_reports.append((emp_name, sub["note"]))
            continue

        try:
            tg_f       = await bot.get_file(sub["file_id"])
            buf        = io.BytesIO()
            await bot.download_file(tg_f.file_path, buf)
            file_bytes = buf.getvalue()
            fname      = sub["file_name"] or ""

            # Rasm (photo) bo'lsa — AI vision bilan o'qish
            if not fname or fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                photo_count += 1
                if ai and hasattr(ai, "read_image"):
                    img_text = await ai.read_image(
                        file_bytes,
                        hint=f"Bu '{task['title']}' topshirig'i bo'yicha xodim yuborgan rasm. "
                             "Rasmdagi jadval, raqam va barcha ma'lumotlarni o'qi.",
                    )
                    if img_text:
                        text_reports.append((emp_name, img_text))
                        # Rasmni ham fayl sifatida qo'shamiz (ZIP uchun)
                        safe_fname = fname or f"{emp_name}.jpg"
                        employee_files.append((emp_name, file_bytes, safe_fname))
                else:
                    # AI yo'q — faqat ZIP ga qo'shamiz
                    employee_files.append((emp_name, file_bytes, fname or f"{emp_name}.jpg"))
            else:
                # Excel/Word/PPT fayl
                employee_files.append((emp_name, file_bytes, fname))
                text_reports.append((emp_name, extract_text(file_bytes, fname)))

        except Exception as exc:
            logger.warning("Fayl yuklashda xato (%s/%s): %s", emp_name, sub["id"], exc)
            error_count += 1

    # ── Jadvallarni umumlashtirish ────────────────────────────
    # Faqat fayl bo'lgan (rasm emas) xodimlarni struktura birlashtirish uchun ajratamiz
    struct_files = [
        (n, b, fn) for n, b, fn in employee_files
        if fn.lower().endswith((".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt"))
    ]

    unified_file = b""
    unified_ext  = template_format or "xlsx"

    if struct_files:
        unified_file, unified_ext = auto_consolidate(
            reports=struct_files,
            template_format=template_format,
            reference_headers=ref_headers,
            task_title=task["title"],
            tz=config.tz,
        )

    zip_bytes = b""
    if employee_files:
        zip_bytes = build_zip(
            employee_files=employee_files,
            unified_file=unified_file,
            unified_ext=unified_ext,
            task_id=task_id,
            task_title=task["title"],
        )

    # ── AI tahlili ────────────────────────────────────────────
    ai_summary    = ""
    ai_table_analysis = {}

    if ai and text_reports:
        try:
            result = await ai.consolidate(
                task_title=task["title"],
                task_desc=task["description"] or "",
                reports=text_reports,
            )
            if result:
                if result.get("summary"):
                    ai_summary = result["summary"]
        except Exception as exc:
            logger.warning("AI consolidate xatolik: %s", exc)

    # AI jadval tahlili (agar struktura fayli birlashtirilib, AI mavjud bo'lsa)
    if ai and struct_files and hasattr(ai, "analyze_table") and unified_file:
        try:
            from ..utils.consolidator import consolidate as _consolidate
            canonical_h, unified_rows = _consolidate(struct_files, reference_headers=ref_headers)
            ai_table_analysis = await ai.analyze_table(
                headers=canonical_h,
                rows=unified_rows,
                task_context=f"{task['title']}: {task.get('description', '') or ''}",
            )
        except Exception as exc:
            logger.warning("AI analyze_table xatolik: %s", exc)

    # ── Xulosa xabari ─────────────────────────────────────────
    fmt_label = {"xlsx": "Excel", "docx": "Word", "pptx": "PowerPoint"}.get(
        unified_ext, unified_ext.upper()
    )
    summary = (
        f"📊 <b>UMUMLASHTIRISH #{task_id}: {task['title']}</b>\n\n"
        f"📁 Fayllar qayta ishlandi: {len(employee_files)} ta\n"
    )
    if photo_count:
        summary += f"📸 Rasmlar (AI o'qidi): {photo_count} ta\n"
    if error_count:
        summary += f"⚠️ Yuklab bo'lmadi: {error_count} ta\n"
    if struct_files:
        summary += f"📄 Chiqish formati: {fmt_label}\n"

    if ai_summary:
        summary += f"\n🤖 <b>AI xulosasi:</b>\n{ai_summary}\n"

    if ai_table_analysis:
        if ai_table_analysis.get("top_performers"):
            top = ", ".join(ai_table_analysis["top_performers"][:3])
            summary += f"\n🏆 Eng yaxshi: {top}"
        if ai_table_analysis.get("low_performers"):
            low = ", ".join(ai_table_analysis["low_performers"][:3])
            summary += f"\n⚠️ Kam ishlagan: {low}"
        if ai_table_analysis.get("recommendation"):
            summary += f"\n\n💡 <b>Tavsiya:</b> {ai_table_analysis['recommendation']}"
        if ai_table_analysis.get("anomalies"):
            anom = ai_table_analysis["anomalies"][:2]
            summary += "\n\n🔍 <b>Diqqat:</b>\n" + "\n".join(f"• {a}" for a in anom)

    await _edit_or_reply(wait, reply_to, summary)

    # Umumiy fayl yuborish
    if unified_file:
        ts    = datetime.now(config.tz).strftime("%Y%m%d_%H%M")
        fname = f"UMUMIY_{task_id}_{ts}.{unified_ext}"
        await bot.send_document(
            reply_to.chat.id,
            BufferedInputFile(unified_file, filename=fname),
            caption=f"📄 #{task_id} umumlashtirilgan jadval ({fmt_label}, {len(struct_files)} xodim)",
        )

    # ZIP arxiv
    if zip_bytes:
        zname = f"Topshiriq_{task_id}.zip"
        await bot.send_document(
            reply_to.chat.id,
            BufferedInputFile(zip_bytes, filename=zname),
            caption=(
                f"📦 #{task_id} — barcha fayllar ZIP\n"
                f"({len(employee_files)} xodim fayl + umumiy {fmt_label})"
            ),
        )


async def _edit_or_reply(wait: Message, fallback: Message, text: str) -> None:
    try:
        await wait.edit_text(text)
    except Exception:
        try:
            await fallback.reply(text)
        except Exception:
            pass
