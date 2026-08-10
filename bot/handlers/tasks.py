"""Topshiriq yaratish.

Qoidalar:
  • AI yoqilgan holda: AI har bir menejer xabarini tekshiradi — topshiriqmi yoki oddiy xabarmi.
  • AI o'chirilgan holda: uzunlik + kalit so'zlar heuristikasi.
  • Duplicate xabarlar (bir xil chat+msg_id) ikkinchi marta qayta ishlanmaydi.
"""
from __future__ import annotations

import re
import time
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import (
    InputMediaDocument,
    InputMediaPhoto,
    Message,
)

from ..config import Config
from ..database import Database
from ..utils.deadline import format_deadline, humanize_left, parse_deadline
from ..utils.files import extract_file, message_text
from ..utils.notify import send_and_clean

router = Router()

_TRIGGER    = re.compile(r"#\s?topshiriq", re.IGNORECASE)
_SHORT_SKIP = re.compile(
    r"^\s*(ok|ha|yo[oʻ']q|ko[oʻ']rdim|rahmat|yaxshi|bo[oʻ']ladi|tushundim"
    r"|salom|assalomu alaykum|xayrli|😊|👍|✅|❌|🙏|👌)\s*$",
    re.IGNORECASE,
)

# Duplicate oldini olish uchun kesh: {(chat_id, msg_id): timestamp}
_processed: dict[tuple[int, int], float] = {}
_CACHE_TTL = 120  # sekund


def _cache_check(chat_id: int, msg_id: int) -> bool:
    """True qaytarsa — allaqachon qayta ishlangan, o'tkazib yuborish kerak."""
    now = time.monotonic()
    key = (chat_id, msg_id)
    # Eski yozuvlarni tozalash
    dead = [k for k, t in _processed.items() if now - t > _CACHE_TTL]
    for k in dead:
        _processed.pop(k, None)
    if key in _processed:
        return True
    _processed[key] = now
    return False


# ── Heuristik (AI bo'lmasa) ─────────────────────────────────

def _heuristic_is_task(text: str, has_files: bool) -> bool:
    """AI o'chirilgan holda topshiriqni aniqlash."""
    if has_files:
        return True  # Fayl biriktirilgan xabar deyarli har doim topshiriq
    t = text.strip()
    if len(t) < 15:
        return False
    if _SHORT_SKIP.match(t):
        return False
    if t.startswith("/"):
        return False  # Bot komandasi
    # Topshiriq kalit so'zlari
    task_keywords = (
        "kerak", "bajaring", "tayyorla", "yuboring", "to'ldiring", "hisobot",
        "muddat", "deadline", "topshiriq", "ish", "vazifa", "jadval",
        "excel", "word", "fayl", "sana", "kun", "hafta",
    )
    t_lower = t.lower()
    if any(kw in t_lower for kw in task_keywords):
        return True
    # Uzun xabar — ehtimol topshiriq
    return len(t) >= 50


