"""Telethon userbot — xodimlarga shaxsiy xabar yuborish (rahbar nomi bilan)."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        UserPrivacyRestrictedError,
        FloodWaitError,
        PeerFloodError,
    )
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False


class UserBot:
    """
    Telethon orqali shaxsiy xabar yuborish.

    Sozlash tartibi:
    1. my.telegram.org saytida API ID va API Hash oling
    2. generate_session.py ni ishga tushirib session string hosil qiling
    3. .env fayliga TG_API_ID, TG_API_HASH, TG_USERBOT_SESSION ni qo'shing
    """

    def __init__(
        self, api_id: int, api_hash: str, session_string: str
    ) -> None:
        if not TELETHON_AVAILABLE:
            raise ImportError(
                "telethon o'rnatilmagan. Buyruq: pip install telethon"
            )
        self._client: Optional["TelegramClient"] = TelegramClient(
            StringSession(session_string), api_id, api_hash
        )
        self._started = False

    async def start(self) -> bool:
        """Userbotni ulaydi. Muvaffaqiyat bo'lsa True."""
        if not self._client:
            return False
        try:
            await self._client.start()
            me = await self._client.get_me()
            logger.info("Userbot ulandi: @%s", me.username or me.id)
            self._started = True
            return True
        except Exception as exc:
            logger.error("Userbot ulanmadi: %s", exc)
            self._started = False
            return False

    async def send_message(self, user_id: int, text: str) -> bool:
        """user_id ga shaxsiy xabar yuboradi. Muvaffaqiyat bo'lsa True."""
        if not self._started or not self._client:
            return False
        try:
            await self._client.send_message(user_id, text, parse_mode="html")
            return True
        except UserPrivacyRestrictedError:
            logger.warning(
                "Userbot: %s ga xabar yuborib bo'lmaydi (maxfiylik sozlamalari)",
                user_id,
            )
            return False
        except FloodWaitError as e:
            logger.warning("Userbot: FloodWait %s soniya", e.seconds)
            return False
        except PeerFloodError:
            logger.warning("Userbot: PeerFlood — spam cheklov")
            return False
        except Exception as exc:
            logger.warning("Userbot xatolik (%s): %s", user_id, exc)
            return False

    async def stop(self) -> None:
        if self._client and self._started:
            await self._client.disconnect()
            self._started = False


class DummyUserBot:
    """Telethon o'rnatilmagan yoki sozlanmagan bo'lganda ishlatiladi."""

    async def start(self) -> bool:
        return False

    async def send_message(self, user_id: int, text: str) -> bool:
        logger.debug("DummyUserBot: xabar yuborilmadi user=%s", user_id)
        return False

    async def stop(self) -> None:
        pass


def create_userbot(
    api_id: int | None,
    api_hash: str | None,
    session_string: str | None,
) -> "UserBot | DummyUserBot":
    """Konfiguratsiyaga qarab real yoki dummy userbot qaytaradi."""
    if not TELETHON_AVAILABLE:
        logger.info("Telethon o'rnatilmagan — userbot o'chirilgan.")
        return DummyUserBot()
    if not api_id or not api_hash or not session_string:
        logger.info("Userbot sozlanmagan (TG_API_ID/TG_API_HASH/TG_USERBOT_SESSION yo'q).")
        return DummyUserBot()
    try:
        return UserBot(api_id, api_hash, session_string)
    except Exception as exc:
        logger.error("Userbot yaratishda xatolik: %s", exc)
        return DummyUserBot()
