"""Telegram Mini App uchun aiohttp HTTP server."""
from __future__ import annotations

import hashlib
import hmac as _hmac
import io
import json
import logging
import urllib.parse
import zipfile
from pathlib import Path

import httpx
import openpyxl
from aiohttp import web

from .config import Config
from .database import Database
from .utils.deadline import format_deadline

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


# ── Parol tekshiruvi ───────────────────────────────────────
def _check_manager_password(plain: str, stored: str) -> bool:
    return _hmac.compare_digest(plain, stored)


# ── Fayl nomi yordamchilari ────────────────────────────────
def _safe_filename(name: str) -> str:
    """Yo'l ajratgichlari va boshqaruv belgilarini olib tashlaydi."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '"\r\n')
    return name.strip() or "fayl"


def _content_disposition(fname: str) -> str:
    """Kirill/lotin harflari uchun RFC 5987 sarlavhasi."""
    ascii_fb = fname.encode("ascii", "ignore").decode() or "fayl"
    quoted   = urllib.parse.quote(fname, safe="")
    return f"attachment; filename=\"{ascii_fb}\"; filename*=UTF-8''{quoted}"


def _unique_arcname(folder: str, fname: str, used: set[str]) -> str:
    """ZIP ichida takrorlanmas yo'l qaytaradi: hisobot.docx → hisobot_1.docx"""
    stem, dot, ext = fname.rpartition(".")
    if not dot:              # kengaytmasiz fayl: rpartition ('', '', 'nom') qaytaradi
        stem, ext = fname, ""
    arc, n = f"{folder}/{fname}", 0
    while arc in used:
        n += 1
        arc = f"{folder}/{stem}_{n}.{ext}" if ext else f"{folder}/{stem}_{n}"
    used.add(arc)
    return arc


# ── Rasm tekshiruvi (EXIF) ────────────────────────────────
def _extract_exif_date(data: bytes, filename: str) -> str | None:
    """JPG/JPEG rasimidan EXIF DateTimeOriginal sanani oladi."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg"):
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        if not exif:
            return None
        for tag_id in (36867, 36868, 306):   # DateTimeOriginal, DateTimeDigitized, DateTime
            val = exif.get(tag_id)
            if val:
                return str(val)
    except Exception:
        pass
    return None


def _is_old_photo(exif_str: str | None, submitted_at: str) -> bool:
    """EXIF sana topshirish vaqtidan 24 soatdan oldin bo'lsa True qaytaradi."""
    if not exif_str:
        return False
    try:
        from datetime import datetime as _dt, timedelta as _td
        exif_dt = _dt.strptime(exif_str, "%Y:%m:%d %H:%M:%S")
        sub_dt  = _dt.fromisoformat(submitted_at)
        if sub_dt.tzinfo:
            sub_dt = sub_dt.replace(tzinfo=None)
        return (sub_dt - exif_dt) > _td(hours=24)
    except Exception:
        return False


# ── initData tekshirish ────────────────────────────────────
def _validate_init_data(init_data: str, bot_token: str) -> dict | None:
    if not init_data:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    hash_val = parsed.pop("hash", None)
    if not hash_val:
        return None
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = _hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc   = _hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(calc, hash_val):
        return None
    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except Exception:
        return None


async def _auth_full(request: web.Request) -> tuple[dict | None, bool]:
    """(user_dict, is_manager) yoki (None, False) qaytaradi."""
    config: Config = request.app["config"]
    db: Database   = request.app["db"]

    # 1. Telegram initData
    init_data = (
        request.headers.get("X-Telegram-Init-Data", "")
        or request.rel_url.query.get("init", "")
    )
    if init_data:
        user = _validate_init_data(init_data, config.bot_token)
        if user:
            return user, config.is_manager(user.get("id", 0))

    # 2. Web session token
    token = (
        request.headers.get("X-Session-Token", "")
        or request.rel_url.query.get("token", "")
    )
    if token:
        session = await db.get_web_session(token)
        if session:
            if session["is_manager"]:
                return {"id": 0, "first_name": "Rahbar"}, True
            emp = await db.get_employee(session["tg_id"])
            if emp and emp["active"]:
                return (
                    {"id": emp["tg_id"], "first_name": emp["full_name"]},
                    config.is_manager(emp["tg_id"]),
                )
    return None, False


