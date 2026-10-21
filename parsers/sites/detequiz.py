"""
Парсер detequiz.com/kazakhstan/astana (Detequiz — детективные квизы).

Сайт активно блокирует не-браузерные запросы: curl с любым User-Agent
редиректит на /unsupported-browser (проверено — это не просто проверка
заголовка, обычный httpx получит ту же заглушку), поэтому здесь всегда
нужен настоящий браузер — Playwright, а не httpx.

Карточка — `li` внутри `ul.grid.gap-4` (DevTools, 2026-09-23):
  h3                          — "Дело: <название>"
  первый <p> с текстом        — дата, вид "вс, 27 сент., 17:00" (месяц —
                                 4-буквенное сокращение с точкой, см. фикс
                                 в utils/date_parser.py: добавлено "сент")
  второй <p> с текстом        — площадка
  ссылка на карточке (<a>)    — href на страницу регистрации
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from parsers.browser import goto, open_page, wait_for_items

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://detequiz.com"
SCHEDULE_URL = BASE_URL + "/kazakhstan/astana"
CARD_SELECTOR = "ul.grid.gap-4 > li"


class DetequizParser(BaseParser):
    source_name = "Detequiz"
    uses_browser = True

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        # Без явной локали сайт отдаёт англоязычную версию (даты вида
        # "Sun 27 Sept") — detequiz выбирает язык по Accept-Language, а не по URL.
        async with open_page(locale="ru-RU") as page:
            await goto(page, SCHEDULE_URL)
            cards = page.locator(CARD_SELECTOR)
            count = await wait_for_items(cards, timeout=15_000)

            for i in range(count):
                card = cards.nth(i)
                ps = card.locator("p")
                p_count = await ps.count()
                href = card.locator("a").first
                cards_data.append(
                    {
                        "title": await card.locator("h3").text_content(),
                        "date": await ps.nth(0).text_content() if p_count > 0 else "",
                        "venue": await ps.nth(1).text_content() if p_count > 1 else "",
                        "href": await href.get_attribute("href") if await href.count() else None,
                    }
                )

        events: list[QuizEvent] = []
        for data in cards_data:
            event = self._parse_card(data)
            if event:
                events.append(event)

        return events

    def _parse_card(self, data: dict) -> QuizEvent | None:
        raw_title = (data["title"] or "").strip()
        raw_date = (data["date"] or "").strip()
        if not raw_title or not raw_date:
            return None

        try:
            event_date = extract_date(raw_date)
        except DateParseError:
            logger.warning("Detequiz: не удалось разобрать дату %r", raw_date)
            return None

        event_time = extract_time(raw_date)
        title = raw_title.removeprefix("Дело:").strip() or raw_title

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=event_time,
            venue=(data["venue"] or "уточняется").strip(),
            city="Астана",
            url=urljoin(BASE_URL, data["href"]) if data["href"] else SCHEDULE_URL,
            raw_text=f"{raw_title} | {raw_date}",
        )
