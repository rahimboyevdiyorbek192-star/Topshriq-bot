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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


COMMANDS = [
    BotCommand(command="svodka", description="Umumiy svodka / N-topshiriq svodkasi"),
    BotCommand(command="excel", description="Svodkani Excel faylda yuklab olish"),
    BotCommand(command="topshiriqlar", description="Ochiq topshiriqlar ro'yxati"),
    BotCommand(command="eslatma", description="Bajarmaganlarga eslatma yuborish"),
    BotCommand(command="hodimlar", description="Xodimlar ro'yxati"),
    BotCommand(command="mening", description="Mening topshiriqlarim holati"),
    BotCommand(command="id", description="Chat va foydalanuvchi ID"),
    BotCommand(command="help", description="Yordam / qo'llanma"),
]


async def main() -> None:
    config = load_config()

    db = Database(config.db_path)
    await db.connect()
    logger.info("Ma'lumotlar bazasi ulandi: %s", config.db_path)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middleware'lar
    deps = DependencyMiddleware(config, db)
    album = AlbumMiddleware()
    # Outer middleware — filtrlardan oldin ishlaydi (albom qismlarini yig'ish uchun zarur).
    dp.message.outer_middleware(deps)
    dp.message.outer_middleware(album)

    dp.include_router(setup_routers())

    scheduler = setup_scheduler(bot, db, config)
    scheduler.start()
    logger.info("Scheduler ishga tushdi (eslatmalar).")

    try:
        await bot.set_my_commands(COMMANDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Komandalar o'rnatilmadi: %s", exc)

    me = await bot.get_me()
    logger.info("Bot ishga tushdi: @%s", me.username)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await db.close()
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")


if __name__ == "__main__":
    run()
