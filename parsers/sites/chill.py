"""
Парсер chillquiz.kz/quizzes (Chill Quiz).

Важно: сайт общий на несколько городов Казахстана (Алматы, Астана,
Караганда, Усть-Каменогорск и т.д.), город выбирается через cookie
`city_slug` — без неё отдаётся микс из ВСЕХ городов (проверено вживую:
без cookie в списке вперемешку венды Алматы вроде "Harat's na Pastera" и
Астаны вроде "Harat's Желтоксан"). Выставляем `city_slug=astana` через
Playwright cookie перед заходом на страницу.

Next.js-приложение, расписание рендерится клиентским JS (проверено —
curl с той же cookie не находит карточек, значит список подгружается уже
в браузере), поэтому Playwright, а не httpx.

Карточка — `a > div.rounded-lg.border.bg-card` (shadcn/ui):
  h3                                    — название
  .space-y-2 > div:nth-child(1) span    — дата ("23 сентября 2026 г.")
  .space-y-2 > div:nth-child(2) span    — время ("20:00")
  .space-y-2 > div:nth-child(3) span    — площадка
  .text-2xl.font-bold.text-primary      — цена ("3500 ₸")
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from parsers.browser import goto, open_page, wait_for_items

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://chillquiz.kz"
SCHEDULE_URL = BASE_URL + "/quizzes"
CARD_SELECTOR = "a > div.rounded-lg.border.bg-card"
INFO_ROW_SELECTOR = ".space-y-2.text-sm.text-muted-foreground > div span"


class ChillQuizParser(BaseParser):
    source_name = "Chill Quiz"
    uses_browser = True

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        city_cookie = {"name": "city_slug", "value": "astana", "url": BASE_URL}
        async with open_page(cookies=[city_cookie]) as page:
            await goto(page, SCHEDULE_URL)
            cards = page.locator(CARD_SELECTOR)
            count = await wait_for_items(cards, timeout=15_000)

            for i in range(count):
                card = cards.nth(i)
                info_spans = card.locator(INFO_ROW_SELECTOR)
                info_count = await info_spans.count()
                href = card.locator("xpath=..").first  # родительский <a>
                cards_data.append(
                    {
                        "title": await card.locator("h3").text_content(),
                        "date": await info_spans.nth(0).text_content() if info_count > 0 else "",
                        "time": await info_spans.nth(1).text_content() if info_count > 1 else "",
                        "venue": await info_spans.nth(2).text_content() if info_count > 2 else "",
                        "price": await card.locator(
                            ".text-2xl.font-bold.text-primary"
                        ).text_content(),
                        "href": await href.get_attribute("href"),
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
            logger.warning("Chill Quiz: не удалось разобрать дату %r", raw_date)
            return None

        raw_time = (data["time"] or "").strip()
        event_time = extract_time(raw_time) if raw_time else None

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=event_time,
            venue=(data["venue"] or "уточняется").strip(),
            price=(data["price"] or "").strip() or None,
            city="Астана",
            url=urljoin(BASE_URL, data["href"]) if data["href"] else SCHEDULE_URL,
            raw_text=f"{title} | {raw_date} {raw_time}",
        )
