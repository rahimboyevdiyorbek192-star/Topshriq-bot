"""Middleware'lar: albom (media group) yig'ish va bog'liqliklarni uzatish."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from .config import Config
from .database import Database


class DependencyMiddleware(BaseMiddleware):
    """Har bir handlerga config va db obyektlarini uzatadi."""

    def __init__(self, config: Config, db: Database) -> None:
        self.config = config
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["config"] = self.config
        data["db"] = self.db
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
