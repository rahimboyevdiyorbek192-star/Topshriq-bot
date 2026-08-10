"""Topshiriqlarni qabul qilish: guruh, shaxsiy xabar, forward.

Muammolar va yechimlar:
  • DM fayl yo'qolishi: _pending_dm dict orqali fayl saqlanadi, tugma bosilganda qo'llaniladi.
  • Auto-register: ijro guruhida xabar yozgan har kim ro'yxatga tushadi.
  • Re-submission: xodim qayta yuborsa — eng yangi fayl saqlanadi.
  • Guruh fayllar: teglanmagan fayllar uchun bot topshiriq so'raydi.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ..config import Config
from ..database import Database
from ..utils.deadline import humanize_left
from ..utils.files import extract_file, message_text

router = Router()

_TASK_TAG = re.compile(
    r"#\s?(?:[tTтТ]\s?)?(\d+)"           # #T3, #t3, #3, # 3
    r"|(?:topshiriq|vazifa)\s*#?\s*(\d+)", # "topshiriq #3" yoki "topshiriq 3"
    re.IGNORECASE,
)

# DM topshirish: fayl kutilmoqda
# {user_id: {"file_id": ..., "file_name": ..., "note": ..., "msg_id": ...}}
_pending_dm: dict[int, dict] = {}

# Guruh: teglanmagan foto/video albom kutilmoqda
# {user_id: {"files": [(file_id, file_name, kind), ...], "note": ..., "msg_id": ...}}
_pending_group_album: dict[int, dict] = {}

# Guruh: teglanmagan hujjat kutilmoqda
# {token: {"file_id": ..., "file_name": ..., "file_kind": ..., "note": ..., "user_id": ..., "msg_id": ...}}
_pending_group_doc: dict[str, dict] = {}

# ── Smart kalit so'z matching ──────────────────────────────────

_CYR_TO_LAT: dict[str, str] = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'j',
    'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
    'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'x','ч':'ch',
    'ш':'sh','щ':'sh','ъ':'','ы':'i','ь':'','э':'e','ю':'yu','я':'ya',
    'ц':'ts','ў':'u','қ':'q','ғ':'g','ҳ':'h',
}

_STOPWORDS = frozenset({
    'bilan','uchun','kerak','yoki','hamda','lekin','qilish','qiladi',
    'boyin','haqida','uchun','yoqi','emas','yoqo','topshiriq',
    'fayl','docx','xlsx','jpeg','rasm','tasvir','ilova','rasmli',
    'hisobot','jadval','yuklash','hujjat','vazifa','keyin','yana',
    'bugun','sana','vaqt','yillik','oylik','hafta','boshqa',
})


def _transliterate(text: str) -> str:
    """Kirillcha Oʻzbek → Lotin (soddalashtirilgan). Lotin harflar o'zgarmaydi."""
    out: list[str] = []
    for ch in text.lower():
        out.append(_CYR_TO_LAT.get(ch, ch))
    return ''.join(out)


def _extract_kws(texts: list[str]) -> set[str]:
    """Matnlar ro'yxatidan transliteratsiya qilingan kalit so'zlar to'plami.

    Hashtag va _ belgilar ajratuvchi sifatida ishlatiladi.
    Faqat 4+ harfli, stop-so'z bo'lmagan so'zlar saqlanadi.
    """
    result: set[str] = set()
    for text in texts:
        if not text:
            continue
        cleaned = re.sub(r'[#_\-\.]+', ' ', text)
        words = re.findall(r'[a-zA-ZА-Яа-яЎўҚқҲҳҒғёЁ]{4,}', cleaned)
        for w in words:
            lat = _transliterate(w)
            if len(lat) >= 4 and lat not in _STOPWORDS:
                result.add(lat)
    return result


def _kw_match(a: str, b: str) -> bool:
    """Ikki kalit so'z mos keladimi: aniq teng YOKI 5+ harfli umumiy prefiks."""
    if a == b:
        return True
    n = min(len(a), len(b))
    return n >= 5 and a[:n] == b[:n]


