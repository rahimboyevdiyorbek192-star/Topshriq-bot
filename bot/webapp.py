"""Telegram Mini App uchun aiohttp HTTP server."""
from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import io
import json
import logging
import urllib.parse
import uuid
import zipfile
from datetime import datetime
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
def _extract_exif_info(
    data: bytes, filename: str
) -> tuple[str | None, str | None, str | None]:
    """JPG/JPEG rasimidan (exif_date, exif_device, exif_gps) qaytaradi."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg"):
        return None, None, None
    try:
        from PIL import Image
        img   = Image.open(io.BytesIO(data))
        exif  = img.getexif()
        if not exif:
            return None, None, None

        exif_date: str | None = None
        for tag_id in (36867, 36868, 306):
            val = exif.get(tag_id)
            if val:
                exif_date = str(val)
                break

        make  = (exif.get(271) or "").strip()
        model = (exif.get(272) or "").strip()
        exif_device: str | None = None
        if make or model:
            parts = [x for x in [make, model] if x]
            if len(parts) == 2 and model.startswith(make):
                parts = [model]
            exif_device = " ".join(parts)

        exif_gps: str | None = None
        try:
            gps = exif.get_ifd(0x8825)
            lat_dms = gps.get(2)
            lat_ref = gps.get(1, "N")
            lon_dms = gps.get(4)
            lon_ref = gps.get(3, "E")
            if lat_dms and lon_dms:
                def dms2dd(dms, ref):
                    d, m, s = [float(x) for x in dms]
                    dd = d + m / 60 + s / 3600
                    return -dd if ref in ("S", "W") else dd
                exif_gps = f"{round(dms2dd(lat_dms, lat_ref), 6)},{round(dms2dd(lon_dms, lon_ref), 6)}"
        except Exception:
            pass

        return exif_date, exif_device, exif_gps
    except Exception:
        pass
    return None, None, None


def _extract_exif_date(data: bytes, filename: str) -> str | None:
    return _extract_exif_info(data, filename)[0]


async def _tg_send_submission(bot, send_chats: list, uname: str, task_id: int,
                               files_info: list[tuple[str, str]]) -> None:
    """Background: diskdagi fayllarni Telegram ga yuboradi (xabarnoma uchun)."""
    from aiogram.types import BufferedInputFile
    for idx, (disk_path, fname) in enumerate(files_info):
        try:
            fdata = Path(disk_path).read_bytes()
        except Exception:
            continue
        caption = (
            f"📱 <b>Mini App topshiriq</b>\n👤 {uname}\n📋 #{task_id}"
            if idx == 0 else None
        )
        for chat_id in send_chats:
            try:
                await bot.send_document(
                    chat_id,
                    BufferedInputFile(fdata, filename=fname),
                    caption=caption,
                    parse_mode="HTML",
                )
                break
            except Exception as exc:
                logger.warning("TG bg yuborish %s (%s): %s", chat_id, fname, exc)


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

    lat = data.get("lat")
    lon = data.get("lon")
    try:
        lat = float(lat) if lat is not None else None
        lon = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lat = lon = None

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

    if lat is not None and lon is not None:
        try:
            await db.update_employee_location(emp["tg_id"], lat, lon)
        except Exception:
            pass

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
        submitted_ids  = await db.submitted_employee_ids(t["id"])
        task_files     = await db.get_task_files(t["id"])
        my_sub         = await db.get_submission(t["id"], user_id)
        req_files      = t["required_files"] if "required_files" in t.keys() else 0
        my_file_count  = await db.count_employee_total_files(t["id"], user_id) if not is_manager else 0
        submitted_me   = (
            user_id in submitted_ids and (req_files == 0 or my_file_count >= req_files)
        )

        result.append({
            "id":              t["id"],
            "title":           t["title"],
            "description":     t["description"] or "",
            "deadline":        t["deadline"] or "",
            "submitted_by_me": submitted_me,
            "done_count":      len(submitted_ids),
            "total_count":     total_emp,
            "required_files":  req_files,
            "my_file_count":   my_file_count,
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
            "id":             task["id"],
            "title":          task["title"],
            "description":    task["description"] or "",
            "deadline":       task["deadline"] or "",
            "required_files": task["required_files"] if "required_files" in task.keys() else 0,
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
                "exif_device":  s["exif_device"],
                "exif_gps":     s["exif_gps"],
                "is_old_photo": _is_old_photo(s["exif_date"], s["submitted_at"] or ""),
                "submit_lat":   s["submit_lat"],
                "submit_lon":   s["submit_lon"],
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

        # Fayllarni yuklash: avval disk, keyin Telegram
        used: set[str] = set()

        async def _dl(
            local_path: str | None,
            file_id: str | None,
            file_name: str | None,
            folder: str,
            client: httpx.AsyncClient,
        ) -> None:
            # 1. Disk dan o'qish
            if local_path:
                p = Path(local_path)
                if p.exists():
                    fname = _safe_filename(file_name or p.name)
                    zf.writestr(_unique_arcname(folder, fname, used), p.read_bytes())
                    return
            # 2. Telegram dan yuklash
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

        async with httpx.AsyncClient(timeout=30) as client:
            for s in submissions:
                lp = s["local_path"] if "local_path" in s.keys() else None
                if lp or s["file_id"]:
                    folder = _safe_filename(
                        s["position"] or s["full_name"] or str(s["employee_id"])
                    )
                    await _dl(lp, s["file_id"], s["file_name"], folder, client)

            for ef in extra_files:
                lp = ef["local_path"] if "local_path" in ef.keys() else None
                folder = _safe_filename(
                    ef["position"] or ef["full_name"] or str(ef["employee_id"])
                )
                await _dl(lp, ef["file_id"], ef["file_name"], folder, client)

    buf.seek(0)
    safe = _safe_filename(task["title"][:40])
    return _cors(web.Response(
        body=buf.getvalue(),
        content_type="application/zip",
        headers={"Content-Disposition": _content_disposition(f"topshiriq_{task_id}_{safe}.zip")},
    ))


# ── Topshiriq tarixi (barcha, ochiq + yopilgan) ────────────

async def handle_history(request: web.Request) -> web.Response:
    user, is_manager = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)

    db: Database = request.app["db"]
    user_id      = user["id"]
    tasks        = await db.list_all_tasks()
    total_emp    = await db.count_employees()
    result       = []

    for t in tasks:
        submitted_ids  = await db.submitted_employee_ids(t["id"])
        task_files     = await db.get_task_files(t["id"])
        my_sub         = await db.get_submission(t["id"], user_id) if not is_manager else None
        req_files      = t["required_files"] if "required_files" in t.keys() else 0
        my_file_count  = await db.count_employee_total_files(t["id"], user_id) if not is_manager else 0
        submitted_me   = (
            user_id in submitted_ids and (req_files == 0 or my_file_count >= req_files)
        )

        result.append({
            "id":              t["id"],
            "title":           t["title"],
            "description":     t["description"] or "",
            "deadline":        t["deadline"] or "",
            "status":          t["status"],
            "created_at":      t["created_at"],
            "done_count":      len(submitted_ids),
            "total_count":     total_emp,
            "submitted_by_me": submitted_me,
            "required_files":  req_files,
            "my_file_count":   my_file_count,
            "files": [
                {"file_id": f["file_id"], "file_name": f["file_name"] or "fayl", "kind": f["file_kind"]}
                for f in task_files
            ],
            "my_submission": {
                "file_id":      my_sub["file_id"],
                "file_name":    my_sub["file_name"],
                "note":         my_sub["note"],
                "submitted_at": my_sub["submitted_at"],
            } if my_sub else None,
        })

    return _json({"tasks": result, "is_manager": is_manager, "user": user})


# ── Topshiriqni o'chirish (rahbar) ─────────────────────────

async def handle_task_delete(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    task_id = int(request.match_info.get("task_id", "0"))
    db: Database = request.app["db"]
    ok = await db.delete_task(task_id)
    if not ok:
        return _json({"error": "Topshiriq topilmadi"}, 404)
    return _json({"ok": True})


# ── Topshiriq yaratish (rahbar) ────────────────────────────

async def handle_tasks_create(request: web.Request) -> web.Response:
    """Rahbar uchun yangi topshiriq yaratadi."""
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    title: str = ""
    description: str | None = None
    deadline: str | None = None
    required_files: int = 0
    pending: list[tuple[str, bytes]] = []  # (fname, data)

    try:
        ct = request.content_type or ""
        if ct.startswith("multipart/"):
            reader = await request.multipart()
            async for field in reader:
                if field.name == "title":
                    title = (await field.read(decode=True)).decode("utf-8", "ignore").strip()
                elif field.name == "description":
                    description = (await field.read(decode=True)).decode("utf-8", "ignore").strip() or None
                elif field.name == "deadline":
                    deadline = (await field.read(decode=True)).decode("utf-8", "ignore").strip() or None
                elif field.name == "required_files":
                    raw = (await field.read(decode=True)).decode("utf-8", "ignore").strip()
                    try:
                        required_files = max(0, int(raw))
                    except (TypeError, ValueError):
                        required_files = 0
                elif field.name in ("file", "files", "files[]"):
                    fdata = await field.read()
                    if fdata:
                        pending.append((field.filename or "fayl", fdata))
        else:
            data = await request.json()
            title = (data.get("title") or "").strip()
            description = (data.get("description") or "").strip() or None
            deadline = (data.get("deadline") or "").strip() or None
            try:
                required_files = max(0, int(data.get("required_files") or 0))
            except (TypeError, ValueError):
                required_files = 0
    except Exception:
        return _json({"error": "So'rovni o'qib bo'lmadi"}, 400)

    if not title:
        return _json({"error": "Topshiriq nomi majburiy"}, 400)

    db: Database   = request.app["db"]
    config: Config = request.app["config"]

    task_id = await db.create_task(
        title=title,
        description=description,
        deadline=deadline,
        created_by=user.get("id"),
        src_chat_id=None,
        src_msg_id=None,
        required_files=required_files,
    )

    # Namuna fayllarni Telegram'ga yuborish va task_files ga saqlash
    if pending:
        bot = request.app["bot"]
        send_chat = config.execution_group_id or (
            config.manager_ids[0] if config.manager_ids else None
        )
        if send_chat:
            from aiogram.types import BufferedInputFile
            for idx, (fname, fdata) in enumerate(pending):
                try:
                    caption = f"📎 <b>Topshiriq #{task_id} namuna fayl</b>" if idx == 0 else None
                    sent = await bot.send_document(
                        send_chat, BufferedInputFile(fdata, filename=fname), caption=caption
                    )
                    if sent and sent.document:
                        await db.add_task_file(task_id, sent.document.file_id, fname, "document")
                except Exception as exc:
                    logger.warning("Namuna fayl Telegram'ga yuborilmadi (%s): %s", fname, exc)

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
            if required_files:
                text += f"\n📂 Talab: {required_files} ta fayl"
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
    lat_raw: str | None     = None
    lon_raw: str | None     = None
    client_exif: list       = []  # exif_json maydonidan
    pending: list[tuple[str, bytes, str | None, str | None, str | None]] = []  # (fname, data, exif_date, exif_device, exif_gps)

    try:
        if (request.content_type or "").startswith("multipart/"):
            reader = await request.multipart()
            async for field in reader:
                if field.name == "task_id":
                    task_id_raw = (await field.read(decode=True)).decode("utf-8", "ignore")
                elif field.name == "note":
                    note = (await field.read(decode=True)).decode("utf-8", "ignore")[:1000]
                elif field.name == "lat":
                    lat_raw = (await field.read(decode=True)).decode("utf-8", "ignore")
                elif field.name == "lon":
                    lon_raw = (await field.read(decode=True)).decode("utf-8", "ignore")
                elif field.name == "exif_json":
                    raw = (await field.read(decode=True)).decode("utf-8", "ignore")
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            client_exif = parsed
                    except Exception:
                        pass
                elif field.name in ("file", "files", "files[]"):
                    fdata = await field.read()
                    if fdata:
                        fname = field.filename or "fayl"
                        pending.append((fname, fdata, *_extract_exif_info(fdata, fname)))
        else:
            # Faylsiz (faqat izohli) topshirish oddiy forma sifatida ham kelishi mumkin
            form        = await request.post()
            task_id_raw = form.get("task_id")
            raw_note    = form.get("note")
            note        = str(raw_note)[:1000] if raw_note else None
            lat_raw     = form.get("lat")
            lon_raw     = form.get("lon")
    except Exception as exc:
        logger.warning("Submit so'rovini o'qib bo'lmadi: %s", exc)
        return _json({"error": "So'rovni o'qib bo'lmadi"}, 400)

    # Client EXIF (siqishdan oldin o'qilgan) — server ekstraktsiyasini to'ldiradi/almаshtiradi
    for i, ov in enumerate(client_exif):
        if i < len(pending) and ov and isinstance(ov, dict):
            fname, fdata, ed, edev, eg = pending[i]
            pending[i] = (
                fname, fdata,
                (ov.get("date")   or "").strip() or ed,
                (ov.get("device") or "").strip() or edev,
                (ov.get("gps")    or "").strip() or eg,
            )

    submit_lat: float | None = None
    submit_lon: float | None = None
    try:
        if lat_raw and lon_raw:
            submit_lat = float(lat_raw)
            submit_lon = float(lon_raw)
    except (TypeError, ValueError):
        pass

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

    # ── 3. Fayllarni disk'ga saqlash + Telegram'ga yuborish ──
    # (disk_path, file_id|None, fname, exif_date, exif_device, exif_gps)
    uploaded: list[tuple[str, str | None, str, str | None, str | None, str | None]] = []

    uploads_dir = Path(config.db_path).resolve().parent / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    send_chats: list[int] = []
    if config.execution_group_id:
        send_chats.append(config.execution_group_id)
    if config.manager_ids:
        send_chats.extend(config.manager_ids)

    if pending:
        uname = f"@{user['username']}" if user.get("username") else full_name
        for fname, fdata, exif_d, exif_dev, exif_g in pending:
            # Disk'ga saqlash (har doim)
            safe = _safe_filename(fname)
            disk_path = uploads_dir / f"{uuid.uuid4().hex}_{safe}"
            disk_path.write_bytes(fdata)
            # tg_file_id fonda yuborilib to'ldiriladi — hozir None
            uploaded.append((str(disk_path), None, fname, exif_d, exif_dev, exif_g))

    # ── 4. Bazaga yozish ──────────────────────────────────
    try:
        first = uploaded[0] if uploaded else None
        await db.add_submission(
            task_id=task_id, employee_id=user_id, message_id=None,
            note=(note or "").strip() or "Mini App orqali yuborildi",
            file_id=first[1] if first else None,
            file_name=first[2] if first else None,
            exif_date=first[3] if first else None,
            submit_lat=submit_lat,
            submit_lon=submit_lon,
            local_path=first[0] if first else None,
            exif_device=first[4] if first else None,
            exif_gps=first[5] if first else None,
        )
        for disk_p, fid, fname, exif_d, exif_dev, exif_g in uploaded[1:]:
            await db.add_submission_file(
                task_id, user_id, fid, fname,
                exif_date=exif_d, local_path=disk_p,
                exif_device=exif_dev, exif_gps=exif_g,
            )
    except Exception as exc:
        logger.error("Submit bazaga yozilmadi: %s", exc, exc_info=True)
        return _json({"error": "Ma\'lumotni saqlab bo\'lmadi"}, 500)

    # Telegram xabarnomasi fonda yuboriladi (javobni kutdirmaydi)
    if uploaded and send_chats:
        files_info = [(dp, fn) for dp, _, fn, *_ in uploaded]
        asyncio.create_task(
            _tg_send_submission(bot, send_chats, uname, task_id, files_info)
        )

    submitted     = await db.submitted_employee_ids(task_id)
    my_file_count = await db.count_employee_total_files(task_id, user_id)
    req_files     = task["required_files"] if "required_files" in task.keys() else 0
    submitted_me  = user_id in submitted and (req_files == 0 or my_file_count >= req_files)
    return _json({
        "ok":              True,
        "done_count":      len(submitted),
        "total_count":     await db.count_employees(),
        "submitted_by_me": submitted_me,
        "my_file_count":   my_file_count,
        "req_files":       req_files,
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

    # Avval local_path dan qidirish
    local_path: str | None = await db.get_file_local_path(file_id)
    if local_path:
        p = Path(local_path)
        if p.exists():
            fname = _safe_filename(request.rel_url.query.get("name", "") or p.name)
            return _cors(web.Response(
                body=p.read_bytes(),
                content_type="application/octet-stream",
                headers={"Content-Disposition": _content_disposition(fname)},
            ))

    try:
        tg_file  = await bot.get_file(file_id)
        file_url = (
            f"https://api.telegram.org/file/bot{config.bot_token}/{tg_file.file_path}"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(file_url)
            r.raise_for_status()
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


# ── Real-time joylashuv ────────────────────────────────────

async def handle_location_post(request: web.Request) -> web.Response:
    """Hodim joriy joylashuvini yuboradi (30 soniyada bir)."""
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if is_mgr or user["id"] == 0:
        return _json({"ok": True})  # Rahbardan saqlamaymiz

    try:
        data = await request.json()
    except Exception:
        return _json({"error": "JSON kerak"}, 400)

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return _json({"error": "lat/lon kerak"}, 400)

    accuracy = None
    try:
        accuracy = float(data["accuracy"]) if data.get("accuracy") is not None else None
    except (TypeError, ValueError):
        pass

    db: Database = request.app["db"]
    await db.add_location_point(user["id"], lat, lon, accuracy)
    await db.update_employee_location(user["id"], lat, lon)
    return _json({"ok": True})


async def handle_location_live(request: web.Request) -> web.Response:
    """Barcha xodimlarning eng so'nggi joylashuvi (rahbar uchun)."""
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    from datetime import datetime as _dt, timezone as _tz
    db: Database = request.app["db"]
    rows = await db.get_all_latest_locations()
    now  = _dt.now()
    data = []
    for r in rows:
        rec = r["recorded_at"]
        minutes_ago = None
        rec_fmt = None
        if rec:
            try:
                dt = _dt.fromisoformat(rec)
                if dt.tzinfo:
                    dt = dt.replace(tzinfo=None)
                diff = now - dt
                minutes_ago = int(diff.total_seconds() / 60)
                rec_fmt = dt.strftime("%H:%M")
            except Exception:
                pass
        data.append({
            "tg_id":       r["tg_id"],
            "name":        r["full_name"],
            "position":    r["position"] or "",
            "lat":         r["lat"],
            "lon":         r["lon"],
            "recorded_at": rec_fmt,
            "minutes_ago": minutes_ago,
        })
    return _json({"ok": True, "data": data})