def _extract_title_and_body(text: str) -> tuple[str, str]:
    """#topshiriq trigger va 'Muddat:' qatorini olib tashlab sarlavha+tavsif qaytaradi."""
    cleaned = _TRIGGER.sub("", text, count=1).strip()
    lines   = [ln.rstrip() for ln in cleaned.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    title = lines[0].strip() if lines else "Nomsiz topshiriq"
    body_lines = [
        ln for ln in lines[1:]
        if not re.match(r"\s*(?:muddat(?:i)?|срок|deadline)\s*[:\-–]", ln, re.IGNORECASE)
    ]
    return title[:255], "\n".join(body_lines).strip()


def _auto_extract(text: str) -> tuple[str, str]:
    """AI bo'lmasa: birinchi qator = sarlavha."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "Topshiriq", ""
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
    if message.sender_chat:
        return True  # Kanal posti
    if message.from_user:
        return config.is_manager(message.from_user.id)
    return False


# ── Topshiriq yaratish (asosiy mantiq) ───────────────────────

async def _do_create_task(
    message: Message,
    album: list[Message] | None,
    db: Database,
    config: Config,
    bot: Bot,
    title: str,
    body: str,
    ai: Any = None,
) -> None:
    text        = message_text(message)
    deadline_dt = parse_deadline(text, config.tz)
    deadline_iso = deadline_dt.isoformat() if deadline_dt else None

    # AI bilan sarlavha/tavsif/muddat aniqlashtirish
    if ai and (not title or title == text[:255]):
        try:
            result = await ai.classify_message(
                text,
                has_files=bool(album or extract_file(message)),
            )
            if result.get("title"):
                title = result["title"][:255]
            if result.get("description"):
                body  = result["description"]
            if result.get("deadline") and not deadline_dt:
                deadline_dt  = parse_deadline(result["deadline"], config.tz)
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


# ── AI + heuristik: xabar topshiriqmi? ──────────────────────

async def _should_be_task(
    text: str, has_files: bool, ai: Any
) -> tuple[bool, str, str]:
    """
    Qaytaradi: (is_task, title, description)
    """
    if _TRIGGER.search(text):
        title, body = _extract_title_and_body(text)
        return True, title, body

    if ai:
        try:
            result = await ai.classify_message(text, has_files=has_files)
            is_task = bool(result.get("is_task"))
            conf    = result.get("confidence", 1.0)
            if not is_task and conf >= 0.7:
                return False, "", ""
            if not is_task and conf < 0.7 and not has_files:
                return False, "", ""
            if is_task or has_files:
                title = (result.get("title") or "").strip()
                desc  = (result.get("description") or "").strip()
                if not title:
                    title, desc = _auto_extract(text)
                return True, title[:255], desc
        except Exception:
            pass

    # Heuristik (AI yo'q yoki xato)
    if not _heuristic_is_task(text, has_files):
        return False, "", ""
    title, body = _auto_extract(text)
    return True, title, body


# ── Filtr: faqat rahbarning O'Z xabarlari (forward emas) ────

class _IsManagerTaskPost(BaseFilter):
    """Faqat rahbarning o'z topshiriq xabarlarini o'tkazadi.

    Forward qilingan xabarlar va oddiy xodim xabarlari REJECT qilinadi,
    shuning uchun ular submissions handleriga yetib boradi.
    """

    async def __call__(self, message: Message, config: Config) -> bool:
        # Forward = xodim topshirig'i, submissions handler uchun
        if message.forward_origin:
            return False
        if not _is_tasks_source(message, config):
            return False
        if not _is_manager_post(message, config):
            return False
        return True


# ── RAHBAR TOPSHIRIQ XABARLARI ───────────────────────────────

@router.message(
    _IsManagerTaskPost(),
    (F.chat.type.in_({"group", "supergroup"})) | (F.chat.type == "channel"),
)
async def handle_any_manager_message(
    message: Message,
    album: list[Message] | None,
    db: Database,
    config: Config,
    bot: Bot,
    ai: Any = None,
) -> None:
    if _cache_check(message.chat.id, message.message_id):
        return

    text      = message_text(message)
    has_files = bool(album or extract_file(message))

    if not text and not has_files:
        return

    is_task, title, body = await _should_be_task(text, has_files, ai)
    if not is_task:
        return

    await _do_create_task(message, album, db, config, bot, title, body, ai=ai)


# ── Kanal postlari ───────────────────────────────────────────

@router.channel_post()
async def handle_channel_post(
    message: Message,
    album: list[Message] | None,
    db: Database,
    config: Config,
    bot: Bot,
    ai: Any = None,
) -> None:
    if not config.tasks_channel_id or message.chat.id != config.tasks_channel_id:
        return
    if _cache_check(message.chat.id, message.message_id):
        return

    text      = message_text(message)
    has_files = bool(album or extract_file(message))

    if not text and not has_files:
        return

    is_task, title, body = await _should_be_task(text, has_files, ai)
    if not is_task:
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

    announce_msg = None
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
            sent         = await bot.send_media_group(config.execution_group_id, media)
            announce_msg = sent[0] if sent else None
        except Exception:
            announce_msg = await bot.send_message(config.execution_group_id, caption)
    else:
        announce_msg = await bot.send_message(config.execution_group_id, caption)

    if announce_msg:
        await db.set_announce_msg(task_id, announce_msg.message_id)

    # Har bir xodimning shaxsiy chatiga yangi topshiriq haqida xabar yuborish
    dm_text = f"📢 <b>Yangi topshiriq #{task_id}</b>\n\n<b>{title}</b>\n"
    if body:
        dm_text += f"\n{body}\n"
    dm_text += f"\n🗓 Muddat: {format_deadline(deadline_iso, config.tz)}"
    dm_text += "\n\n📱 Saytga kirib topshiriqni ko'ring va bajarib bo'lgach faylingizni yuboring."

    employees = await db.list_employees(active_only=True)
    for emp in employees:
        if emp["tg_id"] <= 0:
            continue
        await send_and_clean(bot, db, emp["tg_id"], dm_text)


# ── /topshiriqlar va /yopish ─────────────────────────────────

@router.message(Command("topshiriqlar", "tasks"))
async def cmd_list_tasks(
    message: Message, db: Database, config: Config
) -> None:
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
    lines.append("\nBatafsil: /svodka <code>N</code>")
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
    task    = await db.get_task(task_id)
    if not task:
        await message.reply("⚠️ Bunday topshiriq topilmadi.")
        return
    await db.close_task(task_id)
    await message.reply(f"🔒 Topshiriq #{task_id} yopildi.")
