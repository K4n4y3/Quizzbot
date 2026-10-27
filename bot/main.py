from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers.admin import register_admin_handlers
from bot.handlers.admin import router as admin_router
from bot.handlers.schedule import register_schedule_handlers
from bot.handlers.schedule import router as schedule_router
from config import Config
from parsers.base import BaseParser
from parsers.sites.chill import ChillQuizParser
from parsers.sites.detequiz import DetequizParser
from parsers.sites.einstein import EinsteinPartyParser
from parsers.sites.mohito import MohitoQuizParser
from parsers.sites.mozgo import MozgoQuizParser
from parsers.sites.peace import PeaceQuizParser
from parsers.sites.playquiz import PlayQuizParser
from parsers.sites.quizland import QuizlandParser
from parsers.sites.quizplease import QuizPleaseParser
from parsers.sites.shaker import ShakerQuizParser
from parsers.sites.smuzi import SmuziQuizParser
from parsers.sites.wow import WowQuizParser
from scheduler.jobs import ParseCoordinator
from storage.db import init_db, make_engine, make_session_factory
from storage.repository import EventRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def build_parsers() -> list[BaseParser]:
    """
    Список активных парсеров. Action, Teztap и Whiz Quiz сознательно не
    парсятся: их игры админ добавляет вручную (на сайтах нет времени/места
    или данных слишком мало).
    """
    return [
        QuizPleaseParser(),
        EinsteinPartyParser(),
        ShakerQuizParser(),
        SmuziQuizParser(),
        WowQuizParser(),
        PeaceQuizParser(),
        QuizlandParser(),
        MozgoQuizParser(),
        PlayQuizParser(),
        ChillQuizParser(),
        DetequizParser(),
        MohitoQuizParser(),
    ]


async def main() -> None:
    config = Config.from_env()

    engine = make_engine(config.db_path)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    repo = EventRepository(session_factory)

    parsers = build_parsers()
    coordinator = ParseCoordinator(
        parsers,
        repo,
        max_concurrent=config.max_concurrent_parsers,
        stale_after_minutes=config.parse_interval_minutes,
    )

    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(schedule_router)
    dp.include_router(admin_router)
    register_schedule_handlers(schedule_router, repo, coordinator, config)
    register_admin_handlers(admin_router, repo, config, coordinator)

    # Никакого фонового расписания: парсинг сайтов запускается лениво,
    # изнутри хендлеров /today, /week, /post_today — только когда кто-то
    # реально обращается к боту. См. ParseCoordinator.
    logger.info("Бот запущен, поллинг...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
