"""Telegram jonli lokatsiya handlerları.

Xodim botga (yoki guruhga) jonli lokatsiya ulashganda,
bot avtomatik ravishda bazani yangilab boradi.
Oddiy (bir martalik) lokatsiya ham qabul qilinadi.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.types import Message

from ..database import Database

logger = logging.getLogger(__name__)
router = Router()


async def _save_location(message: Message, db: Database, *, is_live: bool) -> None:
    """Lokatsiyani bazaga yozadi; xodim topilmasa jim o'tadi."""
    if not message.from_user or not message.location:
        return
    tg_id = message.from_user.id
    lat   = message.location.latitude
    lon   = message.location.longitude
    acc   = getattr(message.location, "horizontal_accuracy", None)

    emp = await db.get_employee(tg_id)
    if not emp or not emp["active"]:
        return

    await db.update_employee_location(tg_id, lat, lon)
    await db.add_location_point(tg_id, lat, lon, acc)
    kind = "jonli" if is_live else "oddiy"
    logger.info("Lokatsiya saqlandi [%s]: tg_id=%s lat=%.5f lon=%.5f", kind, tg_id, lat, lon)


# ── Yangi lokatsiya xabari (message) ─────────────────────
@router.message(F.content_type == ContentType.LOCATION)
async def on_location(message: Message, db: Database) -> None:
    live = message.location.live_period is not None
    await _save_location(message, db, is_live=live)
    # jonli lokatsiya ulashganda bitta jimgina tasdiqlash
    if live:
        try:
            await message.react([{"type": "emoji", "emoji": "👌"}])
        except Exception:
            pass  # reaction API ba'zi versiyalarda ishlamaydi


# ── Yangilangan lokatsiya (edited_message — jonli lokatsiya) ─
@router.edited_message(F.content_type == ContentType.LOCATION)
async def on_live_location_update(message: Message, db: Database) -> None:
    await _save_location(message, db, is_live=True)
