from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    parse_interval_minutes: int
    default_city: str
    max_concurrent_parsers: int
    admin_user_ids: frozenset[int]
    channel_id: str | None

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise RuntimeError(
                "BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите "
                "токен, полученный у @BotFather."
            )
        admin_user_ids_raw = os.getenv("ADMIN_USER_ID", "")
        admin_user_ids = frozenset(
            int(part.strip()) for part in admin_user_ids_raw.split(",") if part.strip()
        )
        return cls(
            bot_token=token,
            db_path=os.getenv("DB_PATH", "quizbot.sqlite3"),
            parse_interval_minutes=int(os.getenv("PARSE_INTERVAL_MINUTES", "60")),
            default_city=os.getenv("DEFAULT_CITY", "Астана"),
            max_concurrent_parsers=int(os.getenv("MAX_CONCURRENT_PARSERS", "4")),
            admin_user_ids=admin_user_ids,
            channel_id=os.getenv("CHANNEL_ID") or None,
        )