async def handle_location_history(request: web.Request) -> web.Response:
    """Bitta xodimning berilgan sanaga ko'ra joylashuv tarixi (rahbar uchun)."""
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    tg_id = int(request.match_info.get("tg_id", "0"))
    from datetime import date as _date
    date_str = request.rel_url.query.get("date", _date.today().isoformat())

    db: Database = request.app["db"]
    rows = await db.get_location_history(tg_id, date_str)

    from datetime import datetime as _dt
    points = []
    for r in rows:
        t = r["recorded_at"]
        t_fmt = None
        if t:
            try:
                t_fmt = _dt.fromisoformat(t).strftime("%H:%M:%S")
            except Exception:
                pass
        points.append({
            "lat":  r["lat"],
            "lon":  r["lon"],
            "time": t_fmt or t,
        })
    return _json({"ok": True, "points": points})


# ── Xodimlar joylashuvi (rahbar uchun) ────────────────────

async def handle_employees_locations(request: web.Request) -> web.Response:
    user, is_mgr = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_mgr:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    db: Database = request.app["db"]
    rows = await db.get_all_employees_location_status()

    from datetime import datetime as _dt
    data = []
    for r in rows:
        loc_time = r["last_location_at"]
        if loc_time:
            try:
                loc_time = _dt.fromisoformat(loc_time).strftime("%d.%m.%Y %H:%M")
            except Exception:
                pass
        data.append({
            "tg_id":     r["tg_id"],
            "name":      r["full_name"],
            "phone":     r["login_phone"] or "—",
            "position":  r["position"] or "",
            "lat":       r["last_lat"],
            "lon":       r["last_lon"],
            "last_time": loc_time or None,
            "active":    bool(r["active"]),
        })

    return _json({"ok": True, "data": data})


