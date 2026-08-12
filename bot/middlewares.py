"""Middleware'lar: kirish nazorati, albom yig'ish va bog'liqliklarni uzatish."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from .config import Config
from .database import Database

logger = logging.getLogger(__name__)


class AccessControlMiddleware(BaseMiddleware):
    """Faqat rahbar va ro'yxatdagi faol xodimlarga javob beradi.

    Ruxsatsiz foydalanuvchilarga hech qanday javob qaytarilmaydi (jim rad etish).
    Kanal postlari va from_user=None bo'lgan xabarlar tekshirilmaydi.
    """

    def __init__(self, config: Config, db: Database) -> None:
        self.config = config
        self.db = db

    async def _allowed(self, user_id: int) -> bool:
        if self.config.is_manager(user_id):
            return True
        try:
            emp = await self.db.get_employee(user_id)
            return bool(emp and emp["active"])
        except Exception as exc:
            logger.warning("AccessControl DB xatosi (user %s): %s", user_id, exc)
            return False  # xato bo'lsa — rad etish (xavfsiz yopiq)

    def _allowed_group(self, chat_id: int) -> bool:
        """Bu guruh .env da sozlangan guruhlardan birimi?"""
        if chat_id in self.config.execution_group_ids:
            return True
        if self.config.tasks_group_id and chat_id == self.config.tasks_group_id:
            return True
        return False

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            user = event.from_user
            if user is None:
                # Tizim xabari yoki anonim — o'tkazib yuborish
                return await handler(event, data)

            chat_type = event.chat.type

            if chat_type == "private":
                # Shaxsiy: faqat rahbar va ro'yxatdagi xodim
                if not await self._allowed(user.id):
                    logger.info("Ruxsatsiz shaxsiy xabar rad etildi: user_id=%s", user.id)
                    return None

            elif chat_type in ("group", "supergroup"):
                # Guruh: faqat .env da ro'yxatga olingan guruhlar
                if not self._allowed_group(event.chat.id):
                    logger.info(
                        "Noma'lum guruhdan xabar rad etildi: chat_id=%s user_id=%s",
                        event.chat.id, user.id,
                    )
                    return None

            # channel type — channel_post event orqali keladi, bu yerga kelmaydi

        elif isinstance(event, CallbackQuery):
            if not await self._allowed(event.from_user.id):
                return None

        return await handler(event, data)


class DependencyMiddleware(BaseMiddleware):
    """Har bir handlerga config, db va ai obyektlarini uzatadi."""

    def __init__(self, config: Config, db: Database, ai=None) -> None:
        self.config = config
        self.db = db
        self.ai = ai

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["config"] = self.config
        data["db"] = self.db
        data["ai"] = self.ai
        return await handler(event, data)


class AlbumMiddleware(BaseMiddleware):
    """Bir media group (albom) ichidagi xabarlarni bitta ro'yxatga yig'adi.

    Faqat guruhning birinchi xabari handlerga o'tadi va unga `album`
    (barcha xabarlar ro'yxati) qo'shiladi. Yakka xabarlar uchun album=None.
    """

    def __init__(self, delay: float = 1.0) -> None:
        self.delay = delay
        self._albums: dict[str, list[Message]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            data["album"] = None
            return await handler(event, data)

        group_id = event.media_group_id
        self._albums.setdefault(group_id, []).append(event)

        # Har bir albom uchun bitta lock — faqat birinchi xabar ishlov beradi.
        lock = self._locks.setdefault(group_id, asyncio.Lock())
        if lock.locked():
            return None  # bu xabar asosiy xabarga qo'shildi, alohida ishlanmaydi

        async with lock:
            await asyncio.sleep(self.delay)
            album = self._albums.pop(group_id, [])
            self._locks.pop(group_id, None)

        # Albomni birinchi (caption bor) xabar bo'yicha tartiblaymiz
        album.sort(key=lambda m: m.message_id)
        data["album"] = album
        return await handler(event, data)
