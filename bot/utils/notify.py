"""Xodimning shaxsiy chatida bot xabarlarini tozalab yuborish."""
from __future__ import annotations

import logging

from aiogram import Bot

from ..database import Database

logger = logging.getLogger(__name__)


async def send_and_clean(bot: Bot, db: Database, tg_id: int, text: str, **kwargs) -> None:
    """Oldingi bot xabarini o'chiradi, yangi xabar yuboradi va yangi msg_id ni saqlaydi."""
    if tg_id <= 0:
        return
    old_msg_id = await db.get_employee_bot_msg(tg_id)
    if old_msg_id:
        try:
            await bot.delete_message(tg_id, old_msg_id)
        except Exception:
            pass
    try:
        sent = await bot.send_message(tg_id, text, **kwargs)
        await db.set_employee_bot_msg(tg_id, sent.message_id)
    except Exception as exc:
        logger.warning("Xodim %s ga xabar yuborilmadi: %s", tg_id, exc)
        await db.set_employee_bot_msg(tg_id, None)
