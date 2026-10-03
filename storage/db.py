from __future__ import annotations

from datetime import date, time

from sqlalchemy import Boolean, Date, String, Time, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("dedupe_hash", name="uq_events_dedupe_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64), index=True)

    source: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    event_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    venue: Mapped[str] = mapped_column(String(300))
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    price: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str] = mapped_column(String(100), default="Астана")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


def make_engine(db_path: str):
    """db_path напр. 'quizbot.sqlite3' (относительный) или '/data/quizbot.sqlite3'."""
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # На старых базах, созданных до появления is_manual, create_all не
        # добавит колонку в уже существующую таблицу — делаем это вручную.
        result = await conn.exec_driver_sql("PRAGMA table_info(events)")
        columns = {row[1] for row in result.fetchall()}
        if "is_manual" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN is_manual BOOLEAN NOT NULL DEFAULT 0"
            )
