"""Barcha klaviatura va callback ishlovchilar."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from ..config import Config
from ..database import Database
from ..utils.deadline import format_deadline, humanize_left
from ..utils.report import (
    build_excel_report,
    build_overall_text_report,
    build_task_text_report,
)

router = Router()


# ══════════════════════════════════════════════════════════════
#  REPLY KEYBOARD — pastdagi doimiy tugmalar
# ══════════════════════════════════════════════════════════════

def main_reply_kb(is_manager: bool) -> ReplyKeyboardMarkup:
    """Asosiy menyu — chat pastida doim ko'rinadi."""
    if is_manager:
        buttons = [
            [KeyboardButton(text="📋 Topshiriqlar"),  KeyboardButton(text="📊 Svodka")],
            [KeyboardButton(text="📈 Reyting"),        KeyboardButton(text="📄 Excel")],
            [KeyboardButton(text="🗂 Umumlashtir"),    KeyboardButton(text="🤖 AI Suhbat")],
            [KeyboardButton(text="💻 Kompyuter"),       KeyboardButton(text="👥 Xodimlar")],
            [KeyboardButton(text="❓ Yordam")],
        ]
    else:
        buttons = [
            [KeyboardButton(text="📌 Ishlarim"),     KeyboardButton(text="📋 Topshiriqlar")],
            [KeyboardButton(text="🤖 AI Yordam"),    KeyboardButton(text="❓ Yordam")],
        ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        persistent=True,
    )


# ══════════════════════════════════════════════════════════════
#  INLINE KEYBOARD — tugmali panellar
# ══════════════════════════════════════════════════════════════

def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def tasks_panel_kb(tasks, is_manager: bool) -> InlineKeyboardMarkup:
    rows = []
    for t in tasks[:12]:
        title = t["title"][:28] + ("…" if len(t["title"]) > 28 else "")
        rows.append([_btn(f"#{t['id']}  {title}", f"task:{t['id']}")])
    if is_manager:
        rows.append([_btn("➕ Yangi topshiriq qo'shish", "hint:new_task")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_detail_kb(task_id: int, is_manager: bool) -> InlineKeyboardMarkup:
    if is_manager:
        rows = [
            [_btn("📊 Svodka",       f"svodka:{task_id}"),
             _btn("⏰ Eslatma",      f"remind:{task_id}")],
            [_btn("📄 Excel",        f"excel:{task_id}"),
             _btn("🤖 Umumlashtir",  f"consolidate:{task_id}")],
            [_btn("🔒 Topshiriqni yopish", f"close:{task_id}")],
            [_btn("‹ Ortga",          "back:tasks")],
        ]
    else:
        rows = [
            [_btn("📊 Svodka", f"svodka:{task_id}")],
            [_btn("‹ Ortga",   "back:tasks")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_close_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("✅ Ha, yopish", f"confirm_close:{task_id}"),
        _btn("✗ Bekor",       f"task:{task_id}"),
    ]])


def back_kb(target: str = "back:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("‹ Ortga", target)]])


def ai_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💬 Savol yozing (matn)",    "hint:ai_type")],
        [_btn("📊 Oxirgi topshiriq tahlili", "ai:last_task")],
    ])


def computer_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💡 Namuna vazifalar",     "computer:examples")],
        [_btn("⛔ Agentni to'xtatish",   "computer:stop")],
    ])


def employees_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ Xodim qo'shish",       "hint:add_employee")],
        [_btn("🗑 Xodim o'chirish",      "hint:del_employee")],
    ])


# ══════════════════════════════════════════════════════════════
#  REPLY KEYBOARD HANDLER — matn tugmalarini ushlaymiz
# ══════════════════════════════════════════════════════════════