def _cors(resp: web.Response) -> web.Response:
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = (
        "X-Telegram-Init-Data, X-Session-Token, Content-Type"
    )
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp


def _json(data, status: int = 200) -> web.Response:
    return _cors(web.json_response(data, status=status))


# ── Umumiy ────────────────────────────────────────────────

async def handle_options(request: web.Request) -> web.Response:
    return _cors(web.Response(status=200))


async def handle_index(request: web.Request) -> web.Response:
    f = STATIC_DIR / "index.html"
    return web.FileResponse(f) if f.exists() else web.Response(
        text="Mini App yuklanmoqda...", content_type="text/html"
    )


# ── Auth ───────────────────────────────────────────────────

async def handle_login(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "JSON kerak"}, 400)

    phone    = data.get("phone", "").strip()
    password = data.get("password", "")
    if not phone or not password:
        return _json({"error": "Telefon va parol kerak"}, 400)

    db: Database   = request.app["db"]
    config: Config = request.app["config"]

    # Rahbar tekshiruvi
    mgr_phone  = config.webapp_manager_phone.replace(" ", "").replace("-", "")
    user_phone = phone.replace(" ", "").replace("-", "")
    if mgr_phone and user_phone == mgr_phone:
        if not config.webapp_manager_password:
            return _json({"error": "Rahbar paroli sozlanmagan"}, 500)
        if not _check_manager_password(password, config.webapp_manager_password):
            return _json({"error": "Noto'g'ri parol"}, 401)
        token = await db.create_web_session(tg_id=0, is_manager=True)
        return _json({"ok": True, "token": token, "role": "manager", "name": "Rahbar"})

    # Xodim tekshiruvi
    emp = await db.get_employee_by_login_phone(phone)
    if not emp:
        return _json({"error": "Bunday telefon raqam topilmadi"}, 401)
    if not emp["password_hash"]:
        return _json({"error": "Parol o'rnatilmagan, rahbarga murojaat qiling"}, 401)
    if not Database.verify_password(password, emp["password_hash"]):
        return _json({"error": "Noto'g'ri parol"}, 401)
    if not emp["active"]:
        return _json({"error": "Hisobingiz faol emas"}, 403)

    is_mgr = config.is_manager(emp["tg_id"])
    token  = await db.create_web_session(tg_id=emp["tg_id"], is_manager=is_mgr)
    return _json({
        "ok":    True,
        "token": token,
        "role":  "manager" if is_mgr else "employee",
        "name":  emp["full_name"],
    })


async def handle_logout(request: web.Request) -> web.Response:
    token = (
        request.headers.get("X-Session-Token", "")
        or request.rel_url.query.get("token", "")
    )
    if token:
        db: Database = request.app["db"]
        await db.delete_web_session(token)
    return _json({"ok": True})


async def handle_me(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    return _json({"user": user, "is_manager": is_mgr})


# ── Topshiriqlar ───────────────────────────────────────────

async def handle_tasks(request: web.Request) -> web.Response:
    user, is_manager = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)

    db: Database = request.app["db"]
    user_id      = user["id"]
    tasks        = await db.list_open_tasks()
    total_emp    = await db.count_employees()
    result       = []

    for t in tasks:
        submitted_ids = await db.submitted_employee_ids(t["id"])
        task_files    = await db.get_task_files(t["id"])
        my_sub        = await db.get_submission(t["id"], user_id)

        result.append({
            "id":              t["id"],
            "title":           t["title"],
            "description":     t["description"] or "",
            "deadline":        t["deadline"] or "",
            "submitted_by_me": user_id in submitted_ids,
            "done_count":      len(submitted_ids),
            "total_count":     total_emp,
            "files": [
                {
                    "file_id":   f["file_id"],
                    "file_name": f["file_name"] or "fayl",
                    "kind":      f["file_kind"],
                }
                for f in task_files
            ],
            "my_submission": {
                "file_name":    my_sub["file_name"],
                "note":         my_sub["note"],
                "submitted_at": my_sub["submitted_at"],
            } if my_sub else None,
        })

    return _json({"tasks": result, "is_manager": is_manager, "user": user})


