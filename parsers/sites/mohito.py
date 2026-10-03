"""
Парсер astana.mohito-quiz.com/games (Mohito Quiz).

Тот же движок/шаблон, что и у astana.smuzi-quiz.com (те же классы
`js-product t-store__card`, `js-store-prod-name` — общий конструктор
квиз-сайтов на Tilda). Отличие — формат заголовка карточки БЕЗ скобок
вокруг дня недели и площадки:

  "22 Сентября ВТ 20:00 Угадай фильм №15"

т.е. "<день> <месяц> <день недели> <HH:MM> <название>" (у Smuzi было
"<день> <месяц> (<день недели>) <HH:MM> (<площадка>) <название>").

/games отдаёт 403 обычному curl (бот-защита), нужен Playwright.

Полный адрес площадки — в отдельном селекте/лейбле под карточкой, как и
у Smuzi: "Бар Панаехали (ул. Кенесары, 4)".
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import async_playwright

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.mohito-quiz.com"
SCHEDULE_URL = BASE_URL + "/games"
CARD_SELECTOR = ".js-product.t-store__card"

# "22 Сентября ВТ 20:00 Угадай фильм №15" -> header = дата/день/время, title = хвост.
_HEADER_RE = re.compile(
    r"^\s*(?P<header>\d{1,2}\s+\S+\s+\S+\s+\d{1,2}:\d{2})\s*(?P<title>.+)$"
)
_VENUE_RE = re.compile(r"^(?P<venue>.+?)\s*\((?P<address>[^)]+)\)\s*$")


class MohitoQuizParser(BaseParser):
    source_name = "Mohito Quiz"

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(SCHEDULE_URL, wait_until="networkidle")
                cards = page.locator(CARD_SELECTOR)
                await cards.first.wait_for(state="attached", timeout=15_000)

                count = await cards.count()
                for i in range(count):
                    card = cards.nth(i)
                    raw_title = await card.locator(".js-store-prod-name").text_content()
                    price = await card.locator(".t-store__card__price").text_content()
                    venue_locator = card.locator(
                        ".t-product__option-variants select, .t-product__option-item"
                    ).first
                    venue_text = None
                    if await venue_locator.count():
                        venue_text = await venue_locator.text_content()
                    cards_data.append(
                        {
                            "raw_title": (raw_title or "").strip(),
                            "price": (price or "").strip(),
                            "venue_text": (venue_text or "").strip(),
                        }
                    )
            finally:
                await browser.close()

        events: list[QuizEvent] = []
        for data in cards_data:
            event = self._parse_card(data)
            if event:
                events.append(event)

        return events

    def _parse_card(self, data: dict) -> QuizEvent | None:
        raw_title = data["raw_title"]
        if not raw_title:
            return None

        header_match = _HEADER_RE.match(raw_title)
        date_source = header_match.group("header") if header_match else raw_title
        title = header_match.group("title").strip() if header_match else raw_title

        try:
            event_date = extract_date(date_source)
        except DateParseError:
            logger.warning("Mohito Quiz: не удалось разобрать дату %r", raw_title)
            return None

        event_time = extract_time(date_source)

        venue, address = "уточняется", None
        venue_match = _VENUE_RE.match(data["venue_text"] or "")
        if venue_match:
            venue = venue_match.group("venue").strip()
            address = venue_match.group("address").strip()
        elif data["venue_text"]:
            venue = data["venue_text"]

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=event_time,
            venue=venue,
            address=address,
            price=data["price"] or None,
            city="Астана",
            url=SCHEDULE_URL,
            raw_text=raw_title,
        )
