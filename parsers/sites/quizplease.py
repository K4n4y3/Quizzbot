"""
Парсер расписания "Квиз, плиз!" (astana.quizplease.com).

Берём данные напрямую из JSON API, которым пользуется сама страница
/schedule. Раньше здесь был Playwright, но сайт стоит за защитой Cloudflare,
и браузер из GitHub Actions карточек не получал: новые игры переставали
попадать в базу. API отвечает на обычный запрос и не зависит от вёрстки.

Статусы — тот же набор, что запрашивает сайт. Дата приходит строкой
"10.11.2026 20:00" в местном времени города.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from models.event import QuizEvent
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.quizplease.com"
API_URL = "https://api.quizplease.com/api/games/schedule/29"  # 29 — id Астаны
_STATUSES = ("0", "1", "2", "3", "5")
_PER_PAGE = "100"


class QuizPleaseParser(BaseParser):
    source_name = "Квиз, плиз!"

    async def parse(self) -> list[QuizEvent]:
        games: list[dict] = []
        page = 1
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            while True:
                params = [("per_page", _PER_PAGE), ("page", str(page)), ("order", "date")]
                params += [("statuses[]", s) for s in _STATUSES]
                response = await client.get(
                    API_URL,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                )
                response.raise_for_status()
                data = response.json()["data"]
                games.extend(data["data"])
                if page >= data["pagination"]["total_pages"]:
                    break
                page += 1

        return [event for event in map(self._parse_game, games) if event]

    def _parse_game(self, game: dict) -> QuizEvent | None:
        title = (game.get("title") or "").strip()
        raw_date = game.get("date") or ""
        try:
            dt = datetime.strptime(raw_date, "%d.%m.%Y %H:%M")
        except ValueError:
            logger.warning("QuizPlease: не удалось разобрать дату %r", raw_date)
            return None
        if not title:
            return None

        if game.get("game_number"):
            title = f"{title} #{game['game_number']}"

        place = game.get("place") or {}
        price = game.get("current_price") or game.get("price")

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=dt.date(),
            event_time=dt.time(),
            venue=(place.get("title") or "уточняется").strip(),
            address=(place.get("address") or "").strip() or None,
            price=f"{price} ₸" if price else None,
            city="Астана",
            url=f"{BASE_URL}/game/{game['id']}" if game.get("id") else f"{BASE_URL}/schedule",
            raw_text=f"{title} | {raw_date}",
        )
