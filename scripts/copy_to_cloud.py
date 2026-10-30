"""
Перенос предстоящих событий (в том числе ручных квизов) из локальной SQLite
в облачную базу из DATABASE_URL. Повторный запуск безопасен: дубли
отбрасываются по dedupe_hash.

    python -m scripts.copy_to_cloud [путь к sqlite, по умолчанию quizbot.sqlite3]
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import select

from models.event import QuizEvent
from storage.db import EventRow, init_db, make_engine, make_session_factory
from storage.repository import EventRepository
from utils.clock import today_astana


async def main(source_path: str) -> None:
    load_dotenv()
    target_url = os.getenv("DATABASE_URL")
    if not target_url:
        sys.exit("DATABASE_URL не задан в .env — некуда переносить.")

    source = make_engine(source_path)
    async with make_session_factory(source)() as session:
        rows = (
            await session.execute(select(EventRow).where(EventRow.event_date >= today_astana()))
        ).scalars().all()
    await source.dispose()

    events = [
        QuizEvent(
            source=r.source, title=r.title, event_date=r.event_date, venue=r.venue,
            event_time=r.event_time, address=r.address, price=r.price, city=r.city,
            url=r.url, raw_text=r.raw_text, is_manual=r.is_manual,
        )
        for r in rows
    ]

    target = make_engine(target_url)
    await init_db(target)
    inserted = await EventRepository(make_session_factory(target)).save_many(events)
    await target.dispose()

    manual = sum(e.is_manual for e in events)
    print(f"Найдено предстоящих событий: {len(events)} (ручных: {manual}). Добавлено в облако: {inserted}.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "quizbot.sqlite3"))
