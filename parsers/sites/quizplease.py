"""
Парсер astana.quizplease.com.

Изначально брался с главной страницы (httpx + BeautifulSoup, там она
статична) — но там только 3 "ближайшие игры". Полное расписание живёт на
/schedule, а этот роут уже рендерится клиентским JS (Nuxt CSR): curl его
не видит (проверено — 0 совпадений по классам карточек в исходном HTML),
поэтому здесь Playwright.

Структура карточки (DevTools, 2026-09-23), блок расписания на /schedule:
  .schedule-card-desktop
    .game-title-link[href]  — ссылка на страницу игры (/game/<uuid>), внутри h3.game-title
    .place-title             — площадка
    .place-address            — адрес
    .game-date               — дата и время, ДВА формата:
                                  "Сегодня, 20:00" (для игры сегодняшним днём)
                                  "24 сентября, 20:00 (Четверг)" (для остальных)
    .price-sum                — цена

Для "Сегодня, ..." дату не парсим через utils.date_parser (там только
день+месяц словом) — используем today_astana() напрямую (именно по
времени Астаны, а не сервера — см. utils/clock.py). Для остальных
формат "<день> <месяц словом>..." укладывается в extract_date/extract_time
как есть (день недели в скобках игнорируется — regex ищет только день+месяц).
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from parsers.browser import goto, open_page, wait_for_items

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.clock import today_astana
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.quizplease.com"
SCHEDULE_URL = BASE_URL + "/schedule"
CARD_SELECTOR = ".schedule-card-desktop"


class QuizPleaseParser(BaseParser):
    source_name = "Квиз, плиз!"
    uses_browser = True

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        async with open_page() as page:
            await goto(page, SCHEDULE_URL)
            cards = page.locator(CARD_SELECTOR)
            count = await wait_for_items(cards, timeout=15_000)

            for i in range(count):
                card = cards.nth(i)
                cards_data.append(
                    {
                        "title": await card.locator(".game-title").text_content(),
                        "raw_date": await card.locator(".game-date").text_content(),
                        "venue": await card.locator(".place-title").text_content(),
                        "address": await card.locator(".place-address").text_content(),
                        "price": await card.locator(".price-sum").text_content(),
                        "href": await card.locator(".game-title-link").get_attribute("href"),
                    }
                )

        events: list[QuizEvent] = []
        for data in cards_data:
            event = self._parse_card(data)
            if event:
                events.append(event)

        return events

    def _parse_card(self, data: dict) -> QuizEvent | None:
        raw_date = (data["raw_date"] or "").strip()

        if raw_date.lower().startswith("сегодня"):
            event_date = today_astana()
        else:
            try:
                event_date = extract_date(raw_date)
            except DateParseError:
                logger.warning("QuizPlease: не удалось разобрать дату %r", raw_date)
                return None

        event_time = extract_time(raw_date)
        title = (data["title"] or "").strip()
        if not title:
            return None

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
            raw_text=f"{title} | {raw_date}",
        )
