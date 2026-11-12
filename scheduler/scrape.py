"""
Разовый обход всех сайтов с сохранением в базу. Запускается по расписанию
в GitHub Actions (.github/workflows/scrape.yml) — там есть Chromium и
достаточно памяти, а бот на хостинге только читает готовую базу.

Локально: python -m scheduler.scrape (база берётся из DATABASE_URL или DB_PATH).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from config import database_from_env
from parsers.registry import build_parsers
from scheduler.jobs import run_all_parsers
from storage.db import init_db, make_engine, make_session_factory
from storage.repository import EventRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main() -> int:
    engine = make_engine(database_from_env())
    await init_db(engine)
    repo = EventRepository(make_session_factory(engine))
    parsers = build_parsers()
    await run_all_parsers(parsers, repo, max_concurrent=int(os.getenv("MAX_CONCURRENT_PARSERS", "3")))
    await engine.dispose()

    # Если не сработал ни один источник — что-то сломано глобально (сеть,
    # браузер, база). Падаем с ошибкой, чтобы GitHub прислал уведомление.
    if not any(p.last_ok for p in parsers):
        logging.error("Ни один парсер не отработал")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
