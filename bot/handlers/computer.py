"""Telegram orqali kompyuter boshqarish: /kompyuter va /stop komandalar."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from ..config import Config

logger = logging.getLogger(__name__)
router = Router()

# Joriy ishayotgan agent (faqat bitta bo'lishi mumkin)
_active_agent: Optional[object] = None
_active_user:  Optional[int]    = None


def _check_agent_available() -> tuple[bool, str]:
    """pyautogui va PIL mavjudligini tekshiradi."""
    try:
        import pyautogui   # noqa: F401
    except ImportError:
        return False, (
            "❌ <b>pyautogui</b> o'rnatilmagan.\n\n"
            "O'rnatish:\n<code>pip install pyautogui</code>\n\n"
            "Windows da: <code>pip install pyautogui pyperclip</code>\n"
            "Linux da DISPLAY muhit o'zgaruvchisi kerak bo'lishi mumkin."
        )
    try:
        from PIL import Image   # noqa: F401
    except ImportError:
        return False, "❌ <b>Pillow</b> o'rnatilmagan: <code>pip install Pillow</code>"
    return True, ""


@router.message(Command("kompyuter", "computer", "kom"))
async def cmd_kompyuter(
    message: Message,
    command: CommandObject,
    config: Config,
) -> None:
    global _active_agent, _active_user

    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return

    # Kutubxonalarni tekshirish
    ok, err_msg = _check_agent_available()
    if not ok:
        await message.reply(err_msg)
        return

    task = (command.args or "").strip()
    if not task:
        await message.reply(
            "🤖 <b>Avtonom kompyuter agenti</b>\n\n"
            "Foydalanish:\n"
            "<code>/kompyuter vazifa matni</code>\n\n"
            "Misol:\n"
            "• <code>/kompyuter Chrome ochib google.com ga kir</code>\n"
            "• <code>/kompyuter Notepad ochib salom dunyo yoz va saqlا</code>\n"
            "• <code>/kompyuter Ish stoli rasmini ko'rsat</code>\n\n"
            "To'xtatish: <code>/stop</code>\n\n"
            "⚠️ Agent sizning ekraningizni ko'radi va boshqaradi. "
            "To'xtatish uchun sichqonni ekran burchagiga olib boring yoki /stop bosing."
        )
        return

    if _active_agent is not None:
        await message.reply(
            "⚠️ Agent allaqachon ishlayapti!\n"
            "Avval <code>/stop</code> buyrug'i bilan to'xtating."
        )
        return

    # Agent yaratish
    try:
        from computer_agent import ComputerAgent
    except ImportError:
        await message.reply("❌ computer_agent moduli topilmadi.")
        return

    ollama_url    = getattr(config, "ollama_base_url", "http://localhost:11434")
    vision_model  = getattr(config, "ollama_vision_model", "") or "llava"

    _active_agent = ComputerAgent(
        ollama_url=ollama_url,
        vision_model=vision_model,
    )
    _active_user = message.from_user.id

    await message.reply(
        f"🤖 <b>Agent ishga tushdi!</b>\n\n"
        f"📋 Vazifa: {task}\n"
        f"👁️ Model: {vision_model}\n"
        f"⏱ Max qadamlar: 25\n\n"
        "Har qadam natijasi shu yerga yuboriladi.\n"
        "To'xtatish: <code>/stop</code>"
    )

    # Asinxron ishga tushirish (main thread ni blokirovka qilmaslik)
    asyncio.create_task(
        _run_agent(
            agent=_active_agent,
            task=task,
            chat_id=message.chat.id,
            bot=message.bot,
        )
    )


@router.message(Command("stop", "bekor"))
async def cmd_stop(message: Message, config: Config) -> None:
    global _active_agent, _active_user

    if not (message.from_user and config.is_manager(message.from_user.id)):
        await message.reply("⛔️ Bu komanda faqat rahbar uchun.")
        return

    if _active_agent is None:
        await message.reply("ℹ️ Hech qanday agent ishlamayapti.")
        return

    _active_agent.stop()
    await message.reply("⛔ Agent to'xtatilmoqda...")


async def _run_agent(
    agent,
    task: str,
    chat_id: int,
    bot,
) -> None:
    global _active_agent, _active_user

    async def on_step(step: int, msg: str, scr: Optional[bytes]) -> None:
        try:
            if scr:
                await bot.send_photo(
                    chat_id,
                    BufferedInputFile(scr, filename=f"qadam_{step}.png"),
                    caption=f"📸 {msg}",
                )
            else:
                await bot.send_message(chat_id, f"📍 {msg}")
        except Exception as exc:
            logger.warning("on_step yuborish xato: %s", exc)

    async def on_done(msg: str, success: bool, scr: Optional[bytes]) -> None:
        icon = "✅" if success else "❌"
        try:
            if scr:
                await bot.send_photo(
                    chat_id,
                    BufferedInputFile(scr, filename="yakuniy.png"),
                    caption=f"{icon} <b>Yakuniy natija</b>\n\n{msg}",
                )
            else:
                await bot.send_message(
                    chat_id,
                    f"{icon} <b>Yakuniy natija</b>\n\n{msg}",
                )
        except Exception as exc:
            logger.warning("on_done yuborish xato: %s", exc)

    try:
        await agent.run(task=task, on_step=on_step, on_done=on_done)
    except Exception as exc:
        logger.error("Agent xato: %s", exc)
        try:
            await bot.send_message(chat_id, f"❌ Agent kutilmagan xato: {exc}")
        except Exception:
            pass
    finally:
        _active_agent = None
        _active_user  = None
