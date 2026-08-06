"""Topshiriq yaratish — barcha menejer xabarlari topshiriq sifatida qabul qilinadi."""
from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    Message,
)

from ..config import Config
from ..database import Database
from ..utils.deadline import format_deadline, humanize_left, parse_deadline
from ..utils.files import extract_file, message_text

router = Router()

_TRIGGER = re.compile(r"#\s?topshiriq", re.IGNORECASE)


# ── Yordam funksiyalari ──────────────────────────────────────

def _extract_title_and_body(text: str) -> tuple[str, str]:
    """Trigger va 'Muddat:' qatorini olib tashlab, sarlavha + tavsif qaytaradi."""
    cleaned = _TRIGGER.sub("", text, count=1).strip()
    lines = [ln.rstrip() for ln in cleaned.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    title = lines[0].strip() if lines else "Nomsiz topshiriq"
    body_lines = [
        ln for ln in lines[1:]
        if not re.match(r"\s*(?:muddat(?:i)?|срок|deadline)\s*[:\-–]", ln, re.IGNORECASE)
    ]
    body = "\n".join(body_lines).strip()
    return title[:255], body


def _auto_extract(text: str) -> tuple[str, str]:
    """AI bo'lmasa: birinchi qator = sarlavha, qolgani = tavsif."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "Topshiriq", ""
    # Muddat qatorini tavsifdan olib tashlaymiz
    body_lines = [
        ln for ln in lines[1:]
        if not re.match(r"\s*(?:muddat(?:i)?|срок|deadline)\s*[:\-–]", ln, re.IGNORECASE)
    ]
    return lines[0][:255], "\n".join(body_lines).strip()


def _is_tasks_source(message: Message, config: Config) -> bool:
    if config.tasks_channel_id and message.chat.id == config.tasks_channel_id:
        return True
    if config.tasks_group_id and message.chat.id == config.tasks_group_id:
        return True
    if config.tasks_group_id is None and config.tasks_channel_id is None:
        return message.chat.type in ("group", "supergroup", "channel")
    return False


def _is_manager_post(message: Message, config: Config) -> bool:
    """Kanal posti yoki guruhda menejer xabari."""
    if message.sender_chat:
        return True  # Kanal posti (kanallar nomidan yuboriladigan xabarlar)
    if message.from_user:
        return config.is_manager(message.from_user.id)
    return False


async def _do_create_task(
    message: Message,
    album: list[Message] | None,
    db: Database,
    config: Config,
    bot: Bot,
    title: str,
    body: str,
    ai=None,
) -> None:
    """Topshiriqni DBga yozadi va ijro guruhiga e'lon qiladi."""
    text = message_text(message)
    deadline_dt = parse_deadline(text, config.tz)
    deadline_iso = deadline_dt.isoformat() if deadline_dt else None

    # AI bilan sarlavha/tavsifni aniqlashtirish
    if ai and (not title or title == text[:255]):
        try:
            result = await ai.classify_task(text)
            if result.get("title"):
                title = result["title"][:255]
            if result.get("description"):
                body = result["description"]
            if result.get("deadline") and not deadline_dt:
                deadline_dt = parse_deadline(result["deadline"], config.tz)
                deadline_iso = deadline_dt.isoformat() if deadline_dt else None
        except Exception:
            pass

    created_by = message.from_user.id if message.from_user else None
    task_id = await db.create_task(
        title=title,
        description=body or None,
        deadline=deadline_iso,
        created_by=created_by,
        src_chat_id=message.chat.id,
        src_msg_id=message.message_id,
    )

    messages = album if album else [message]
    files: list[tuple[str, str | None, str]] = []
    for m in messages:
        info = extract_file(m)
        if info:
            files.append(info)
            await db.add_task_file(task_id, info[0], info[1], info[2])

    tail = (
        "Ijro guruhiga e'lon yuborildi."
        if config.execution_group_id
        else "⚠️ Ijro guruhi (EXECUTION_GROUP_ID) sozlanmagan."
    )
    try:
        await message.reply(
            f"✅ <b>Topshiriq #{task_id}</b> qabul qilindi.\n"
            f"📌 {title}\n"
            f"🗓 Muddat: {format_deadline(deadline_iso, config.tz)}\n"
            f"📎 Fayllar: {len(files)} ta\n\n{tail}"
        )
    except Exception:
        pass

    if config.execution_group_id:
        await _announce_task(bot, config, db, task_id, title, body, deadline_iso, files)


# ── BARCHA MENEJER XABARLARI → TOPSHIRIQ ────────────────────

@router.message(
    (F.chat.type.in_({"group", "supergroup"}))
    | (F.chat.type == "channel")
)
async def handle_any_manager_message(
    message: Message,
    album: list[Message] | None,
    db: Database,
    config: Config,
    bot: Bot,
    ai=None,
) -> None:
    """Topshiriqlar guruh/kanalida menejer har qanday xabar = topshiriq."""
    if not _is_tasks_source(message, config):
        return
    if not _is_manager_post(message, config):
        return

    text = message_text(message)
    if not text and not (album or extract_file(message)):
        return  # Bo'sh xabar

    # #topshiriq yorlig'i bor bo'lsa: aniq topshiriq
    if _TRIGGER.search(text):
        title, body = _extract_title_and_body(text)
    else:
        # Avtomatik: birinchi qator sarlavha
        title, body = _auto_extract(text)
        if not title:
            return

    await _do_create_task(message, album, db, config, bot, title, body, ai=ai)


# ── Kanal postlari uchun alohida handler ────────────────────

@router.channel_post()
async def handle_channel_post(
    message: Message,
    album: list[Message] | None,
    db: Database,
    config: Config,
    bot: Bot,
    ai=None,
) -> None:
    """Topshiriqlar kanalida e'lon qilingan har qanday post = topshiriq."""
    if not config.tasks_channel_id or message.chat.id != config.tasks_channel_id:
        return

    text = message_text(message)
    if _TRIGGER.search(text):
        title, body = _extract_title_and_body(text)
    else:
        title, body = _auto_extract(text)
        if not title:
            return

    await _do_create_task(message, album, db, config, bot, title, body, ai=ai)


# ── E'lon yuborish ───────────────────────────────────────────

async def _announce_task(
    bot: Bot,
    config: Config,
    db: Database,
    task_id: int,
    title: str,
    body: str,
    deadline_iso: str | None,
    files: list[tuple[str, str | None, str]],
) -> None:
    caption = (
        f"📢 <b>YANGI TOPSHIRIQ #{task_id}</b>\n\n"
        f"<b>{title}</b>\n"
    )
    if body:
        caption += f"\n{body}\n"
    caption += (
        f"\n🗓 Muddat: {format_deadline(deadline_iso, config.tz)}"
        f"\n\n➡️ Bajarib bo'lgach, <b>shu xabarga reply qilib</b> ishingizni yuboring "
        f"(yoki xabar boshida <code>#T{task_id}</code> deb yozing)."
    )

    announce_msg: Message | None = None
    if len(files) == 1 and files[0][2] == "document":
        announce_msg = await bot.send_document(
            config.execution_group_id, files[0][0], caption=caption
        )
    elif files:
        media = []
        first = True
        for fid, _fname, kind in files:
            cap = caption if first else None
            if kind == "photo":
                media.append(InputMediaPhoto(media=fid, caption=cap))
            else:
                media.append(InputMediaDocument(media=fid, caption=cap))
            first = False
        try:
            sent = await bot.send_media_group(config.execution_group_id, media)
            announce_msg = sent[0] if sent else None
        except Exception:
            announce_msg = await bot.send_message(config.execution_group_id, caption)
    else:
        announce_msg = await bot.send_message(config.execution_group_id, caption)

    if announce_msg:
        await db.set_announce_msg(task_id, announce_msg.message_id)


# ── /topshiriqlar va /yopish komandalar ─────────────────────

@router.message(Command("topshiriqlar", "tasks"))
async def cmd_list_tasks(message: Message, db: Database, config: Config) -> None:
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.reply("📭 Ochiq topshiriqlar yo'q.")
        return
    total_emp = await db.count_employees()
    lines = [f"📋 <b>Ochiq topshiriqlar ({len(tasks)} ta):</b>", ""]
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        done = len(submitted)
        left = humanize_left(t["deadline"], config.tz)
        lines.append(
            f"<b>#{t['id']}</b> {t['title']}\n"
            f"   ✅ {done}/{total_emp} · {format_deadline(t['deadline'], config.tz)}"
            + (f" · {left}" if left else "")
        )
    lines.append("\nBatafsil svodka: /svodka <code>N</code>")
    await message.reply("\n".join(lines))


@router.message(Command("yopish", "close"))
async def cmd_close_task(
    message: Message, command: CommandObject, db: Database, config: Config
) -> None:
    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return
    if not (command.args and command.args.strip().isdigit()):
        await message.reply("ℹ️ Foydalanish: <code>/yopish N</code>")
        return
    task_id = int(command.args.strip())
    task = await db.get_task(task_id)
    if not task:
        await message.reply("⚠️ Bunday topshiriq topilmadi.")
        return
    await db.close_task(task_id)
    await message.reply(f"🔒 Topshiriq #{task_id} yopildi.")
