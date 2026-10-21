"""
Парсер astana.smuzi-quiz.com (Смузи-квиз).

Полное расписание — на странице /games, а не на главной (там только 4
ближайшие игры). /games рендерится клиентским JS (curl отдаёт 403/пустой
контент без JS), поэтому здесь Playwright.

Сайт собран на Tilda, карточки — это блок "Store" (обычно для товаров),
переиспользованный под расписание: все данные (дата, день недели, время,
короткое имя площадки) склеены в одну строку заголовка карточки, напр.:

  "23 сентября (СР) 20:00 (GARAGE) Отчаянные домохозяйки №5"

т.е. "<день> <месяц> (<день недели>) <HH:MM> (<площадка кратко>) <название>".
Название квиза — это "хвост" после второй скобки (может само содержать
скобки, напр. "Караоке-квиз: ... (все песни на русском)" — поэтому title
берём нежадно до первых двух групп, всё остальное — в title).

Полный адрес площадки (там, где короткого имени недостаточно) — в
отдельном селекте/лейбле выбора площадки под карточкой:
  "Бар «GARAGE» (Александра Кравцова, 6)"
"""

from __future__ import annotations

import logging
import re

from parsers.browser import goto, open_page, wait_for_items

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.smuzi-quiz.com"
SCHEDULE_URL = BASE_URL + "/games"
CARD_SELECTOR = ".js-product.t-store__card"

# "23 сентября (СР) 20:00 (GARAGE) Отчаянные домохозяйки №5"
# -> header = дата/время/площадка, title = хвост.
# Дату/время достаём ТОЛЬКО из header, а не из всей строки — иначе
# extract_date подхватывает случайные 4-значные числа из названия квиза
# (напр. "СОВРЕМЕННОЕ 2015-2025" или "РУССКИЕ ХИТЫ 2000-х") как год.
_HEADER_RE = re.compile(
    r"^\s*(?P<header>\d{1,2}\s+\S+\s*\([^)]*\)\s*\d{1,2}:\d{2}\s*\([^)]*\))\s*(?P<title>.+)$"
)
# "Бар «GARAGE» (Александра Кравцова, 6)" -> venue + address
_VENUE_RE = re.compile(r"^(?P<venue>.+?)\s*\((?P<address>[^)]+)\)\s*$")


class SmuziQuizParser(BaseParser):
    source_name = "Смузи-квиз"
    uses_browser = True

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        async with open_page() as page:
            await goto(page, SCHEDULE_URL)
            cards = page.locator(CARD_SELECTOR)
            count = await wait_for_items(cards, timeout=15_000)

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
            logger.warning("Смузи-квиз: не удалось разобрать дату %r", raw_title)
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