@router.message(F.text == "📋 Topshiriqlar")
async def btn_tasks(message: Message, db: Database, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    tasks  = await db.list_open_tasks()
    if not tasks:
        await message.answer(
            "📭 <b>Ochiq topshiriqlar yo'q</b>\n\n"
            "Topshiriqlar guruhiga xabar yuboring — bot avtomatik qabul qiladi.",
        )
        return
    await message.answer(
        f"📋 <b>Ochiq topshiriqlar — {len(tasks)} ta</b>\n\n"
        "Ko'rish uchun tanlang 👇",
        reply_markup=tasks_panel_kb(tasks, is_mgr),
    )


@router.message(F.text == "📊 Svodka")
async def btn_svodka(
    message: Message, db: Database, config: Config, bot: Bot
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.answer("⛔️ Svodka faqat rahbar uchun.")
        return
    from ..utils.image_report import PIL_AVAILABLE, build_svodka_image
    employees = await db.list_employees()
    tasks     = await db.list_open_tasks()
    sub_map: dict[int, set[int]] = {}
    rows = []
    for t in tasks:
        sids = await db.submitted_employee_ids(t["id"])
        sub_map[t["id"]] = sids
        rows.append((t, sids))

    if tasks and PIL_AVAILABLE:
        img = build_svodka_image(tasks, employees, sub_map, config.tz)
        if img:
            fname = f"svodka_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.png"
            await bot.send_photo(
                message.chat.id,
                BufferedInputFile(img, filename=fname),
                caption="📊 Topshiriqlar svodkasi",
            )

    text = build_overall_text_report(rows, employees, config.tz)
    await message.answer(text)


@router.message(F.text == "📈 Reyting")
async def btn_reyting(message: Message, db: Database, config: Config) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.answer("⛔️ Reyting faqat rahbar uchun.")
        return
    stats    = await db.employee_open_task_stats()
    open_cnt = (stats[0]["open_count"] if stats else 0) or 0
    if not stats:
        await message.answer("👥 Xodimlar ro'yxati bo'sh.")
        return
    if open_cnt == 0:
        await message.answer("📭 Ochiq topshiriqlar yo'q.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines  = [f"🏆 <b>XODIMLAR REYTINGI</b> — {open_cnt} ochiq topshiriq", ""]
    for i, r in enumerate(stats):
        done  = r["done_count"]
        pct   = round(done / open_cnt * 100) if open_cnt else 0
        bar   = "▓" * (pct // 10) + "░" * (10 - pct // 10)
        medal = medals[i] if i < 3 else f"{i+1}."
        uname = f" (@{r['username']})" if r["username"] else ""
        lines.append(f"{medal} <b>{r['full_name']}</b>{uname}\n   {bar} {done}/{open_cnt} ({pct}%)")
    await message.answer("\n".join(lines))


@router.message(F.text == "📄 Excel")
async def btn_excel(
    message: Message, db: Database, config: Config, bot: Bot
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.answer("⛔️ Excel faqat rahbar uchun.")
        return
    employees = await db.list_employees()
    tasks     = sorted(await db.list_open_tasks(), key=lambda t: t["id"])
    if not employees or not tasks:
        await message.answer("📭 Ma'lumot yetarli emas.")
        return
    rows = []
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        subs      = {s["employee_id"]: s for s in await db.get_submissions(t["id"])}
        rows.append((t, submitted, subs))
    data  = build_excel_report(rows, employees, config.tz)
    fname = f"svodka_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.xlsx"
    await bot.send_document(
        message.chat.id,
        BufferedInputFile(data, filename=fname),
        caption=f"📄 Svodka — {len(tasks)} topshiriq, {len(employees)} xodim.",
    )


@router.message(F.text == "🤖 AI Suhbat")
async def btn_ai(message: Message, config: Config) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.answer("⛔️ AI suhbat faqat rahbar uchun.")
        return
    await message.answer(
        "🤖 <b>AI Mutaxassis</b>\n\n"
        "Savolingizni yozing — tahlil, maslahat, hisobot:\n\n"
        "<code>/ai Qaysi xodim topshiriqlarni bajarmayapti?</code>\n"
        "<code>/ai Bu hafta eng faol xodim kim?</code>\n"
        "<code>/ai 3-topshiriqni umumlashtir</code>",
        reply_markup=ai_panel_kb(),
    )


@router.message(F.text == "💻 Kompyuter")
async def btn_computer(message: Message, config: Config) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.answer("⛔️ Kompyuter agenti faqat rahbar uchun.")
        return
    await message.answer(
        "💻 <b>Avtonom Kompyuter Agenti</b>\n\n"
        "AI ekraningizni ko'rib, vazifangizni bajaradi.\n\n"
        "📝 <b>Foydalanish:</b>\n"
        "<code>/kompyuter Chrome ochib google.com ga kir</code>\n"
        "<code>/kompyuter Notepad ochib salom yoz</code>\n"
        "<code>/kompyuter Ish stolini ko'rsat</code>\n\n"
        "⚠️ To'xtatish: <code>/stop</code> yoki sichqonni ekran burchagiga olib boring.",
        reply_markup=computer_panel_kb(),
    )


@router.message(F.text == "👥 Xodimlar")
async def btn_employees(message: Message, db: Database, config: Config) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.answer("⛔️ Bu bo'lim faqat rahbar uchun.")
        return
    employees = await db.list_employees()
    if not employees:
        await message.answer(
            "👥 <b>Xodimlar ro'yxati bo'sh</b>\n\n"
            "Qo'shish: <code>/hodim_qoshish Ism Familiya</code>",
            reply_markup=employees_panel_kb(),
        )
        return
    lines = [f"👥 <b>Xodimlar ({len(employees)} ta)</b>", ""]
    for i, e in enumerate(employees, 1):
        uname = f" · @{e['username']}" if e["username"] else ""
        lines.append(f"{i}. {e['full_name']}{uname}")
    await message.answer(
        "\n".join(lines),
        reply_markup=employees_panel_kb(),
    )


@router.message(F.text == "📌 Ishlarim")
async def btn_my_tasks(message: Message, db: Database, config: Config) -> None:
    user  = message.from_user
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.answer("📭 Hozircha ochiq topshiriqlar yo'q.")
        return
    lines = ["📌 <b>Mening topshiriqlarim:</b>", ""]
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        mark = "✅" if user.id in submitted else "⏳"
        left = humanize_left(t["deadline"], config.tz)
        lines.append(f"{mark} <b>#{t['id']}</b> {t['title']}\n   📅 {left}")
    await message.answer("\n".join(lines))


@router.message(F.text == "🤖 AI Yordam")
async def btn_ai_employee(message: Message) -> None:
    await message.answer(
        "🤖 <b>AI Yordam</b>\n\n"
        "Savolingizni yozing:\n\n"
        "<code>/ai Qanday topshiriq qoldimi?</code>\n"
        "<code>/ai Topshiriq muddati qachon?</code>",
    )


@router.message(F.text == "❓ Yordam")
async def btn_help(message: Message, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    from .common import HELP_MANAGER, HELP_EMPLOYEE
    await message.answer(HELP_MANAGER if is_mgr else HELP_EMPLOYEE)


# ══════════════════════════════════════════════════════════════
#  INLINE CALLBACK HANDLER — inline tugmalar
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("back:"))
async def cb_back(callback: CallbackQuery, db: Database, config: Config) -> None:
    target = callback.data.split(":", 1)[1]
    is_mgr = bool(callback.from_user and config.is_manager(callback.from_user.id))

    if target == "tasks":
        tasks = await db.list_open_tasks()
        if not tasks:
            await callback.message.edit_text("📭 Ochiq topshiriqlar yo'q.")
        else:
            await callback.message.edit_text(
                f"📋 <b>Ochiq topshiriqlar — {len(tasks)} ta</b>\n\nKo'rish uchun tanlang 👇",
                reply_markup=tasks_panel_kb(tasks, is_mgr),
            )
    else:
        await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.startswith("task:"))
async def cb_task_detail(callback: CallbackQuery, db: Database, config: Config) -> None:
    task_id  = int(callback.data.split(":")[1])
    task     = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topshiriq topilmadi.", show_alert=True)
        return
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    done      = len(submitted)
    total     = len(employees)
    pct       = round(done / total * 100) if total else 0
    left      = humanize_left(task["deadline"], config.tz)
    bar       = "▓" * (pct // 10) + "░" * (10 - pct // 10)

    text = (
        f"📋 <b>#{task_id}: {task['title']}</b>\n\n"
        f"📅 Muddat: <b>{format_deadline(task['deadline'], config.tz)}</b>"
        + (f"  ·  {left}" if left else "") + "\n"
        f"📊 {bar} <b>{done}/{total}</b> ({pct}%)\n"
    )
    if task["description"]:
        text += f"\n📝 {task['description'][:400]}\n"

    is_mgr = config.is_manager(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=task_detail_kb(task_id, is_mgr))
    await callback.answer()


@router.callback_query(F.data.startswith("svodka:"))
async def cb_svodka(callback: CallbackQuery, db: Database, config: Config) -> None:
    task_id   = int(callback.data.split(":")[1])
    task      = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topilmadi.", show_alert=True)
        return
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    text      = build_task_text_report(task, employees, submitted, config.tz)
    await callback.message.edit_text(text, reply_markup=back_kb(f"task:{task_id}"))
    await callback.answer()


@router.callback_query(F.data.startswith("excel:"))
async def cb_excel(
    callback: CallbackQuery, db: Database, config: Config, bot: Bot
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar.", show_alert=True)
        return
    task_id   = int(callback.data.split(":")[1])
    task      = await db.get_task(task_id)
    employees = await db.list_employees()
    if not task or not employees:
        await callback.answer("⚠️ Ma'lumot topilmadi.", show_alert=True)
        return
    submitted = await db.submitted_employee_ids(task_id)
    subs      = {s["employee_id"]: s for s in await db.get_submissions(task_id)}
    data      = build_excel_report([(task, submitted, subs)], employees, config.tz)
    fname     = f"topshiriq_{task_id}_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.xlsx"
    await bot.send_document(
        callback.message.chat.id,
        BufferedInputFile(data, filename=fname),
        caption=f"📄 #{task_id} — {task['title']}",
    )
    await callback.answer("📄 Excel yuborildi!")


@router.callback_query(F.data.startswith("remind:"))
async def cb_remind(
    callback: CallbackQuery, db: Database, config: Config, bot: Bot
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar.", show_alert=True)
        return
    if config.execution_group_id is None:
        await callback.answer("Ijro guruhi sozlanmagan.", show_alert=True)
        return
    task_id   = int(callback.data.split(":")[1])
    task      = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topilmadi.", show_alert=True)
        return
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    not_done  = [e for e in employees if e["tg_id"] not in submitted]
    if not not_done:
        await callback.answer("🎉 Hamma bajargan!", show_alert=True)
        return
    mentions  = [
        f"@{e['username']}" if e["username"]
        else f'<a href="tg://user?id={e["tg_id"]}">{e["full_name"]}</a>'
        for e in not_done
    ]
    await bot.send_message(
        config.execution_group_id,
        f"⏰ <b>ESLATMA — #{task_id}: {task['title']}</b>\n"
        f"🗓 {format_deadline(task['deadline'], config.tz)} "
        f"{humanize_left(task['deadline'], config.tz)}\n\n"
        f"❗️ Bajarmagan ({len(not_done)} ta): " + ", ".join(mentions),
    )
    await callback.answer(f"✅ Eslatma yuborildi ({len(not_done)} kishi).")


@router.callback_query(F.data.startswith("close:"))
async def cb_close(callback: CallbackQuery, config: Config) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        f"🔒 <b>#{task_id}</b>-topshiriqni yopishni tasdiqlaysizmi?",
        reply_markup=confirm_close_kb(task_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_close:"))
async def cb_confirm_close(
    callback: CallbackQuery, db: Database, config: Config
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    await db.close_task(task_id)
    await callback.message.edit_text(
        f"🔒 <b>#{task_id}</b>-topshiriq yopildi.",
        reply_markup=back_kb("back:tasks"),
    )
    await callback.answer("✅ Yopildi.")


@router.callback_query(F.data == "computer:stop")
async def cb_computer_stop(callback: CallbackQuery, config: Config) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar.", show_alert=True)
        return
    from . import computer as comp_mod
    if comp_mod._active_agent:
        comp_mod._active_agent.stop()
        await callback.answer("⛔ Agent to'xtatilmoqda...", show_alert=True)
    else:
        await callback.answer("ℹ️ Hech qanday agent ishlamayapti.", show_alert=True)


@router.callback_query(F.data == "computer:examples")
async def cb_computer_examples(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "💡 <b>Namuna vazifalar:</b>\n\n"
        "<code>/kompyuter Chrome ochib google.com ga kir</code>\n"
        "<code>/kompyuter Notepad ochib Salom dunyo yoz va saqlا</code>\n"
        "<code>/kompyuter Yangi papka yarat va nom qo'y Ish</code>\n"
        "<code>/kompyuter Hozirgi vaqtni ko'rsat</code>\n"
        "<code>/kompyuter Windows sozlamalarini och</code>",
    )


@router.callback_query(F.data == "ai:last_task")
async def cb_ai_last(
    callback: CallbackQuery, db: Database, config: Config
) -> None:
    await callback.answer()
    tasks = await db.list_open_tasks()
    if not tasks:
        await callback.message.answer("📭 Ochiq topshiriqlar yo'q.")
        return
    last = tasks[-1]
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(last["id"])
    text      = build_task_text_report(last, employees, submitted, config.tz)
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("hint:"))
async def cb_hint(callback: CallbackQuery) -> None:
    hints = {
        "new_task":    "📝 Topshiriqlar guruhiga xabar yuboring — bot avtomatik qabul qiladi.\nMuddat qo'shish: <code>Muddat: 10.08.2026 18:00</code>",
        "ai_type":     "🤖 <code>/ai savolingiz</code> deb yuboring.\nMisol: <code>/ai Bu hafta eng faol xodim kim?</code>",
        "add_employee":"👤 <code>/hodim_qoshish Ism Familiya</code>",
        "del_employee":"🗑 <code>/hodim_ochirish ID</code>\nID ni bilish: /hodimlar",
    }
    key  = callback.data.split(":", 1)[1]
    text = hints.get(key, "ℹ️ Yordam mavjud emas.")
    await callback.answer(text, show_alert=True)


# ══════════════════════════════════════════════════════════════
#  🗂 UMUMLASHTIR TUGMASI
# ══════════════════════════════════════════════════════════════

def consolidate_tasks_kb(tasks) -> InlineKeyboardMarkup:
    """Umumlashtirish uchun topshiriqlar tanlovi."""
    rows = []
    for t in tasks[:15]:
        title = t["title"][:30] + ("…" if len(t["title"]) > 30 else "")
        rows.append([_btn(f"🗂 #{t['id']}  {title}", f"consolidate:{t['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "🗂 Umumlashtir")
async def btn_consolidate(message: Message, db: Database, config: Config) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.answer("⛔️ Bu bo'lim faqat rahbar uchun.")
        return
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.answer("📭 Umumlashtirish uchun ochiq topshiriqlar yo'q.")
        return
    await message.answer(
        "🗂 <b>Qaysi topshiriqni umumlashtirish kerak?</b>\n\n"
        "Tanlang 👇 — bot barcha xodim fayllarini o'qib,\n"
        "bitta Excel/Word/PPT + ZIP + AI tahlil yuboradi.",
        reply_markup=consolidate_tasks_kb(tasks),
    )


# ── /menu komandasi (eski compat) ────────────────────────────

@router.message(Command("menu"))
async def cmd_menu(message: Message, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    await message.answer(
        "🏠 <b>Asosiy menyu</b>\n\nQuyidagi tugmalardan foydalaning 👇",
        reply_markup=main_reply_kb(is_mgr),
    )


def main_menu_kb(is_manager: bool) -> InlineKeyboardMarkup:
    """Eski kod bilan moslik uchun (common.py dan chaqiriladi)."""
    rows: list[list[InlineKeyboardButton]] = []
    return InlineKeyboardMarkup(inline_keyboard=rows)