async def handle_task_detail(request: web.Request) -> web.Response:
    """Rahbar uchun topshiriq bo'yicha batafsil svodka."""
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    task_id = int(request.match_info.get("task_id", "0"))
    db: Database = request.app["db"]

    task = await db.get_task(task_id)
    if not task:
        return _json({"error": "Topshiriq topilmadi"}, 404)

    submissions = await db.get_all_task_submissions(task_id)
    total_emp   = await db.count_employees()
    task_files  = await db.get_task_files(task_id)

    return _json({
        "task": {
            "id":          task["id"],
            "title":       task["title"],
            "description": task["description"] or "",
            "deadline":    task["deadline"] or "",
        },
        "submissions": [
            {
                "employee_id":  s["employee_id"],
                "full_name":    s["full_name"] or f"#{s['employee_id']}",
                "username":     s["username"],
                "file_id":      s["file_id"],
                "file_name":    s["file_name"],
                "note":         s["note"],
                "submitted_at": s["submitted_at"],
                "exif_date":    s["exif_date"],
                "is_old_photo": _is_old_photo(s["exif_date"], s["submitted_at"] or ""),
            }
            for s in submissions
        ],
        "total_count":     total_emp,
        "submitted_count": len(submissions),
        "task_files": [
            {"file_id": f["file_id"], "file_name": f["file_name"] or "fayl", "kind": f["file_kind"]}
            for f in task_files
        ],
    })


