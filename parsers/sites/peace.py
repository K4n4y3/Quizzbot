"""
Парсер peacequizastana.kz (Peace Quiz).

Страница /raspisanie_kvizov_astana — Tilda-сайт, но расписание (блок
"Catalog") подгружается JS с задержкой (curl видит только 1 упоминание
класса карточки — это CSS-правило, не сама карточка; реальный контент
появляется через пару секунд после загрузки, проверено вживую). Playwright,
с ожиданием `state="attached"`, этого достаточно.

Карточка `.js-product.t-catalog__card`:
  .js-catalog-prod-name    — название (без даты, в отличие от Smuzi)
  .js-catalog-prod-descr   — "<strong>23 сентября (среда) | 20:00</strong><br>
                               Стоимость участия: 3500тг/ чел"
                              (цена и дата в одном текстовом блоке через <br>)
  .t-product__option-item / option — площадка (в этом городе она одна и та
                              же на все игры: "Draft bar&grill" ул. ...)

Блок цены (`.t-catalog__card__price`) в разметке пуст (display:none,
значение не проставлено) — реальная цена берётся из текста `-descr`,
строка "Стоимость участия: ...".
"""

from __future__ import annotations

import logging
import re

from parsers.browser import goto, open_page, wait_for_items

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://peacequizastana.kz"
SCHEDULE_URL = BASE_URL + "/raspisanie_kvizov_astana"
CARD_SELECTOR = ".js-product.t-catalog__card"

_PRICE_RE = re.compile(r"Стоимость участия:\s*(?P<price>.+)$", re.IGNORECASE)
_VENUE_RE = re.compile(r"^(?P<venue>.+?)\s*(?P<address>ул\.?\s*.+)$")


class PeaceQuizParser(BaseParser):
    source_name = "Peace Quiz"
    uses_browser = True

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        async with open_page() as page:
            await goto(page, SCHEDULE_URL)
            cards = page.locator(CARD_SELECTOR)
            count = await wait_for_items(cards, timeout=20_000)

            for i in range(count):
                card = cards.nth(i)
                venue_locator = card.locator(
                    ".t-product__option-variants select, .t-product__option-item"
                ).first
                venue_text = await venue_locator.text_content() if await venue_locator.count() else ""
                cards_data.append(
                    {
                        "title": await card.locator(".js-catalog-prod-name").text_content(),
                        "descr": await card.locator(".js-catalog-prod-descr").text_content(),
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
        title = (data["title"] or "").strip()
        descr = (data["descr"] or "").strip()
        if not title or not descr:
            return None

        try:
            event_date = extract_date(descr)
        except DateParseError:
            logger.warning("Peace Quiz: не удалось разобрать дату %r", descr)
            return None

        event_time = extract_time(descr)

        price_match = _PRICE_RE.search(descr)
        price = price_match.group("price").strip() if price_match else None

        venue, address = "уточняется", None
        venue_match = _VENUE_RE.match(data["venue_text"])
        if venue_match:
            venue = venue_match.group("venue").strip(' "') or "уточняется"
            address = venue_match.group("address").strip()
        elif data["venue_text"]:
            venue = data["venue_text"].strip(' "')

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=event_time,
            venue=venue,
            address=address,
            price=price,
            city="Астана",
            url=SCHEDULE_URL,
            raw_text=f"{title} | {descr}",
        )
