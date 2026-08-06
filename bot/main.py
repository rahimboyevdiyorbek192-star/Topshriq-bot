"""Botning kirish nuqtasi."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import load_config
from .database import Database
from .handlers import setup_routers
from .middlewares import AlbumMiddleware, DependencyMiddleware
from .scheduler import setup_scheduler
from .userbot import create_userbot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


COMMANDS = [
    BotCommand(command="menu",          description="Asosiy menyu (tugmalar)"),
    BotCommand(command="svodka",        description="Umumiy svodka (rasm + matn)"),
    BotCommand(command="excel",         description="Svodkani Excel faylda yuklab olish"),
    BotCommand(command="reyting",       description="Xodimlar samaradorlik reytingi"),
    BotCommand(command="topshiriqlar",  description="Ochiq topshiriqlar ro'yxati"),
    BotCommand(command="eslatma",       description="Bajarmaganlarga eslatma yuborish"),
    BotCommand(command="hodimlar",      description="Xodimlar ro'yxati"),
    BotCommand(command="mening",        description="Mening topshiriqlarim holati"),
    BotCommand(command="ai",            description="AI mutaxassis bilan suhbat"),
    BotCommand(command="umumlashtir",   description="Fayllarni umumlashtirish + ZIP"),
    BotCommand(command="id",            description="Chat va foydalanuvchi ID"),
    BotCommand(command="help",          description="Yordam / qo'llanma"),
]


async def main() -> None:
    config = load_config()

    db = Database(config.db_path)
    await db.connect()
    logger.info("Ma'lumotlar bazasi ulandi: %s", config.db_path)

    # AI klienti (Ollama yoki Claude)
    ai_client = None
    if config.use_ollama:
        from .ai_ollama import OllamaClient
        ai_client = OllamaClient(config.ollama_base_url, config.ollama_model)
        logger.info("Mahalliy AI (Ollama) yoqildi: %s / %s",
                    config.ollama_base_url, config.ollama_model)
    elif config.anthropic_api_key:
        from .ai import AIClient
        ai_client = AIClient(config.anthropic_api_key, config.anthropic_model)
        logger.info("Claude AI yoqildi (model: %s)", config.anthropic_model)
    else:
        logger.info("AI o'chirilgan (API kalit yo'q).")

    # Userbot (Telethon)
    userbot = create_userbot(
        config.tg_api_id, config.tg_api_hash, config.tg_userbot_session
    )
    if config.userbot_enabled:
        started = await userbot.start()
        if started:
            logger.info("Userbot ulandi — shaxsiy eslatmalar yoqilgan.")
        else:
            logger.warning("Userbot ulanmadi — faqat guruh eslatmalari ishlaydi.")

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    deps  = DependencyMiddleware(config, db, ai=ai_client)
    album = AlbumMiddleware()
    dp.message.outer_middleware(deps)
    dp.message.outer_middleware(album)
    dp.callback_query.outer_middleware(deps)
    dp.channel_post.outer_middleware(deps)
    dp.channel_post.outer_middleware(album)

    dp.include_router(setup_routers())

    scheduler = setup_scheduler(bot, db, config, userbot=userbot)
    scheduler.start()
    logger.info("Scheduler ishga tushdi (har 5 daqiqada tekshiradi).")

    try:
        await bot.set_my_commands(COMMANDS)
    except Exception as exc:
        logger.warning("Komandalar o'rnatilmadi: %s", exc)

    me = await bot.get_me()
    logger.info("Bot ishga tushdi: @%s", me.username)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "channel_post"],
        )
    finally:
        scheduler.shutdown(wait=False)
        if config.userbot_enabled:
            await userbot.stop()
        await db.close()
        if ai_client and hasattr(ai_client, "close"):
            await ai_client.close()
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")


if __name__ == "__main__":
    run()
