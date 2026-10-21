"""
Парсер astana.wowquiz.ru (Вау Квиз).

Главная страница — Nuxt SPA-заглушка ("Загружаем расписание..."),
расписание живёт на /schedule, тоже клиентский рендеринг (проверено —
curl отдаёт только 12KB JS-каркаса, ни одной карточки). Playwright.

Карточка `.schedule-card` — селекторы чистые и подписанные (DevTools,
2026-09-23):
  .schedule-card__title                       — название
  .schedule-card__details-item.--date span     — "25 сентября, пятница"
  .schedule-card__details-item.--time span     — "20:00"
  .schedule-card__details-item.--price span    — "3000 ₸/чел."
  .schedule-card__bar                           — площадка
  .schedule-card__bar-address                    — адрес
  a[href^="/games/"] с текстом "Страница игры"  — ссылка на страницу игры
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from parsers.browser import goto, open_page, wait_for_items

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.wowquiz.ru"
SCHEDULE_URL = BASE_URL + "/schedule"
CARD_SELECTOR = ".schedule-card"


class WowQuizParser(BaseParser):
    source_name = "WOW Quiz"
    uses_browser = True

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        async with open_page() as page:
            await goto(page, SCHEDULE_URL)
            cards = page.locator(CARD_SELECTOR)
            count = await wait_for_items(cards, timeout=15_000)

            for i in range(count):
                card = cards.nth(i)
                href = card.locator('a[href^="/games/"]').first
                cards_data.append(
                    {
                        "title": await card.locator(".schedule-card__title").text_content(),
                        "date": await card.locator(
                            ".schedule-card__details-item.--date span"
                        ).text_content(),
                        "time": await card.locator(
                            ".schedule-card__details-item.--time span"
                        ).text_content(),
                        "price": await card.locator(
                            ".schedule-card__details-item.--price span"
                        ).text_content(),
                        "venue": await card.locator(".schedule-card__bar").text_content(),
                        "address": await card.locator(
                            ".schedule-card__bar-address"
                        ).text_content(),
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
        title = (data["title"] or "").strip()
        raw_date = (data["date"] or "").strip()
        if not title or not raw_date:
            return None

        try:
            event_date = extract_date(raw_date)
        except DateParseError:
            logger.warning("WOW Quiz: не удалось разобрать дату %r", raw_date)
            return None

        raw_time = (data["time"] or "").strip()
        event_time = extract_time(raw_time) if raw_time else None

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=event_time,
            venue=(data["venue"] or "уточняется").strip(),
            address=(data["address"] or "").strip() or None,
            price=(data["price"] or "").strip() or None,
            city="Астана",
            url=urljoin(BASE_URL, data["href"]) if data["href"] else SCHEDULE_URL,
            raw_text=f"{title} | {raw_date} {raw_time}",
        )
