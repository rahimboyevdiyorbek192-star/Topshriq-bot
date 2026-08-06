"""Telegram xabaridan fayl ma'lumotlarini ajratib olish."""
from __future__ import annotations

from aiogram.types import Message


def extract_file(message: Message) -> tuple[str, str | None, str] | None:
    """Xabardan (file_id, file_name, kind) qaytaradi. Fayl bo'lmasa None."""
    if message.document:
        return message.document.file_id, message.document.file_name, "document"
    if message.photo:
        return message.photo[-1].file_id, None, "photo"
    if message.video:
        return message.video.file_id, message.video.file_name, "video"
    if message.audio:
        return message.audio.file_id, message.audio.file_name, "audio"
    if message.voice:
        return message.voice.file_id, None, "voice"
    return None


def message_text(message: Message) -> str:
    return message.text or message.caption or ""
