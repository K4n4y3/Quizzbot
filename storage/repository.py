from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.event import QuizEvent
from storage.db import EventRow, PollLog
from utils.clock import today_astana


def _insert(session: AsyncSession, table):
    """INSERT с поддержкой ON CONFLICT для того диалекта, с которым работает сессия."""
    dialect_insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    return dialect_insert(table)


class EventRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_many(self, events: list[QuizEvent]) -> int:
        """
        Сохраняет события, игнорируя дубликаты (по dedupe_hash).
        Возвращает количество РЕАЛЬНО новых записей.

        INSERT ... ON CONFLICT DO NOTHING на уровне БД, а не "сначала SELECT потом решай" —
        так это остаётся корректным, даже если несколько источников
        парсятся параллельно и одновременно пишут.
        """
        if not events:
            return 0

        rows = [
            {
                "dedupe_hash": e.dedupe_hash,
                "source": e.source,
                "title": e.title,
                "event_date": e.event_date,
                "event_time": e.event_time,
                "venue": e.venue,
                "address": e.address,
                "price": e.price,
                "city": e.city,
                "url": e.url,
                "raw_text": e.raw_text,
                "is_manual": e.is_manual,
            }
            for e in events
        ]

        async with self._session_factory() as session:
            stmt = _insert(session, EventRow).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_hash"])
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def get_upcoming(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        city: str | None = None,
        limit: int = 1000,
    ) -> list[EventRow]:
        from_date = from_date or today_astana()

        stmt = select(EventRow).where(EventRow.event_date >= from_date)
        if to_date is not None:
            stmt = stmt.where(EventRow.event_date <= to_date)
        if city is not None:
            stmt = stmt.where(EventRow.city == city)
        stmt = stmt.order_by(EventRow.event_date, EventRow.event_time).limit(limit)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_manual_upcoming(self, *, from_date: date | None = None) -> list[EventRow]:
        """Вручную добавленные события (для админского списка /мои квизы)."""
        from_date = from_date or today_astana()
        stmt = (
            select(EventRow)
            .where(EventRow.is_manual.is_(True), EventRow.event_date >= from_date)
            .order_by(EventRow.event_date, EventRow.event_time)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_manual(self, event_id: int) -> bool:
        """
        Удаляет вручную добавленное событие по id. Условие `is_manual` —
        подстраховка, чтобы админ случайно не мог этим же путём удалить
        событие, пришедшее с парсера (у него другой id, но на всякий случай).
        """
        stmt = delete(EventRow).where(EventRow.id == event_id, EventRow.is_manual.is_(True))
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def delete_stale_for_source(
        self, source: str, fresh: list[QuizEvent], *, today: date | None = None
    ) -> int:
        """
        Удаляет спарсенные (не ручные) записи источника, которых нет в
        свежем снимке его сайта. Без этого переименованная или перенесённая
        игра копилась бы дублями: хэш включает название и площадку, так что
        новая версия — это для БД другое событие, а старая остаётся.

        Сегодняшние игры не трогаем: часть сайтов (Play Quiz) убирает игру,
        как только она началась, и вечером "Сегодня" теряло бы идущие игры.
        Их уберёт delete_past() на следующий день.
        """
        today = today or today_astana()
        hashes = [e.dedupe_hash for e in fresh]
        stmt = delete(EventRow).where(
            EventRow.source == source,
            EventRow.is_manual.is_(False),
            EventRow.event_date > today,
            EventRow.dedupe_hash.not_in(hashes),
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def delete_past(self, *, before: date | None = None) -> int:
        """
        Удаляет события с датой раньше `before` (по умолчанию — сегодня).

        Держит таблицу компактной: прошедшие квизы никому не интересны,
        а `get_upcoming` и так фильтрует по event_date >= today, так что
        для пользователя это ничего не меняет — просто БД не растёт
        бесконечно.
        """
        before = before or today_astana()
        stmt = delete(EventRow).where(EventRow.event_date < before)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def poll_posted(self, day: date) -> bool:
        async with self._session_factory() as session:
            return await session.get(PollLog, day) is not None

    async def mark_poll_posted(self, day: date) -> None:
        async with self._session_factory() as session:
            stmt = _insert(session, PollLog).values(day=day).on_conflict_do_nothing(index_elements=["day"])
            await session.execute(stmt)
            await session.commit()
