from __future__ import annotations

from datetime import date, time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import Boolean, Date, String, Text, Time, UniqueConstraint, false
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("dedupe_hash", name="uq_events_dedupe_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64), index=True)

    # Text, а не String(N): Postgres, в отличие от SQLite, обрезанную длину
    # не прощает — одно слишком длинное название с сайта уронило бы вставку
    # всего пакета.
    source: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    event_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    venue: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(Text, default="Астана")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class PollLog(Base):
    """Дни, за которые ежедневный опрос уже опубликован — защита от дублей."""

    __tablename__ = "poll_log"

    day: Mapped[date] = mapped_column(Date, primary_key=True)


class SourceHealth(Base):
    """Сколько обновлений подряд источник не отдаёт игры и было ли оповещение."""

    __tablename__ = "source_health"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    fail_streak: Mapped[int] = mapped_column(default=0)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


def _postgres_url(url: str) -> tuple[str, dict]:
    """
    Строка подключения Neon/Supabase ("postgresql://...?sslmode=require")
    -> вид для asyncpg. asyncpg не понимает sslmode/channel_binding в URL —
    SSL передаём через connect_args.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    needs_ssl = query.pop("sslmode", None) not in (None, "disable")
    query.pop("channel_binding", None)
    url = urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), ""))
    # statement_cache_size=0 — совместимость с пулером соединений (pgbouncer
    # у Neon/Supabase), который не поддерживает подготовленные запросы asyncpg.
    connect_args: dict = {"statement_cache_size": 0}
    if needs_ssl:
        connect_args["ssl"] = "require"
    return url, connect_args


def make_engine(database: str):
    """
    `database` — либо URL Postgres (DATABASE_URL), либо путь к файлу SQLite
    (локальный режим и тесты, напр. 'quizbot.sqlite3' или ':memory:').
    """
    if database.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
        url, connect_args = _postgres_url(database)
        # pool_pre_ping: бесплатная база засыпает и рвёт простаивающие соединения.
        return create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    return create_async_engine(f"sqlite+aiosqlite:///{database}", echo=False)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name != "sqlite":
            return
        # На старых SQLite-базах, созданных до появления is_manual, create_all
        # не добавит колонку в уже существующую таблицу — делаем это вручную.
        result = await conn.exec_driver_sql("PRAGMA table_info(events)")
        columns = {row[1] for row in result.fetchall()}
        if "is_manual" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE events ADD COLUMN is_manual BOOLEAN NOT NULL DEFAULT 0"
            )
