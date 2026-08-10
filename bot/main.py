"""Botning kirish nuqtasi."""
from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web as aiohttp_web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import load_config
from .database import Database
from .handlers import setup_routers
from .middlewares import AlbumMiddleware, DependencyMiddleware
from .scheduler import setup_scheduler
from .ai import create_ai_client
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

    # AI klienti — provayder .env bo'yicha avtomatik tanlanadi
    ai_client = create_ai_client(config)

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

    # Mini App web server
    webapp_runner = None
    if config.webapp_enabled:
        from .webapp import create_webapp
        webapp     = create_webapp(config, db, bot)
        webapp_runner = aiohttp_web.AppRunner(webapp)
        await webapp_runner.setup()
        site = aiohttp_web.TCPSite(webapp_runner, config.webapp_host, config.webapp_port)
        try:
            await site.start()
        except OSError as exc:
            if exc.errno in (98, 10048):  # Linux EADDRINUSE / Windows
                logger.error(
                    "❌ Port %s band! Avvalgi bot hali ishlayapti.\n"
                    "  Windows: Task Manager oching → python.exe ni topib 'End Task' bosing\n"
                    "  Yoki .env faylida WEBAPP_PORT=8081 yozing va qayta ishga tushiring.",
                    config.webapp_port,
                )
                sys.exit(1)
            raise
        logger.info("Mini App server ishga tushdi: http://%s:%s  (WEBAPP_URL=%s)",
                    config.webapp_host, config.webapp_port, config.webapp_url)
    else:
        logger.info("Mini App o'chirilgan (WEBAPP_URL sozlanmagan).")

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
        if webapp_runner:
            await webapp_runner.cleanup()
        if config.userbot_enabled:
            await userbot.stop()
        await db.close()
        if ai_client:
            await ai_client.close()
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")


if __name__ == "__main__":
    run()