async def handle_task_zip(request: web.Request) -> web.Response:
    """Topshiriq uchun barcha fayllarni ZIP qilib yuboradi."""
    user, is_mgr = await _auth_full(request)
    if not user:
        return web.Response(status=401)
    if not is_mgr:
        return web.Response(status=403)

    task_id = int(request.match_info.get("task_id", "0"))
    db: Database   = request.app["db"]
    bot            = request.app["bot"]
    config: Config = request.app["config"]

    task = await db.get_task(task_id)
    if not task:
        return web.Response(status=404)

    submissions = await db.get_all_task_submissions(task_id)
    extra_files = await db.get_all_submission_files_for_task(task_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Excel svodka
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Svodka"
        ws.column_dimensions["A"].width = 4
        ws.column_dimensions["B"].width = 28
        ws.column_dimensions["C"].width = 10
        ws.column_dimensions["D"].width = 20
        ws.column_dimensions["E"].width = 30
        ws.column_dimensions["F"].width = 40
        ws.append(["#", "F.I.O.", "Topshirdi", "Vaqt", "Fayl", "Izoh"])
        for i, s in enumerate(submissions, 1):
            ws.append([
                i,
                s["full_name"] or f"#{s['employee_id']}",
                "Ha",
                s["submitted_at"],
                s["file_name"] or "",
                s["note"] or "",
            ])
        xl_buf = io.BytesIO()
        wb.save(xl_buf)
        zf.writestr("svodka.xlsx", xl_buf.getvalue())

        # Fayllarni Telegram dan yuklash
        async with httpx.AsyncClient(timeout=30) as client:
            used: set[str] = set()

            async def _dl(file_id: str, file_name: str | None, folder: str) -> None:
                if not file_id:
                    return
                try:
                    tg_file  = await bot.get_file(file_id)
                    file_url = (
                        f"https://api.telegram.org/file/bot"
                        f"{config.bot_token}/{tg_file.file_path}"
                    )
                    r = await client.get(file_url)
                    r.raise_for_status()
                    fname = _safe_filename(
                        file_name or (tg_file.file_path or "").split("/")[-1]
                    )
                    zf.writestr(_unique_arcname(folder, fname, used), r.content)
                except Exception as exc:
                    logger.warning("ZIP fayl yuklanmadi %s: %s", file_id, exc)

            for s in submissions:
                if s["file_id"]:
                    folder = _safe_filename(s["full_name"] or str(s["employee_id"]))
                    await _dl(s["file_id"], s["file_name"], folder)

            for ef in extra_files:
                folder = _safe_filename(ef["full_name"] or str(ef["employee_id"]))
                await _dl(ef["file_id"], ef["file_name"], folder)

    buf.seek(0)
    safe = _safe_filename(task["title"][:40])
    return _cors(web.Response(
        body=buf.getvalue(),
        content_type="application/zip",
        headers={"Content-Disposition": _content_disposition(f"topshiriq_{task_id}_{safe}.zip")},
    ))


# ── Topshiriq yaratish (rahbar) ────────────────────────────

async def handle_tasks_create(request: web.Request) -> web.Response:
    """Rahbar uchun yangi topshiriq yaratadi."""
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    try:
        data = await request.json()
    except Exception:
        return _json({"error": "JSON kerak"}, 400)

    title = (data.get("title") or "").strip()
    if not title:
        return _json({"error": "Topshiriq nomi majburiy"}, 400)

    description = (data.get("description") or "").strip() or None
    deadline    = (data.get("deadline") or "").strip() or None

    db: Database   = request.app["db"]
    config: Config = request.app["config"]

    task_id = await db.create_task(
        title=title,
        description=description,
        deadline=deadline,
        created_by=user.get("id"),
        src_chat_id=None,
        src_msg_id=None,
    )

    try:
        bot = request.app["bot"]
        if config.execution_group_id:
            dl_text = format_deadline(deadline, config.tz) if deadline else "belgilanmagan"
            text = (
                f"📋 <b>Yangi topshiriq #{task_id}</b>\n"
                f"📌 {title}\n"
                f"📅 Muddat: {dl_text}"
            )
            if description:
                text += f"\n📝 {description[:200]}"
            await bot.send_message(config.execution_group_id, text)
    except Exception as exc:
        logger.warning("Topshiriq e'lon xato: %s", exc)

    return _json({"ok": True, "task_id": task_id})


# ── Fayl topshirish ────────────────────────────────────────

async def handle_submit(request: web.Request) -> web.Response:
    user, _ = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if user["id"] == 0:
        # Rahbar web sessiyasi (tg_id=0) — topshiriq topshira olmaydi,
        # aks holda svodkada "#0" nomli soxta ijrochi paydo bo'lar edi.
        return _json({"error": "Rahbar topshiriq topshira olmaydi"}, 403)

    db: Database   = request.app["db"]
    config: Config = request.app["config"]
    bot            = request.app["bot"]

    # ── 1. So'rovni o'qish ────────────────────────────────
    # Fayllar avval xotiraga yig'iladi: multipart'da task_id fayllardan
    # keyin kelishi mumkin, u holda caption'da "#None" chiqib qolardi.
    task_id_raw: str | None = None
    note: str | None        = None
    pending: list[tuple[str, bytes, str | None]] = []  # (fname, data, exif_date)

    try:
        if (request.content_type or "").startswith("multipart/"):
            reader = await request.multipart()
            async for field in reader:
                if field.name == "task_id":
                    task_id_raw = (await field.read(decode=True)).decode("utf-8", "ignore")
                elif field.name == "note":
                    note = (await field.read(decode=True)).decode("utf-8", "ignore")[:1000]
                elif field.name in ("file", "files", "files[]"):
                    fdata = await field.read()
                    if fdata:
                        fname = field.filename or "fayl"
                        pending.append((fname, fdata, _extract_exif_date(fdata, fname)))
        else:
            # Faylsiz (faqat izohli) topshirish oddiy forma sifatida ham kelishi mumkin
            form        = await request.post()
            task_id_raw = form.get("task_id")
            raw_note    = form.get("note")
            note        = str(raw_note)[:1000] if raw_note else None
    except Exception as exc:
        logger.warning("Submit so'rovini o'qib bo'lmadi: %s", exc)
        return _json({"error": "So'rovni o'qib bo'lmadi"}, 400)

    # ── 2. Tekshiruv ──────────────────────────────────────
    try:
        task_id = int(task_id_raw)
    except (TypeError, ValueError):
        return _json({"error": "task_id noto'g'ri"}, 400)

    task = await db.get_task(task_id)
    if not task:
        return _json({"error": "Topshiriq topilmadi"}, 404)
    if not pending and not (note or "").strip():
        return _json({"error": "Fayl yoki izoh kerak"}, 400)

    user_id   = user["id"]
    full_name = (
        f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "Xodim"
    )
    if not await db.get_employee(user_id):
        await db.add_employee(user_id, full_name, user.get("username"))

    # ── 3. Fayllarni Telegram'ga yuborish ─────────────────
    uploaded: list[tuple[str, str, str | None]] = []   # (file_id, fname, exif_date)
    msg_ids_to_delete: list[int] = []
    send_chat = config.execution_group_id or (
        config.manager_ids[0] if config.manager_ids else None
    )
    if pending and send_chat:
        from aiogram.types import BufferedInputFile
        uname = f"@{user['username']}" if user.get("username") else full_name
        for idx, (fname, fdata, exif_d) in enumerate(pending):
            caption = (
                f"📱 <b>Mini App topshiriq</b>\n👤 {uname}\n📋 #{task_id}"
                if idx == 0 else None
            )
            try:
                sent = await bot.send_document(
                    send_chat, BufferedInputFile(fdata, filename=fname), caption=caption
                )
            except Exception as exc:
                logger.error("Fayl Telegram'ga yuborilmadi (%s): %s", fname, exc)
                return _json({"error": f"Fayl yuborilmadi: {fname}"}, 502)
            if sent and sent.document:
                uploaded.append((sent.document.file_id, fname, exif_d))
                msg_ids_to_delete.append(sent.message_id)

    # ── 4. Bazaga yozish ──────────────────────────────────
    try:
        await db.add_submission(
            task_id=task_id, employee_id=user_id, message_id=None,
            note=(note or "").strip() or "Mini App orqali yuborildi",
            file_id=uploaded[0][0] if uploaded else None,
            file_name=uploaded[0][1] if uploaded else None,
            exif_date=uploaded[0][2] if uploaded else None,
        )
        for fid, fname, exif_d in uploaded[1:]:
            await db.add_submission_file(task_id, user_id, fid, fname, exif_date=exif_d)
    except Exception as exc:
        logger.error("Submit bazaga yozilmadi: %s", exc, exc_info=True)
        return _json({"error": "Ma\'lumotni saqlab bo\'lmadi"}, 500)

    # ── 5. Guruhni toza saqlash: saqlagandan keyin xabarlarni o'chiramiz ─
    for mid in msg_ids_to_delete:
        try:
            await bot.delete_message(send_chat, mid)
        except Exception:
            pass   # o'chirish huquqi bo'lmasa yoki xabar topilmasa muammo emas

    submitted = await db.submitted_employee_ids(task_id)
    return _json({
        "ok":          True,
        "done_count":  len(submitted),
        "total_count": await db.count_employees(),
    })


# ── Fayl proxy ─────────────────────────────────────────────

async def handle_file_proxy(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return web.Response(status=401)

    file_id = request.match_info.get("file_id", "")
    bot     = request.app["bot"]
    db: Database   = request.app["db"]
    config: Config = request.app["config"]

    # Egalik tekshiruvi: xodim faqat namuna fayllarni va O'ZI yuborgan
    # fayllarni yuklay oladi. Rahbar hammasini ko'ra oladi.
    kind, owner_id = await db.file_access_owner(file_id)
    if kind == "unknown":
        return web.Response(status=404)
    if kind == "submission" and not is_mgr and owner_id != user["id"]:
        logger.warning(
            "Ruxsatsiz fayl so'rovi: user=%s owner=%s file=%s",
            user["id"], owner_id, file_id[:24],
        )
        return web.Response(status=403)

    try:
        tg_file  = await bot.get_file(file_id)
        file_url = (
            f"https://api.telegram.org/file/bot{config.bot_token}/{tg_file.file_path}"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(file_url)
            r.raise_for_status()
        # Haqiqiy fayl nomini ?name= dan olamiz, aks holda Telegram nomi ishlatiladi
        fname = _safe_filename(
            request.rel_url.query.get("name", "")
            or (tg_file.file_path.split("/")[-1] if tg_file.file_path else "fayl")
        )
        ctype = r.headers.get("content-type", "application/octet-stream")
        return _cors(web.Response(
            body=r.content, content_type=ctype,
            headers={"Content-Disposition": _content_disposition(fname)},
        ))
    except Exception as exc:
        logger.error("Fayl proxy xatosi: %s", exc)
        return web.Response(status=500)


# ── Xodimlar boshqaruvi (rahbar) ───────────────────────────

async def handle_employees_list(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)
    db: Database = request.app["db"]
    emps = await db.list_employees_web()
    return _json({"employees": [
        {
            "tg_id":        e["tg_id"],
            "full_name":    e["full_name"],
            "position":     e["position"] or "",
            "login_phone":  e["login_phone"] or "",
            "username":     e["username"] or "",
            "active":       bool(e["active"]),
            "has_password": bool(e["password_hash"]),
        }
        for e in emps
    ]})


async def handle_employees_add(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "JSON kerak"}, 400)

    full_name   = data.get("full_name", "").strip()
    position    = data.get("position", "").strip()
    login_phone = data.get("login_phone", "").strip()
    password    = data.get("password", "").strip()

    if not full_name or not login_phone or not password:
        return _json({"error": "Ism, telefon va parol majburiy"}, 400)

    db: Database = request.app["db"]
    if await db.get_employee_by_login_phone(login_phone):
        return _json({"error": "Bu telefon raqam allaqachon ro'yxatda"}, 409)

    pw_hash = Database.hash_password(password)
    tg_id   = await db.add_employee_web(full_name, position, login_phone, pw_hash)
    return _json({"ok": True, "tg_id": tg_id})


async def handle_employees_update(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)
    tg_id = int(request.match_info.get("tg_id", "0"))
    try:
        data = await request.json()
    except Exception:
        return _json({"error": "JSON kerak"}, 400)

    full_name   = data.get("full_name", "").strip()
    position    = data.get("position", "").strip()
    login_phone = data.get("login_phone", "").strip()
    password    = data.get("password", "").strip()
    active      = int(data.get("active", 1))

    if not full_name or not login_phone:
        return _json({"error": "Ism va telefon majburiy"}, 400)

    db: Database = request.app["db"]
    pw_hash = Database.hash_password(password) if password else None
    await db.update_employee_web(tg_id, full_name, position, login_phone, pw_hash, active)
    return _json({"ok": True})


async def handle_employees_delete(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)
    tg_id = int(request.match_info.get("tg_id", "0"))
    db: Database = request.app["db"]
    await db.delete_employee_web(tg_id)
    return _json({"ok": True})


# ── App factory ────────────────────────────────────────────

def create_webapp(config: Config, db: Database, bot) -> web.Application:
    app = web.Application(client_max_size=50 * 1024 * 1024)
    app["config"] = config
    app["db"]     = db
    app["bot"]    = bot

    app.router.add_route("OPTIONS", "/{path_info:.*}", handle_options)

    app.router.add_get("/",  handle_index)

    app.router.add_post("/api/login",  handle_login)
    app.router.add_post("/api/logout", handle_logout)
    app.router.add_get("/api/me",      handle_me)

    app.router.add_get("/api/tasks",                  handle_tasks)
    app.router.add_post("/api/tasks",                 handle_tasks_create)
    app.router.add_get("/api/tasks/{task_id}/detail", handle_task_detail)
    app.router.add_get("/api/tasks/{task_id}/zip",    handle_task_zip)
    app.router.add_post("/api/submit",                handle_submit)
    app.router.add_get("/api/file/{file_id}",         handle_file_proxy)

    app.router.add_get("/api/employees",            handle_employees_list)
    app.router.add_post("/api/employees",           handle_employees_add)
    app.router.add_put("/api/employees/{tg_id}",    handle_employees_update)
    app.router.add_delete("/api/employees/{tg_id}", handle_employees_delete)

    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)

    return app
