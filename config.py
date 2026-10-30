from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _admin_ids() -> frozenset[int]:
    raw = os.getenv("ADMIN_USER_ID", "")
    return frozenset(int(part.strip()) for part in raw.split(",") if part.strip())


def database_from_env() -> str:
    """URL облачной базы (DATABASE_URL), иначе локальный файл SQLite (DB_PATH)."""
    load_dotenv()
    return os.getenv("DATABASE_URL") or os.getenv("DB_PATH", "quizbot.sqlite3")


@dataclass(frozen=True)
class Config:
    bot_token: str
    database: str
    parse_interval_minutes: int
    default_city: str
    max_concurrent_parsers: int
    admin_user_ids: frozenset[int]
    channel_id: str | None
    # Адрес, на который Telegram шлёт сообщения (режим вебхука на хостинге).
    # Пусто — бот работает поллингом (локально, на ноутбуке).
    webhook_base_url: str | None
    webhook_secret: str | None
    port: int
    # Парсить сайты по нажатию кнопки. На хостинге выключено: там нет
    # браузера, расписание обновляет GitHub Actions (scheduler/scrape.py).
    parse_on_demand: bool

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise RuntimeError(
                "BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите "
                "токен, полученный у @BotFather."
            )
        # Render сам выставляет RENDER_EXTERNAL_URL — внешний адрес сервиса.
        webhook_base_url = os.getenv("WEBHOOK_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")
        return cls(
            bot_token=token,
            database=database_from_env(),
            parse_interval_minutes=int(os.getenv("PARSE_INTERVAL_MINUTES", "60")),
            default_city=os.getenv("DEFAULT_CITY", "Астана"),
            max_concurrent_parsers=int(os.getenv("MAX_CONCURRENT_PARSERS", "1")),
            admin_user_ids=_admin_ids(),
            channel_id=os.getenv("CHANNEL_ID") or None,
            webhook_base_url=webhook_base_url or None,
            webhook_secret=os.getenv("WEBHOOK_SECRET") or None,
            port=int(os.getenv("PORT", "8080")),
            parse_on_demand=os.getenv("PARSE_ON_DEMAND", "0" if webhook_base_url else "1") == "1",
        )