def _match_tasks(tasks: list, kws: set[str]) -> list:
    """Kalit so'zlarga ko'ra topshiriqlarni baholaydi va saralaydi.

    Qaytaradi: mos topshiriqlar kamida 1 ball bilan, ball bo'yicha kamayish tartibida.
    Aniq moslik + 5+ harfli prefiks mosligini hisobga oladi.
    """
    if not kws:
        return []
    scored: list[tuple] = []
    for t in tasks:
        t_text = re.sub(r'[#_\-\.]+', ' ',
                        (t['title'] or '') + ' ' + (t['description'] or ''))
        t_kws = _extract_kws([t_text])
        score = sum(1 for kw in kws for tkw in t_kws if _kw_match(kw, tkw))
        if score > 0:
            scored.append((t, score))
    scored.sort(key=lambda x: -x[1])
    return [t for t, _ in scored]


def _full_name(user) -> str:
    return (user.full_name or user.first_name or "Nomsiz").strip()


async def _resolve_task_id(message: Message, db: Database) -> int | None:
    if message.reply_to_message:
        task = await db.get_task_by_announce(message.reply_to_message.message_id)
        if task:
            return task["id"]
    m = _TASK_TAG.search(message_text(message))
    if m:
        task_id = int(m.group(1) or m.group(2))
        task    = await db.get_task(task_id)
        if task:
            return task_id
    return None


async def _sector_total(task_id: int, db: Database) -> int:
    """Topshiriq sektoriga tegishli xodimlar soni (sektor yo'q = barchasi)."""
    task = await db.get_task(task_id)
    sector = task["target_sector"] if task else None
    return await db.count_employees(sector=sector)


async def _record_files(
    task_id: int,
    employee_id: int,
    files: list[tuple[str | None, str | None, str]],
    note: str | None,
    msg_id: int | None,
    db: Database,
) -> tuple[int, int]:
    """Bir xodimning bir nechta faylini topshiriq bilan bog'laydi.

    files = list of (file_id, file_name, kind).
    Returns (submitted_count, total_employees).
    """
    for i, (fid, fname, fkind) in enumerate(files):
        if i == 0:
            await db.add_submission(
                task_id=task_id, employee_id=employee_id,
                message_id=msg_id, note=note,
                file_id=fid, file_name=fname,
            )
        else:
            await db.add_submission_file(
                task_id=task_id, employee_id=employee_id,
                file_id=fid, file_name=fname, file_kind=fkind,
            )
    submitted = await db.submitted_employee_ids(task_id)
    total = await _sector_total(task_id, db)
    return len(submitted), total


async def _record_submission(
    message: Message,
    task_id: int,
    db: Database,
    file_id: str | None = None,
    file_name: str | None = None,
    note: str | None = None,
    employee=None,
) -> None:
    """Topshirishni DBga yozib, tasdiq xabari yuboradi.

    employee: forward qilingan holatda asl yuboruvchi (message.from_user o'rniga).
    """
    user = employee or message.from_user
    if not user:
        return

    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, _full_name(user), user.username)

    if file_id is None:
        info      = extract_file(message)
        file_id   = info[0] if info else None
        file_name = info[1] if info else None
    if note is None:
        note = message_text(message)[:1000] or None

    is_new = await db.add_submission(
        task_id=task_id,
        employee_id=user.id,
        message_id=message.message_id,
        note=note,
        file_id=file_id,
        file_name=file_name,
    )

    submitted = await db.submitted_employee_ids(task_id)
    total     = await _sector_total(task_id, db)
    verb      = "qabul qilindi" if is_new else "yangilandi"
    name_part = f" ({_full_name(user)})" if employee else ""
    try:
        await message.reply(
            f"✅ <b>#{task_id}-topshiriq</b>{name_part} bo'yicha ish {verb}.\n"
            f"({len(submitted)}/{total} xodim topshirdi)",
            disable_notification=True,
        )
    except Exception:
        pass


# ── /mening — o'z topshiriqlari holati ──────────────────────

