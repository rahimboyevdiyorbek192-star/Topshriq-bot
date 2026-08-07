"""Telegram Mini App uchun aiohttp HTTP server."""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import urllib.parse
from pathlib import Path

import httpx
from aiohttp import web

from .config import Config
from .database import Database

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


# ── initData tekshirish ────────────────────────────────────────

def _validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Telegram Web App initData HMAC-SHA256 tekshiradi."""
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


async def _auth(request: web.Request) -> dict | None:
    # Header yoki query param orqali qabul qilinadi (fayl yuklab olish uchun)
    init_data = (
        request.headers.get("X-Telegram-Init-Data", "")
        or request.rel_url.query.get("init", "")
    )
    config: Config = request.app["config"]
    return _validate_init_data(init_data, config.bot_token)


def _cors(resp: web.Response) -> web.Response:
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "X-Telegram-Init-Data, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def _json(data, status: int = 200) -> web.Response:
    return _cors(web.json_response(data, status=status))


# ── Handlerlar ────────────────────────────────────────────────

async def handle_options(request: web.Request) -> web.Response:
    return _cors(web.Response(status=200))


async def handle_index(request: web.Request) -> web.Response:
    f = STATIC_DIR / "index.html"
    return web.FileResponse(f) if f.exists() else web.Response(
        text="Mini App yuklanmoqda...", content_type="text/html"
    )


async def handle_tasks(request: web.Request) -> web.Response:
    user = await _auth(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 403)

    db: Database = request.app["db"]
    config: Config = request.app["config"]
    user_id   = user["id"]
    is_manager = config.is_manager(user_id)

    tasks     = await db.list_open_tasks()
    total_emp = await db.count_employees()
    result    = []

    for t in tasks:
        submitted_ids = await db.submitted_employee_ids(t["id"])
        task_files    = await db.get_task_files(t["id"])
        my_sub        = await db.get_submission(t["id"], user_id)

        result.append({
            "id":            t["id"],
            "title":         t["title"],
            "description":   t["description"] or "",
            "deadline":      t["deadline"] or "",
            "submitted_by_me": user_id in submitted_ids,
            "done_count":    len(submitted_ids),
            "total_count":   total_emp,
            "files": [
                {
                    "file_id":   f["file_id"],
                    "file_name": f["file_name"] or f"fayl",
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


async def handle_submit(request: web.Request) -> web.Response:
    user = await _auth(request)
    if not user:
        return _json({"error": "Ruxsat yo'q"}, 403)

    db: Database    = request.app["db"]
    config: Config  = request.app["config"]
    bot             = request.app["bot"]

    try:
        reader         = await request.multipart()
        task_id        = None
        note           = None
        uploaded_files: list[tuple[str, str]] = []  # [(file_id, file_name)]

        async for field in reader:
            if field.name == "task_id":
                task_id = int(await field.read(decode=True))

            elif field.name == "note":
                raw  = await field.read(decode=True)
                note = raw.decode("utf-8", errors="ignore")[:1000]

            elif field.name in ("file", "files", "files[]"):
                fn    = field.filename or "fayl"
                fdata = await field.read()
                if not fdata:
                    continue

                send_chat = config.execution_group_id or (
                    config.manager_ids[0] if config.manager_ids else None
                )
                if send_chat:
                    from aiogram.types import BufferedInputFile
                    full_name = (
                        f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                        or "Xodim"
                    )
                    uname   = f"@{user['username']}" if user.get("username") else full_name
                    caption = (
                        f"📱 <b>Mini App topshiriq</b>\n"
                        f"👤 {uname}\n"
                        f"📋 #{task_id}"
                        if not uploaded_files
                        else None
                    )
                    sent = await bot.send_document(
                        send_chat,
                        BufferedInputFile(fdata, filename=fn),
                        caption=caption,
                    )
                    if sent and sent.document:
                        uploaded_files.append((sent.document.file_id, fn))

        if not task_id:
            return _json({"error": "task_id kerak"}, 400)

        task = await db.get_task(task_id)
        if not task:
            return _json({"error": "Topshiriq topilmadi"}, 404)

        user_id   = user["id"]
        full_name = (
            f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "Xodim"
        )
        username  = user.get("username")

        if not await db.get_employee(user_id):
            await db.add_employee(user_id, full_name, username)

        primary_fid  = uploaded_files[0][0] if uploaded_files else None
        primary_name = uploaded_files[0][1] if uploaded_files else None

        await db.add_submission(
            task_id=task_id,
            employee_id=user_id,
            message_id=None,
            note=note or "Mini App orqali yuborildi",
            file_id=primary_fid,
            file_name=primary_name,
        )

        # Qo'shimcha fayllarni submission_files ga saqlash
        if len(uploaded_files) > 1:
            for fid, fname in uploaded_files[1:]:
                await db.add_submission_file(task_id, user_id, fid, fname)

        submitted = await db.submitted_employee_ids(task_id)
        total     = await db.count_employees()

        return _json({
            "ok":         True,
            "done_count": len(submitted),
            "total_count": total,
            "files_uploaded": len(uploaded_files),
        })

    except Exception as exc:
        logger.error("Mini App submit xatosi: %s", exc, exc_info=True)
        return _json({"error": str(exc)}, 500)


async def handle_file_proxy(request: web.Request) -> web.Response:
    """Telegram faylini proksi orqali yuboradi (bot token ochiq qolmaydi)."""
    user = await _auth(request)
    if not user:
        return web.Response(status=403)

    file_id = request.match_info.get("file_id", "")
    bot     = request.app["bot"]
    config: Config = request.app["config"]

    try:
        tg_file  = await bot.get_file(file_id)
        file_url = (
            f"https://api.telegram.org/file/bot{config.bot_token}/{tg_file.file_path}"
        )
        async with httpx.AsyncClient() as client:
            r = await client.get(file_url)
            r.raise_for_status()

        fname = tg_file.file_path.split("/")[-1] if tg_file.file_path else "fayl"
        ctype = r.headers.get("content-type", "application/octet-stream")
        return _cors(web.Response(
            body=r.content,
            content_type=ctype,
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        ))
    except Exception as exc:
        logger.error("Fayl proxy xatosi: %s", exc)
        return web.Response(status=500)


# ── App factory ───────────────────────────────────────────────

def create_webapp(config: Config, db: Database, bot) -> web.Application:
    app = web.Application(client_max_size=50 * 1024 * 1024)  # 50 MB limit
    app["config"] = config
    app["db"]     = db
    app["bot"]    = bot

    app.router.add_route("OPTIONS", "/{path_info:.*}", handle_options)
    app.router.add_get("/",                       handle_index)
    app.router.add_get("/api/tasks",              handle_tasks)
    app.router.add_post("/api/submit",            handle_submit)
    app.router.add_get("/api/file/{file_id}",     handle_file_proxy)

    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)

    return app
