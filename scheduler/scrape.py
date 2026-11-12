"""
Разовый обход всех сайтов с сохранением в базу. Запускается по расписанию
в GitHub Actions (.github/workflows/scrape.yml) — там есть Chromium и
достаточно памяти, а бот на хостинге только читает готовую базу.

После обхода:
- проверяет источники и шлёт оповещения о поломках в ALERT_CHAT_IDS
  (числовые Telegram ID через запятую, см. scheduler/health.py);
- если задан NOTIFY_CHAT_ID (обновление запустил админ кнопкой в боте),
  отправляет туда итог.

Локально: python -m scheduler.scrape (база берётся из DATABASE_URL или DB_PATH).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from config import database_from_env
from parsers.registry import build_parsers
from scheduler.health import check_health
from scheduler.jobs import run_all_parsers
from storage.db import init_db, make_engine, make_session_factory
from storage.repository import EventRepository
from utils.telegram import parse_chat_ids, send_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main() -> int:
    engine = make_engine(database_from_env())
    await init_db(engine)
    repo = EventRepository(make_session_factory(engine))
    parsers = build_parsers()
    result = await run_all_parsers(
        parsers, repo, max_concurrent=int(os.getenv("MAX_CONCURRENT_PARSERS", "3"))
    )
    alerts = await check_health(repo, parsers, result.results)
    await engine.dispose()

    token = os.getenv("BOT_TOKEN")
    alert_chats = parse_chat_ids(os.getenv("ALERT_CHAT_IDS"))
    if alerts:
        logging.warning("Оповещения: %s", alerts)
        if token and alert_chats:
            await send_text(token, alert_chats, "\n\n".join(alerts))

    notify_chat = os.getenv("NOTIFY_CHAT_ID")
    if token and notify_chat:
        failed = [p.source_name for p in parsers if not p.last_ok]
        summary = (
            f"🔄 Расписание обновлено за {result.seconds:.0f} с: найдено игр {result.found}, "
            f"новых {result.inserted}."
        )
        if failed:
            summary += "\nНе ответили: " + ", ".join(failed)
        await send_text(token, [notify_chat], summary)

    # Если не сработал ни один источник — что-то сломано глобально (сеть,
    # браузер, база). Падаем с ошибкой, чтобы GitHub прислал уведомление.
    if not any(p.last_ok for p in parsers):
        logging.error("Ни один парсер не отработал")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