@router.message(Command("mening", "my"))
async def cmd_my_tasks(
    message: Message, db: Database, config: Config
) -> None:
    user = message.from_user
    if not user:
        return
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.reply("📭 Hozircha ochiq topshiriqlar yo'q.")
        return
    lines = ["📌 <b>Mening topshiriqlarim holati:</b>", ""]
    for t in tasks:
        submitted = await db.submitted_employee_ids(t["id"])
        mark = "✅ bajarilgan" if user.id in submitted else "❌ bajarilmagan"
        left = humanize_left(t["deadline"], config.tz)
        lines.append(f"<b>#{t['id']}</b> {t['title']} — {mark}\n   {left}")
    await message.reply("\n".join(lines))


# ── GURUH: ijro guruhida topshiriq qabul qilish ──────────────

@router.message(
    (F.chat.type.in_({"group", "supergroup"}))
    & ~F.from_user.is_bot
    & (F.text | F.caption | F.document | F.photo | F.video | F.audio | F.voice)
)
async def handle_group_submission(
    message: Message, db: Database, config: Config,
    album: list[Message] | None = None,
) -> None:
    user = message.from_user
    if not user:
        return

    # ── Asl yuboruvchini aniqlash (rahbar forward qilgan bo'lsa) ──
    # Rahbar xodimning faylini guruhga forward qilsa → xodim hisoblanadi.
    effective_user = user
    if config.is_manager(user.id) and message.forward_origin:
        origin_user = getattr(message.forward_origin, "sender_user", None)
        if origin_user and not origin_user.is_bot:
            effective_user = origin_user

    # ── Guruh filtri ──────────────────────────────────────────────
    if config.execution_group_id is not None:
        if message.chat.id != config.execution_group_id:
            return
    else:
        if config.tasks_channel_id and message.chat.id == config.tasks_channel_id:
            return
        if config.tasks_group_id and message.chat.id == config.tasks_group_id:
            # Rahbarning OZ xabari (forward emas) — o'tkazib yuboramiz
            if config.is_manager(user.id) and effective_user is user:
                return

    # Auto-register effective_user
    emp = await db.get_employee(effective_user.id)
    if not emp:
        await db.add_employee(effective_user.id, _full_name(effective_user), effective_user.username)

    euid = effective_user.id
    emp_arg = effective_user if effective_user is not user else None

    task_id = await _resolve_task_id(message, db)
    note = message_text(message)[:1000] or None

    # Albomning boshqa xabarlarida ham #T teg bo'lishi mumkin
    if task_id is None and album:
        for _m in album:
            _txt = message_text(_m)
            if not _txt:
                continue
            _tag = _TASK_TAG.search(_txt)
            if _tag:
                _tid = int(_tag.group(1))
                _task = await db.get_task(_tid)
                if _task:
                    task_id = _tid
                    note = _txt[:1000]
                    break

    if task_id is not None:
        # Topshiriq teglanган — barcha albom fayllarini birga saqlash
        if album:
            files = [
                (fi[0], fi[1], fi[2])
                for m in album
                if (fi := extract_file(m)) is not None
            ]
            if files:
                submitted, total = await _record_files(
                    task_id, euid, files, note, message.message_id, db
                )
                name_part = f" ({_full_name(effective_user)})" if emp_arg else ""
                try:
                    await message.reply(
                        f"✅ <b>#{task_id}-topshiriq</b>{name_part}: {len(files)} ta fayl qabul qilindi.\n"
                        f"({submitted}/{total} xodim topshirdi)",
                        disable_notification=True,
                    )
                except Exception:
                    pass
                return
        await _record_submission(message, task_id, db, employee=emp_arg)
        return

    # Topshiriq ko'rsatilmagan — bot so'raydi
    tasks = await db.list_open_tasks()
    if not tasks:
        return  # Ochiq topshiriqlar yo'q — jim o'tamiz

    all_msgs = album if album else [message]
    media_files: list[tuple[str | None, str | None, str]] = []
    doc_files: list[tuple[str | None, str | None, str]] = []

    for m in all_msgs:
        info = extract_file(m)
        if not info:
            continue
        fid, fname, kind = info
        if kind in ("photo", "video", "voice"):
            media_files.append((fid, fname, kind))
        else:
            doc_files.append((fid, fname, kind))

    if not media_files and not doc_files:
        return  # Faqat matn — e'tibor bermaymiz

    if len(tasks) == 1:
        # Bitta ochiq topshiriq — avtomatik bog'laymiz
        task_id = tasks[0]["id"]
        all_files = media_files + doc_files
        submitted, total = await _record_files(
            task_id, euid, all_files, note, message.message_id, db
        )
        name_part = f" ({_full_name(effective_user)})" if emp_arg else ""
        try:
            await message.reply(
                f"✅ <b>#{task_id}-topshiriq</b>{name_part} ga {len(all_files)} ta fayl qabul qilindi.\n"
                f"({submitted}/{total} xodim topshirdi)",
                disable_notification=True,
            )
        except Exception:
            pass
        return

    # ── Smart kalit so'z matching ──────────────────────────────
    # Fayl nomlari + caption + albom captionlari → kalit so'zlar
    kw_sources: list[str] = [note or ""]
    for _fid, _fn, _fk in media_files + doc_files:
        if _fn:
            kw_sources.append(_fn)
    if album:
        for _am in album:
            _atxt = message_text(_am)
            if _atxt and _atxt not in kw_sources:
                kw_sources.append(_atxt)

    kws = _extract_kws(kw_sources)
    matched = _match_tasks(tasks, kws)

    if len(matched) == 1:
        # Yagona kalit so'z mos keldi — so'ramasdan avtomatik biriktir
        task_id = matched[0]["id"]
        all_files = media_files + doc_files
        submitted, total = await _record_files(
            task_id, euid, all_files, note, message.message_id, db
        )
        name_part = f" ({_full_name(effective_user)})" if emp_arg else ""
        try:
            await message.reply(
                f"🔍 <b>#{task_id}-topshiriq</b>{name_part} nomi bilan mos keldi.\n"
                f"✅ {len(all_files)} ta fayl qabul qilindi.\n"
                f"({submitted}/{total} xodim topshirdi)",
                disable_notification=True,
            )
        except Exception:
            pass
        return

    if matched:
        # Bir nechta mos topshiriq — faqat moslarini tugmalarda ko'rsat
        tasks = matched
    # matched bo'lmasa: hamma ochiq topshiriqlar (standart xatti-harakat)

    # Bir nechta topshiriq — so'rov tugmalarini yuboramiz
    rows = [
        [InlineKeyboardButton(
            text=f"#{t['id']} {t['title'][:38]}",
            callback_data=f"grp_al:{t['id']}:{euid}",
        )]
        for t in tasks[:10]
    ]

    # Foto/video albom — bitta savol
    if media_files:
        _pending_group_album[euid] = {
            "files": media_files,
            "note": note,
            "msg_id": message.message_id,
        }
        try:
            await message.reply(
                f"📸 <b>{len(media_files)} ta rasm/video</b> — qaysi topshiriq uchun?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                disable_notification=True,
            )
        except Exception:
            pass

    # Hujjatlar — har biri alohida savol
    for fid, fname, fkind in doc_files:
        token = uuid.uuid4().hex
        _pending_group_doc[token] = {
            "file_id":   fid,
            "file_name": fname,
            "file_kind": fkind,
            "note":      note,
            "user_id":   euid,
            "msg_id":    message.message_id,
        }
        doc_rows = [
            [InlineKeyboardButton(
                text=f"#{t['id']} {t['title'][:38]}",
                callback_data=f"grp_doc:{t['id']}:{token}",
            )]
            for t in tasks[:10]
        ]
        display = fname or fkind or "Fayl"
        try:
            await message.reply(
                f"📎 <b>{display}</b> — qaysi topshiriq uchun?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=doc_rows),
                disable_notification=True,
            )
        except Exception:
            pass


