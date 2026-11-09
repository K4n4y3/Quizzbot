from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.daily_poll import post_daily_poll
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


WEBHOOK_PATH = "/webhook"


def _webhook_secret(config: Config) -> str:
    # Telegram присылает его в заголовке каждого запроса — так чужие запросы
    # на /webhook отбрасываются. Если не задан явно, выводим из токена бота:
    # он и так секретный, а настраивать на одну переменную меньше.
    return config.webhook_secret or hashlib.sha256(config.bot_token.encode()).hexdigest()[:32]


async def _run_webhook(bot: Bot, dp: Dispatcher, config: Config, repo: EventRepository) -> None:
    """Режим хостинга: Telegram сам присылает сообщения на наш адрес."""
    secret = _webhook_secret(config)
    url = f"{config.webhook_base_url.rstrip('/')}{WEBHOOK_PATH}"

    @dp.startup()
    async def _set_webhook(bot: Bot) -> None:
        await bot.set_webhook(url, secret_token=secret, allowed_updates=dp.resolve_used_update_types())
        logger.info("Вебхук установлен: %s", url)

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    def _authorized(request: web.Request) -> bool:
        key = request.headers.get("X-Cron-Key") or request.query.get("key")
        return bool(config.cron_secret) and hmac.compare_digest(key or "", config.cron_secret)

    async def daily_poll(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=404)
        if not config.channel_id:
            return web.Response(status=500, text="CHANNEL_ID не задан")
        return web.Response(text=await post_daily_poll(bot, repo, config.channel_id))

    async def refresh_quizplease(request: web.Request) -> web.Response:
        # Квиз, плиз! отвечает 403 на запросы с серверов GitHub Actions,
        # поэтому этот источник обновляется отсюда, по внешнему расписанию.
        if not _authorized(request):
            return web.Response(status=404)
        parser = QuizPleaseParser()
        events = await parser.fetch()
        if not parser.last_ok:
            return web.Response(status=502, text="сайт не ответил, подробности в логе")
        inserted = await repo.save_many(events)
        removed = await repo.delete_stale_for_source(parser.source_name, events) if events else 0
        return web.Response(text=f"найдено {len(events)}, новых {inserted}, устаревших удалено {removed}")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_route("*", "/cron/daily-poll", daily_poll)
    app.router.add_route("*", "/cron/refresh-quizplease", refresh_quizplease)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.port).start()
    logger.info("Бот запущен в режиме вебхука на порту %d", config.port)
    await asyncio.Event().wait()


async def main() -> None:
    config = Config.from_env()

    engine = make_engine(config.database)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    repo = EventRepository(session_factory)

    # На ноутбуке бот парсит сайты сам, по нажатию кнопки (см. ParseCoordinator).
    # На хостинге браузера нет — расписание в базе обновляет GitHub Actions.
    coordinator = None
    if config.parse_on_demand:
        coordinator = ParseCoordinator(
            build_parsers(),
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

    if config.webhook_base_url:
        await _run_webhook(bot, dp, config, repo)
        return

    # Поллинг и вебхук для одного бота несовместимы: снимаем вебхук. Если бот
    # в это время развёрнут на хостинге, он перестанет получать сообщения до
    # своего перезапуска — локально запускать стоит только с другим токеном
    # или когда хостинг не используется.
    if (await bot.get_webhook_info()).url:
        logger.warning("У бота был вебхук (хостинг) — снимаю его для локального поллинга")
        await bot.delete_webhook()
    logger.info("Бот запущен, поллинг...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
