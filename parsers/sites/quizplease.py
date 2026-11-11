"""
Парсер расписания "Квиз, плиз!" (astana.quizplease.com).

Данные — JSON API, которым пользуется сама страница /schedule. Сайт стоит за
защитой Cloudflare: с домашнего интернета API отвечает на обычный запрос, а
с серверов (GitHub Actions, Render) — 403. Тогда открываем страницу целиком
в браузере: проверочный скрипт Cloudflare отрабатывает, страница сама
запрашивает API, и мы берём этот ответ. Браузер ничем не маскируется.

Статусы — тот же набор, что запрашивает сайт. Дата приходит строкой
"10.11.2026 20:00" в местном времени города.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

from models.event import QuizEvent
from parsers.base import BaseParser
from parsers.browser import goto, open_page

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.quizplease.com"
SCHEDULE_URL = BASE_URL + "/schedule"
API_URL = "https://api.quizplease.com/api/games/schedule/29"  # 29 — id Астаны
_STATUSES = ("0", "1", "2", "3", "5")
_PER_PAGE = "100"
_BROWSER_WAIT_S = 40


class QuizPleaseParser(BaseParser):
    source_name = "Квиз, плиз!"
    uses_browser = True  # браузер нужен только при отказе API, но тогда он тяжёлый

    async def parse(self) -> list[QuizEvent]:
        try:
            games = await self._fetch_api()
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 403:
                raise
            logger.info("QuizPlease: API ответил 403, открываю страницу в браузере")
            games = await self._fetch_via_page()
        return [event for event in map(self._parse_game, games) if event]

    async def _fetch_via_page(self) -> list[dict]:
        # Ждём, пока страница сама получит расписание (значит, проверка
        # пройдена), затем из неё же запрашиваем все страницы: сама она
        # грузит только первые 10 игр.
        loaded = asyncio.get_running_loop().create_future()

        def on_response(response) -> None:
            if "/api/games/schedule/" in response.url and response.ok and not loaded.done():
                loaded.set_result(None)

        async with open_page(block_noise=False) as page:
            page.on("response", on_response)
            await goto(page, SCHEDULE_URL)
            await asyncio.wait_for(loaded, _BROWSER_WAIT_S)

            games: list[dict] = []
            page_no = 1
            while True:
                url = str(httpx.URL(API_URL, params=self._params(page_no)))
                data = (await page.evaluate("async (u) => (await fetch(u)).json()", url))["data"]
                games.extend(data["data"])
                if page_no >= data["pagination"]["total_pages"]:
                    return games
                page_no += 1

    @staticmethod
    def _params(page: int) -> list[tuple[str, str]]:
        params = [("per_page", _PER_PAGE), ("page", str(page)), ("order", "date")]
        return params + [("statuses[]", s) for s in _STATUSES]

    async def _fetch_api(self) -> list[dict]:
        games: list[dict] = []
        page = 1
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            while True:
                response = await client.get(
                    API_URL,
                    params=self._params(page),
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                )
                response.raise_for_status()
                data = response.json()["data"]
                games.extend(data["data"])
                if page >= data["pagination"]["total_pages"]:
                    break
                page += 1
        return games

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
