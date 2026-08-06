"""Inline tugmalar (callback query) bilan ishlash."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from datetime import datetime

from ..config import Config
from ..database import Database
from ..utils.deadline import format_deadline, humanize_left
from ..utils.report import (
    build_excel_report,
    build_overall_text_report,
    build_task_text_report,
)

router = Router()


# ── Klaviaturalar ──────────────────────────────────────────────

def main_menu_kb(is_manager: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📋 Topshiriqlar", callback_data="menu:tasks"),
            InlineKeyboardButton(text="📌 Mening ishlarim", callback_data="menu:my"),
        ],
    ]
    if is_manager:
        rows.extend([
            [
                InlineKeyboardButton(text="📈 Svodka", callback_data="menu:svodka"),
                InlineKeyboardButton(text="📄 Excel hisobot", callback_data="menu:excel"),
            ],
            [
                InlineKeyboardButton(text="👥 Xodimlar", callback_data="menu:employees"),
                InlineKeyboardButton(text="🤖 AI yordam", callback_data="menu:ai"),
            ],
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="🤖 AI yordam", callback_data="menu:ai"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tasks_list_kb(tasks, show_svodka: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for t in tasks[:10]:
        rows.append([
            InlineKeyboardButton(
                text=f"#{t['id']} {t['title'][:30]}",
                callback_data=f"task:{t['id']}",
            )
        ])
    if show_svodka:
        rows.append([
            InlineKeyboardButton(text="📈 Umumiy svodka", callback_data="menu:svodka"),
        ])
    rows.append([InlineKeyboardButton(text="🔙 Ortga", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_detail_kb(task_id: int, is_manager: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📊 Svodka", callback_data=f"svodka:{task_id}"),
        ],
    ]
    if is_manager:
        rows[0].append(
            InlineKeyboardButton(text="⏰ Eslatma", callback_data=f"remind:{task_id}")
        )
        rows.append([
            InlineKeyboardButton(text="📄 Excel", callback_data=f"excel:{task_id}"),
            InlineKeyboardButton(text="🤖 Umumlashtir", callback_data=f"consolidate:{task_id}"),
        ])
        rows.append([
            InlineKeyboardButton(text="🔒 Yopish", callback_data=f"close:{task_id}"),
        ])
    rows.append([InlineKeyboardButton(text="🔙 Ortga", callback_data="menu:tasks")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(target: str = "menu:back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Ortga", callback_data=target)]
    ])


def confirm_close_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha, yopish", callback_data=f"confirm_close:{task_id}"),
            InlineKeyboardButton(text="❌ Bekor", callback_data=f"task:{task_id}"),
        ]
    ])


# ── /menu komandasi ──────────────────────────────────────────

@router.message(Command("menu"))
async def cmd_menu(message: Message, config: Config) -> None:
    is_mgr = bool(message.from_user and config.is_manager(message.from_user.id))
    await message.answer(
        "🏠 <b>Asosiy menyu</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=main_menu_kb(is_mgr),
    )


# ── Asosiy menyu callback'lari ───────────────────────────────

@router.callback_query(F.data == "menu:back")
async def cb_back(callback: CallbackQuery, config: Config) -> None:
    is_mgr = bool(callback.from_user and config.is_manager(callback.from_user.id))
    await callback.message.edit_text(
        "🏠 <b>Asosiy menyu</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=main_menu_kb(is_mgr),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:tasks")
async def cb_tasks_menu(callback: CallbackQuery, db: Database) -> None:
    tasks = await db.list_open_tasks()
    if not tasks:
        await callback.message.edit_text(
            "📭 Ochiq topshiriqlar yo'q.",
            reply_markup=back_kb(),
        )
    else:
        await callback.message.edit_text(
            f"📋 <b>Ochiq topshiriqlar ({len(tasks)} ta)</b>\n\n"
            "Batafsil ko'rish uchun tanlang:",
            reply_markup=tasks_list_kb(tasks, show_svodka=True),
        )
    await callback.answer()


@router.callback_query(F.data == "menu:my")
async def cb_my_tasks(callback: CallbackQuery, db: Database, config: Config) -> None:
    user = callback.from_user
    tasks = await db.list_open_tasks()
    if not tasks:
        await callback.message.edit_text(
            "📭 Hozircha ochiq topshiriqlar yo'q.",
            reply_markup=back_kb(),
        )
        await callback.answer()
        return
    lines = ["📌 <b>Mening topshiriqlarim holati:</b>", ""]
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        mark = "✅ bajarilgan" if user.id in submitted else "❌ bajarilmagan"
        left = humanize_left(t["deadline"], config.tz)
        lines.append(f"<b>#{t['id']}</b> {t['title']} — {mark}\n   {left}")
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=back_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "menu:employees")
async def cb_employees(callback: CallbackQuery, db: Database, config: Config) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    employees = await db.list_employees()
    if not employees:
        text = "👥 Xodimlar ro'yxati bo'sh.\n\n/hodim_qoshish yoki /ruyxatdan_otish"
    else:
        lines = [f"👥 <b>Xodimlar ({len(employees)} ta):</b>", ""]
        for i, e in enumerate(employees, 1):
            uname = f" (@{e['username']})" if e["username"] else ""
            lines.append(f"{i}. {e['full_name']}{uname}")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:ai")
async def cb_ai_menu(callback: CallbackQuery, config: Config) -> None:
    if not config.ai_enabled:
        await callback.message.edit_text(
            "🤖 AI funksiyalari hozircha o'chirilgan.\n\n"
            "Yoqish uchun <code>.env</code> faylida "
            "<code>ANTHROPIC_API_KEY</code> ni to'ldiring.",
            reply_markup=back_kb(),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "🤖 <b>AI Mutaxassis</b>\n\n"
        "Menga istalgan savolingizni yozing — topshiriq tuzish, "
        "muddat belgilash, hisobot tahlil qilishda yordam beraman.\n\n"
        "Buyruqlar:\n"
        "• /ai <i>savol</i> — AI bilan suhbat\n"
        "• /umumlashtir <i>N</i> — topshiriq hisobotlarini umumlashtirish",
        reply_markup=back_kb(),
    )
    await callback.answer()


# ── Topshiriq detallari ──────────────────────────────────────

@router.callback_query(F.data.startswith("task:"))
async def cb_task_detail(
    callback: CallbackQuery, db: Database, config: Config
) -> None:
    task_id = int(callback.data.split(":")[1])
    task = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topshiriq topilmadi.", show_alert=True)
        return
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    done = len(submitted)
    total = len(employees)
    pct = round(done / total * 100) if total else 0
    left = humanize_left(task["deadline"], config.tz)

    text = (
        f"📋 <b>Topshiriq #{task_id}: {task['title']}</b>\n\n"
        f"🗓 Muddat: {format_deadline(task['deadline'], config.tz)}"
        + (f" · {left}" if left else "") + "\n"
        f"📊 Bajarildi: <b>{done}/{total}</b> ({pct}%)\n"
    )
    if task["description"]:
        text += f"\n{task['description'][:500]}\n"

    is_mgr = config.is_manager(callback.from_user.id)
    await callback.message.edit_text(
        text, reply_markup=task_detail_kb(task_id, is_mgr)
    )
    await callback.answer()


# ── Svodka callback ──────────────────────────────────────────

@router.callback_query(F.data.startswith("svodka:"))
async def cb_svodka(
    callback: CallbackQuery, db: Database, config: Config
) -> None:
    task_id = int(callback.data.split(":")[1])
    task = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topshiriq topilmadi.", show_alert=True)
        return
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    text = build_task_text_report(task, employees, submitted, config.tz)
    await callback.message.edit_text(
        text, reply_markup=back_kb(f"task:{task_id}")
    )
    await callback.answer()


@router.callback_query(F.data == "menu:svodka")
async def cb_overall_svodka(
    callback: CallbackQuery, db: Database, config: Config
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    employees = await db.list_employees()
    tasks = await db.list_open_tasks()
    rows = []
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        rows.append((t, submitted))
    text = build_overall_text_report(rows, employees, config.tz)
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


# ── Excel callback ───────────────────────────────────────────

@router.callback_query(F.data == "menu:excel")
async def cb_excel_all(
    callback: CallbackQuery, db: Database, config: Config, bot: Bot
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    employees = await db.list_employees()
    if not employees:
        await callback.answer("Avval xodimlar ro'yxatini to'ldiring.", show_alert=True)
        return
    tasks = sorted(await db.list_open_tasks(), key=lambda t: t["id"])
    if not tasks:
        await callback.answer("Ochiq topshiriqlar yo'q.", show_alert=True)
        return
    rows = []
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        subs = {s["employee_id"]: s for s in await db.get_submissions(t["id"])}
        rows.append((t, submitted, subs))
    data = build_excel_report(rows, employees, config.tz)
    fname = f"svodka_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.xlsx"
    await bot.send_document(
        callback.message.chat.id,
        BufferedInputFile(data, filename=fname),
        caption=f"📄 Svodka — {len(tasks)} topshiriq, {len(employees)} xodim.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("excel:"))
async def cb_excel_task(
    callback: CallbackQuery, db: Database, config: Config, bot: Bot
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    task = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topshiriq topilmadi.", show_alert=True)
        return
    employees = await db.list_employees()
    if not employees:
        await callback.answer("Xodimlar ro'yxati bo'sh.", show_alert=True)
        return
    submitted = await db.submitted_employee_ids(task_id)
    subs = {s["employee_id"]: s for s in await db.get_submissions(task_id)}
    data = build_excel_report([(task, submitted, subs)], employees, config.tz)
    fname = f"topshiriq_{task_id}_{datetime.now(config.tz).strftime('%Y%m%d_%H%M')}.xlsx"
    await bot.send_document(
        callback.message.chat.id,
        BufferedInputFile(data, filename=fname),
        caption=f"📄 #{task_id} — {task['title']}",
    )
    await callback.answer()


# ── Eslatma callback ─────────────────────────────────────────

@router.callback_query(F.data.startswith("remind:"))
async def cb_remind(
    callback: CallbackQuery, db: Database, config: Config, bot: Bot
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    if config.execution_group_id is None:
        await callback.answer("Ijro guruhi sozlanmagan.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    task = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topshiriq topilmadi.", show_alert=True)
        return
    employees = await db.list_employees()
    submitted = await db.submitted_employee_ids(task_id)
    not_done = [e for e in employees if e["tg_id"] not in submitted]
    if not not_done:
        await callback.answer("🎉 Hamma bajargan!", show_alert=True)
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
    await callback.answer(f"✅ Eslatma yuborildi ({len(not_done)} xodimga).")


# ── Topshiriqni yopish callback ──────────────────────────────

@router.callback_query(F.data.startswith("close:"))
async def cb_close(callback: CallbackQuery, config: Config) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        f"🔒 Topshiriq #{task_id} ni yopishni tasdiqlaysizmi?",
        reply_markup=confirm_close_kb(task_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_close:"))
async def cb_confirm_close(
    callback: CallbackQuery, db: Database, config: Config
) -> None:
    if not config.is_manager(callback.from_user.id):
        await callback.answer("⛔️ Faqat rahbar uchun.", show_alert=True)
        return
    task_id = int(callback.data.split(":")[1])
    task = await db.get_task(task_id)
    if not task:
        await callback.answer("⚠️ Topshiriq topilmadi.", show_alert=True)
        return
    await db.close_task(task_id)
    await callback.message.edit_text(
        f"🔒 Topshiriq #{task_id} yopildi.",
        reply_markup=back_kb("menu:tasks"),
    )
    await callback.answer()
