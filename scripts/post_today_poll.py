"""
Ежедневная публикация опроса "сегодня я иду..." в канал. Запускается по
расписанию в GitHub Actions (.github/workflows/daily_poll.yml) — бот на
Render засыпает и сам по часам ничего сделать не может.

Формат тот же, что у кнопки "📤 Опубликовать сегодня", но без превью:
опрос сразу уходит в канал. Если квизов на сегодня нет — ничего не шлём.

    python -m scripts.post_today_poll
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot
from dotenv import load_dotenv

from bot.handlers.admin import (
    _MAX_OPTIONS_PER_POLL,
    _OPT_OUT,
    _chunk,
    _poll_option,
    _poll_question,
)
from config import database_from_env
from storage.db import make_engine, make_session_factory
from storage.repository import EventRepository
from utils.clock import today_astana
from utils.merge import merge_mirrors

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def main() -> int:
    load_dotenv()
    token, channel = os.getenv("BOT_TOKEN"), os.getenv("CHANNEL_ID")
    if not token or not channel:
        logging.error("Нужны BOT_TOKEN и CHANNEL_ID")
        return 1

    engine = make_engine(database_from_env())
    today = today_astana()
    events = merge_mirrors(
        await EventRepository(make_session_factory(engine)).get_upcoming(from_date=today, to_date=today)
    )
    await engine.dispose()

    if not events:
        logging.info("На %s квизов нет — опрос не публикуем", today)
        return 0

    chunks = _chunk(events, _MAX_OPTIONS_PER_POLL)
    async with Bot(token=token) as bot:
        for i, chunk in enumerate(chunks, start=1):
            await bot.send_poll(
                chat_id=channel,
                question=_poll_question(today, i, len(chunks)),
                options=[_poll_option(e) for e in chunk] + [_OPT_OUT],
                is_anonymous=True,
                allows_multiple_answers=True,
            )
    logging.info("Опубликовано опросов: %d (квизов: %d) в %s", len(chunks), len(events), channel)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
