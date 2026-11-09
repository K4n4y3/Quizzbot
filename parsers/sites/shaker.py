"""
Парсер astana.shakerquiz.ru (Shaker Quiz).

Сайт на Next.js с SSR: HTML-разметка карточек почти пустая для скрапинга,
зато вся нужная нам структура данных уже лежит готовым JSON в
`<script id="__NEXT_DATA__">` на странице — сайт сам подгружает из него
React-стейт при гидратации. Проверено (2026-09-23): JSON есть в исходном
HTML без выполнения JS, поэтому httpx хватает, Playwright не нужен.

Структура `__NEXT_DATA__.props.pageProps.store` — это кэш SWR-запросов
в виде списка пар [ключ_запроса, данные]. Нужные нам ключи:
  "GET/games/search"              -> список игр (id, name, event_time, price, status)
  "GET/games/venue/:venue/search" -> список площадок (name="Бар, адрес", game_id)
Площадка находится по `venue.game_id == game.id`.

`event_time` — ISO-строка с суффиксом Z (напр. "2026-09-23T20:00:00.000Z"),
но это НЕ настоящий UTC: бэкенд Shaker так сериализует локальное время
Астаны (сверено вручную: 20:00 для вечерней игры — это явно локальное
время, а не UTC). Поэтому просто берём час:минуту из строки как есть,
без конвертации таймзоны.

Берём только игры со `status == "Publish"` и `visibility == "Visible"`.
В данных страницы лежат и прошедшие ("Finish"), и отменённые организатором
("Cancel") игры — сайт отдаёт их вместе с настоящими.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from models.event import QuizEvent
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.shakerquiz.ru/"
GAMES_KEY = "GET/games/search"
VENUES_KEY = "GET/games/venue/:venue/search"
_KNOWN_STATUSES = {"Publish", "Finish", "Cancel"}


class ShakerQuizParser(BaseParser):
    source_name = "Shaker Quiz"

    async def parse(self) -> list[QuizEvent]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                BASE_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; QuizScheduleBot/1.0)"},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script or not script.string:
            logger.warning("Shaker Quiz: не нашёл __NEXT_DATA__ на странице")
            return []

        try:
            data = json.loads(script.string)
            store = data["props"]["pageProps"]["store"]
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("Shaker Quiz: не удалось разобрать __NEXT_DATA__")
            return []

        games = self._find_store_entry(store, GAMES_KEY) or []
        venues = self._find_store_entry(store, VENUES_KEY) or []
        venue_by_game_id = {v.get("game_id"): v for v in venues}

        events: list[QuizEvent] = []
        for game in games:
            event = self._parse_game(game, venue_by_game_id.get(game.get("id")))
            if event:
                events.append(event)

        return events

    @staticmethod
    def _find_store_entry(store: list, key: str) -> list | None:
        for entry in store:
            if isinstance(entry, list) and len(entry) == 2 and entry[0] == key:
                return entry[1]
        return None

    def _parse_game(self, game: dict, venue: dict | None) -> QuizEvent | None:
        status, visibility = game.get("status"), game.get("visibility")
        if status not in _KNOWN_STATUSES:
            logger.warning("Shaker Quiz: неизвестный статус %r у игры %r", status, game.get("name"))
        if status != "Publish" or visibility != "Visible":
            return None

        title = (game.get("name") or "").strip()
        raw_time = game.get("event_time")
        if not title or not raw_time:
            return None

        try:
            dt = datetime.fromisoformat(raw_time.replace("Z", ""))
        except ValueError:
            logger.warning("Shaker Quiz: не удалось разобрать event_time %r", raw_time)
            return None

        venue_name, address = "уточняется", None
        if venue and venue.get("name"):
            full = venue["name"]
            if "," in full:
                venue_name, address = (p.strip() for p in full.split(",", 1))
            else:
                venue_name = full

        price = game.get("price")

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=dt.date(),
            event_time=dt.time(),
            venue=venue_name,
            address=address,
            price=f"{price} ₸" if price is not None else None,
            city="Астана",
            url=BASE_URL,
            raw_text=f"{title} | {raw_time}",
        )