# ── DM: xodim botga shaxsiy xabar yuboradi ───────────────────

@router.message(
    (F.chat.type == "private")
    & ~F.from_user.is_bot
    & (F.document | F.photo | F.video | F.audio | F.voice | F.caption | F.text)
)
async def handle_private_submission(
    message: Message, db: Database, config: Config, bot: Bot, ai: Any = None
) -> None:
    user = message.from_user
    if not user:
        return
    if config.is_manager(user.id):
        return  # Rahbar komandalar ishlatadi

    text = message_text(message)

    # Bot komandasi bo'lsa o'tkazib yuboramiz (boshqa handler ushlab qolgan bo'ladi)
    if text.startswith("/"):
        return

    # Topshiriq raqami ko'rsatilganmi? (#T3 yoki reply)
    task_id = await _resolve_task_id(message, db)
    if task_id:
        await _record_submission(message, task_id, db)
        _pending_dm.pop(user.id, None)
        return

    # Faylni pending ga saqlash
    info = extract_file(message)
    _pending_dm[user.id] = {
        "file_id":   info[0] if info else None,
        "file_name": info[1] if info else None,
        "note":      text[:1000] or None,
        "msg_id":    message.message_id,
    }

    # Ochiq topshiriqlarni ko'rsatib tanlash so'raymiz
    tasks = await db.list_open_tasks()
    if not tasks:
        await message.reply(
            "📭 Hozircha ochiq topshiriqlar yo'q.\n"
            "Topshiriq raqamini #T1 ko'rinishida yozing."
        )
        return

    if len(tasks) == 1:
        # Bitta topshiriq — avtomatik bog'laymiz
        await _record_submission(
            message, tasks[0]["id"], db,
            file_id=_pending_dm[user.id]["file_id"],
            file_name=_pending_dm[user.id]["file_name"],
            note=_pending_dm[user.id]["note"],
        )
        _pending_dm.pop(user.id, None)
        return

    # Tugmalar bilan tanlash
    rows = [
        [InlineKeyboardButton(
            text=f"#{t['id']} {t['title'][:38]}",
            callback_data=f"dm_submit:{t['id']}",
        )]
        for t in tasks[:10]
    ]
    await message.reply(
        "📋 <b>Qaysi topshiriq uchun?</b>\n"
        "Faylingiz saqlanib turibdi — topshiriqni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("grp_al:"))
async def cb_grp_album(callback: CallbackQuery, db: Database) -> None:
    parts = callback.data.split(":")
    task_id = int(parts[1])
    user_id = int(parts[2])

    pending = _pending_group_album.pop(user_id, {})
    files   = pending.get("files", [])
    note    = pending.get("note")
    msg_id  = pending.get("msg_id")

    if not files:
        await callback.answer("⚠️ Fayl topilmadi (muhlat o'tgan bo'lishi mumkin).")
        return

    emp = await db.get_employee(user_id)
    if not emp:
        await callback.answer("⚠️ Xodim topilmadi.")
        return

    submitted, total = await _record_files(task_id, user_id, files, note, msg_id, db)
    await callback.message.edit_text(
        f"✅ <b>#{task_id}-topshiriq</b> ga {len(files)} ta rasm qabul qilindi.\n"
        f"({submitted}/{total} xodim topshirdi)"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("grp_doc:"))
async def cb_grp_doc(callback: CallbackQuery, db: Database) -> None:
    parts   = callback.data.split(":", 2)
    task_id = int(parts[1])
    token   = parts[2]

    pending   = _pending_group_doc.pop(token, {})
    file_id   = pending.get("file_id")
    file_name = pending.get("file_name")
    file_kind = pending.get("file_kind") or "document"
    note      = pending.get("note")
    user_id   = pending.get("user_id")
    msg_id    = pending.get("msg_id")

    if not user_id:
        await callback.answer("⚠️ Ma'lumot topilmadi (muhlat o'tgan bo'lishi mumkin).")
        return

    emp = await db.get_employee(user_id)
    if not emp:
        await callback.answer("⚠️ Xodim topilmadi.")
        return

    existing = await db.get_submission(task_id, user_id)
    if existing:
        await db.add_submission_file(
            task_id=task_id, employee_id=user_id,
            file_id=file_id, file_name=file_name, file_kind=file_kind,
        )
    else:
        await db.add_submission(
            task_id=task_id, employee_id=user_id,
            message_id=msg_id, note=note,
            file_id=file_id, file_name=file_name,
        )

    submitted = await db.submitted_employee_ids(task_id)
    total     = await _sector_total(task_id, db)
    display   = file_name or file_kind or "Fayl"
    await callback.message.edit_text(
        f"✅ <b>#{task_id}-topshiriq</b>: {display} qabul qilindi.\n"
        f"({len(submitted)}/{total} xodim topshirdi)"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dm_submit:"))
async def cb_dm_submit(
    callback: CallbackQuery, db: Database
) -> None:
    task_id = int(callback.data.split(":")[1])
    user    = callback.from_user

    # Pending faylni olamiz
    pending   = _pending_dm.pop(user.id, {})
    file_id   = pending.get("file_id")
    file_name = pending.get("file_name")
    note      = pending.get("note") or "DM orqali topshirildi"

    emp = await db.get_employee(user.id)
    if not emp:
        await db.add_employee(user.id, _full_name(user), user.username)

    is_new = await db.add_submission(
        task_id=task_id,
        employee_id=user.id,
        message_id=pending.get("msg_id"),
        note=note,
        file_id=file_id,
        file_name=file_name,
    )

    submitted = await db.submitted_employee_ids(task_id)
    total     = await _sector_total(task_id, db)
    verb      = "qabul qilindi" if is_new else "yangilandi"

    file_info = f"📎 Fayl: {file_name}" if file_name else ("📸 Rasm" if file_id else "📝 Matn")
    extra = (
        f"\n\n{file_info}\n"
        "Boshqa fayl yubormoqchi bo'lsangiz — "
        f"<code>#T{task_id}</code> deb boshlab yuboring."
        if not file_id
        else f"\n\n{file_info}"
    )

    await callback.message.edit_text(
        f"✅ <b>#{task_id}-topshiriq</b> bo'yicha ishingiz {verb}.\n"
        f"({len(submitted)}/{total} xodim topshirdi){extra}"
    )
    await callback.answer()


# ── FORWARD: rahbar xodim faylini botga forward qiladi ───────

@router.message(
    (F.chat.type == "private")
    & F.forward_origin.IS_NOT_NONE
)
async def handle_forward_from_manager(
    message: Message, db: Database, config: Config
) -> None:
    user = message.from_user
    if not user or not config.is_manager(user.id):
        return

    origin = message.forward_origin
    if not origin or not hasattr(origin, "sender_user") or not origin.sender_user:
        return
    sender = origin.sender_user
    if sender.is_bot:
        return

    task_id = await _resolve_task_id(message, db)
    if task_id is None:
        tasks = await db.list_open_tasks()
        if len(tasks) == 1:
            task_id = tasks[0]["id"]
        else:
            ids_str = ", ".join(f"#{t['id']}" for t in tasks[:5])
            await message.reply(
                f"ℹ️ Qaysi topshiriq uchun?\n"
                f"Ochiq topshiriqlar: {ids_str}\n"
                f"Javob xabarida <code>#T[raqam]</code> yozing."
            )
            return

    emp = await db.get_employee(sender.id)
    if not emp:
        full_name = _full_name(sender)
        await db.add_employee(sender.id, full_name, sender.username)

    info      = extract_file(message)
    file_id   = info[0] if info else None
    file_name = info[1] if info else None
    note      = message_text(message)[:1000] or "Rahbar orqali qabul qilindi"

    is_new   = await db.add_submission(
        task_id=task_id, employee_id=sender.id,
        message_id=message.message_id,
        note=note, file_id=file_id, file_name=file_name,
    )
    emp_name = sender.full_name or "Xodim"
    verb     = "qabul qilindi" if is_new else "yangilandi"
    await message.reply(
        f"✅ <b>{emp_name}</b> uchun #{task_id}-topshiriq {verb}."
    )