# ── Sozlamalar ────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "org_name":    "Tashkilot nomi",
    "app_title":   "Topshiriq Tizimi",
    "dept_name":   "Bo'lim",
    "task_label":  "Topshiriq",
    "emp_label":   "Xodim",
    "welcome_msg": "Topshiriqlar boshqaruv tizimiga xush kelibsiz.",
}


async def handle_settings_get(request: web.Request) -> web.Response:
    """GET /api/settings — barcha foydalanuvchilar uchun ochiq."""
    db: Database = request.app["db"]
    saved = await db.get_all_settings()
    merged = {**DEFAULT_SETTINGS, **saved}
    return _json(merged)


async def handle_settings_save(request: web.Request) -> web.Response:
    """POST /api/settings — faqat rahbar."""
    user, is_manager = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_manager:
        return _json({"error": "Faqat rahbar sozlay oladi"}, 403)

    try:
        body = await request.json()
    except Exception:
        return _json({"error": "JSON noto'g'ri"}, 400)

    db: Database = request.app["db"]
    allowed = set(DEFAULT_SETTINGS.keys())
    for key, val in body.items():
        if key in allowed and isinstance(val, str):
            await db.set_setting(key, val.strip())

    saved = await db.get_all_settings()
    return _json({**DEFAULT_SETTINGS, **saved})


