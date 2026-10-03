"""
Парсер astana.albertparty.ru (Einstein Party).

Статичный сайт (обычный SSR HTML, без клиентского JS-рендеринга —
проверено через curl). Карточка игры уже несёт данные в data-атрибутах
на обёртке `.games-tickets-slide`, отдельно парсить текст не нужно:

  <div class="games-tickets-slide"
       data-name="#521 ИГРА. УГАДАЙ ОБО ВСЁМ 100 ВОПРОСОВ"
       data-place="Garage music bar"
       data-address="ул. КРАВЦОВА 6"
       data-price="3000  ₸" ...>

Дата и время лежат в тексте внутри карточки: `.games__tickets-ticket-date`
(вид "пятница25 сентября" — день недели слитно с числом, без года) и
`.games__tickets-ticket-time` ("20:00"). Год не указан — вычисляется
эвристикой в `utils.date_parser.extract_date` (текущий год, либо следующий,
если дата "в прошлом").
"""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.albertparty.ru/"
CARD_SELECTOR = ".games-tickets-slide"


class EinsteinPartyParser(BaseParser):
    source_name = "Einstein Party"

    async def parse(self) -> list[QuizEvent]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                BASE_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; QuizScheduleBot/1.0)"},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        events: list[QuizEvent] = []

        for card in soup.select(CARD_SELECTOR):
            event = self._parse_card(card)
            if event:
                events.append(event)

        return events

    def _parse_card(self, card) -> QuizEvent | None:
        title = card.get("data-name", "").strip()
        date_el = card.select_one(".games__tickets-ticket-date")
        time_el = card.select_one(".games__tickets-ticket-time")
        if not title or not date_el:
            return None

        date_text = date_el.get_text(strip=True)
        try:
            event_date = extract_date(date_text)
        except DateParseError:
            logger.warning("Einstein Party: не удалось разобрать дату %r", date_text)
            return None

        event_time = extract_time(time_el.get_text(strip=True)) if time_el else None

        price_raw = card.get("data-price", "").strip()
        price = " ".join(price_raw.split()) or None

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=event_time,
            venue=card.get("data-place", "уточняется").strip() or "уточняется",
            address=card.get("data-address", "").strip() or None,
            price=price,
            city="Астана",
            url=BASE_URL,
            raw_text=f"{title} | {date_text} {time_el.get_text(strip=True) if time_el else ''}",
        )
