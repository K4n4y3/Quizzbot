"""
Ручная публикация ежедневного опроса (GitHub Actions → Run workflow или
локально). Если за сегодня опрос уже вышел — не дублирует, пока не задано
FORCE=1.

    python -m scripts.post_today_poll
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot
from dotenv import load_dotenv

from bot.daily_poll import post_daily_poll
from config import database_from_env
from storage.db import init_db, make_engine, make_session_factory
from storage.repository import EventRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def main() -> int:
    load_dotenv()
    token, channel = os.getenv("BOT_TOKEN"), os.getenv("CHANNEL_ID")
    if not token or not channel:
        logging.error("Нужны BOT_TOKEN и CHANNEL_ID")
        return 1

    engine = make_engine(database_from_env())
    await init_db(engine)
    repo = EventRepository(make_session_factory(engine))
    async with Bot(token=token) as bot:
        result = await post_daily_poll(bot, repo, channel, force=os.getenv("FORCE") == "1")
    await engine.dispose()
    logging.info(result)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