# ── KPI ───────────────────────────────────────────────────

async def handle_kpi(request: web.Request) -> web.Response:
    """GET /api/kpi?year=YYYY
    Rahbar → barcha xodimlar KPI xulosasi.
    Xodim  → o'z KPI ko'rsatkichlari."""
    user, is_manager = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)

    year = int(request.rel_url.query.get("year", datetime.now().year))
    db: Database = request.app["db"]

    if is_manager:
        employees = await db.get_all_employees_kpi_summary(year)
        # int keys → str for JSON serialization
        for e in employees:
            e["quarters"] = {str(q): v for q, v in e["quarters"].items()}
        return _json({"employees": employees, "year": year, "is_manager": True})

    quarters = await db.get_employee_kpi(user["id"], year)
    quarters_out = {
        str(q): {
            "total": v["total"],
            "done":  v["done"],
            "months": {str(m): mv for m, mv in v["months"].items()},
        }
        for q, v in quarters.items()
    }
    return _json({"quarters": quarters_out, "year": year, "is_manager": False, "user": user})


async def handle_kpi_employee(request: web.Request) -> web.Response:
    """GET /api/kpi/{emp_id}?year=YYYY  — faqat rahbar uchun."""
    user, is_manager = await _auth_full(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    if not is_manager:
        return _json({"error": "Faqat rahbar uchun"}, 403)

    emp_id = int(request.match_info.get("emp_id", "0"))
    year   = int(request.rel_url.query.get("year", datetime.now().year))
    db: Database = request.app["db"]

    emp = await db.get_employee(emp_id)
    if not emp:
        return _json({"error": "Xodim topilmadi"}, 404)

    quarters = await db.get_employee_kpi(emp_id, year)
    quarters_out = {
        str(q): {
            "total": v["total"],
            "done":  v["done"],
            "months": {str(m): mv for m, mv in v["months"].items()},
        }
        for q, v in quarters.items()
    }
    return _json({
        "quarters": quarters_out,
        "year": year,
        "employee": {"id": emp["tg_id"], "name": emp["full_name"]},
    })


# ── Xodimning o'z fayllarini boshqarish ───────────────────

async def _my_file_auth(request: web.Request):
    """(user, is_manager, task_id, rec_type, rec_id) yoki xato Response."""
    user, _ = await _auth_full(request)
    if not user or user["id"] == 0:
        return None, None, None, None, None
    rec_type = request.match_info.get("rec_type", "")
    if rec_type not in ("main", "extra"):
        return None, None, None, None, None
    try:
        task_id = int(request.match_info["task_id"])
        rec_id  = int(request.match_info["rec_id"])
    except (KeyError, ValueError):
        return None, None, None, None, None
    return user, user["id"], task_id, rec_type, rec_id


async def handle_my_files_list(request: web.Request) -> web.Response:
    user, _ = await _auth_full(request)
    if not user or user["id"] == 0:
        return _json({"error": "Ruxsat yo'q"}, 401)
    try:
        task_id = int(request.match_info["task_id"])
    except (KeyError, ValueError):
        return _json({"error": "task_id noto'g'ri"}, 400)
    db: Database = request.app["db"]
    files = await db.get_employee_submission_files_meta(task_id, user["id"])
    return _json({"files": files})


async def handle_my_file_download(request: web.Request) -> web.Response:
    user, user_id, task_id, rec_type, rec_id = await _my_file_auth(request)
    if not user:
        return web.Response(status=401)
    db: Database = request.app["db"]
    info = await db.get_submission_file_local(rec_type, rec_id, user_id)
    if not info or not info["local_path"]:
        return web.Response(status=404)
    p = Path(info["local_path"])
    if not p.exists():
        return web.Response(status=404)
    fname    = request.rel_url.query.get("name", "") or info["file_name"]
    ext      = Path(fname).suffix.lower()
    ctype_map = {".pdf": "application/pdf", ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg", ".png": "image/png",
                 ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    ctype    = ctype_map.get(ext, "application/octet-stream")
    encoded  = urllib.parse.quote(fname, safe="")
    return web.Response(
        body=p.read_bytes(),
        content_type=ctype,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


async def handle_my_file_delete(request: web.Request) -> web.Response:
    user, user_id, task_id, rec_type, rec_id = await _my_file_auth(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    db: Database = request.app["db"]
    old_path = await db.delete_submission_file_record(rec_type, rec_id, user_id)
    if old_path is None:
        return _json({"error": "Fayl topilmadi"}, 404)
    if old_path:
        try:
            Path(old_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Faylni diskdan o'chirib bo'lmadi: %s", exc)
    my_file_count = await db.count_employee_total_files(task_id, user_id)
    task          = await db.get_task(task_id)
    req_files     = task["required_files"] if task and "required_files" in task.keys() else 0
    submitted_ids = await db.submitted_employee_ids(task_id)
    submitted_me  = user_id in submitted_ids and (req_files == 0 or my_file_count >= req_files)
    return _json({
        "ok":              True,
        "my_file_count":   my_file_count,
        "submitted_by_me": submitted_me,
    })


async def handle_my_file_replace(request: web.Request) -> web.Response:
    user, user_id, task_id, rec_type, rec_id = await _my_file_auth(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 401)
    db: Database    = request.app["db"]
    config: Config  = request.app["config"]
    bot             = request.app["bot"]
    try:
        reader = await request.multipart()
        fname = "fayl"
        fdata: bytes | None = None
        async for field in reader:
            if field.name in ("file", "files", "files[]"):
                fdata = await field.read()
                fname = field.filename or "fayl"
    except Exception as exc:
        return _json({"error": f"Fayl o'qib bo'lmadi: {exc}"}, 400)
    if not fdata:
        return _json({"error": "Fayl kerak"}, 400)
    uploads_dir = Path(config.db_path).resolve().parent / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe      = _safe_filename(fname)
    new_path  = uploads_dir / f"{uuid.uuid4().hex}_{safe}"
    new_path.write_bytes(fdata)
    old_path = await db.replace_submission_file_record(
        rec_type, rec_id, user_id, fname, str(new_path), None
    )
    if old_path is None:
        new_path.unlink(missing_ok=True)
        return _json({"error": "Fayl topilmadi"}, 404)
    # Telegram xabarnomasi fonda
    r_chats: list[int] = []
    if config.execution_group_id:
        r_chats.append(config.execution_group_id)
    if config.manager_ids:
        r_chats.extend(config.manager_ids)
    if r_chats:
        asyncio.create_task(
            _tg_send_submission(bot, r_chats, f"#{user_id}", 0, [(str(new_path), fname)])
        )
    if old_path:
        try:
            Path(old_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Eski faylni o'chirib bo'lmadi: %s", exc)
    my_file_count = await db.count_employee_total_files(task_id, user_id)
    task          = await db.get_task(task_id)
    req_files     = task["required_files"] if task and "required_files" in task.keys() else 0
    submitted_ids = await db.submitted_employee_ids(task_id)
    submitted_me  = user_id in submitted_ids and (req_files == 0 or my_file_count >= req_files)
    return _json({
        "ok":              True,
        "file_name":       fname,
        "my_file_count":   my_file_count,
        "submitted_by_me": submitted_me,
    })


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
    app.router.add_get("/api/tasks/history",          handle_history)           # static — {task_id}'dan oldin
    app.router.add_get("/api/tasks/{task_id}/detail", handle_task_detail)
    app.router.add_get("/api/tasks/{task_id}/zip",    handle_task_zip)
    app.router.add_delete("/api/tasks/{task_id}",     handle_task_delete)
    app.router.add_post("/api/submit",                handle_submit)
    app.router.add_get("/api/file/{file_id}",         handle_file_proxy)

    app.router.add_get(   "/api/my-files/{task_id}",                          handle_my_files_list)
    app.router.add_get(   "/api/my-files/{task_id}/{rec_type}/{rec_id}",      handle_my_file_download)
    app.router.add_delete("/api/my-files/{task_id}/{rec_type}/{rec_id}",      handle_my_file_delete)
    app.router.add_post(  "/api/my-files/{task_id}/{rec_type}/{rec_id}",      handle_my_file_replace)

    app.router.add_get("/api/employees",                    handle_employees_list)
    app.router.add_post("/api/employees",                   handle_employees_add)
    app.router.add_get("/api/employees/locations",          handle_employees_locations)
    app.router.add_put("/api/employees/{tg_id}",            handle_employees_update)
    app.router.add_delete("/api/employees/{tg_id}",         handle_employees_delete)

    app.router.add_post("/api/location",                    handle_location_post)
    app.router.add_get("/api/location/live",                handle_location_live)
    app.router.add_get("/api/location/{tg_id}",             handle_location_history)

    app.router.add_get("/api/kpi",           handle_kpi)
    app.router.add_get("/api/kpi/{emp_id}",  handle_kpi_employee)

    app.router.add_get("/api/settings",      handle_settings_get)
    app.router.add_post("/api/settings",     handle_settings_save)

    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)

    return app
