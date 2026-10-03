"""
Парсер playquiz.kz/schedule (Play Quiz).

Next.js (App Router) с нормальным SSR — страница отдаёт готовый HTML,
дублирующий JSON в <script> теги (для гидратации) роли не играет, реальные
данные есть и в самой разметке (проверено: curl находит текст карточек).
httpx + BeautifulSoup, Playwright не нужен.

Карточка `article.pq-game-row` (DevTools, 2026-09-23):
  h2.pq-game-row__name        — название
  p.pq-game-row__when         — "Четверг, 24 сен в 20:00" + вложенный
                                  span.pq-game-row__where с площадкой:
                                  "Noir.astana, ул. Алимхан Ермеков, 1/1"
                                  (площадку вынимаем через .extract(), чтобы
                                  дата/время не смешивались с её текстом)

Цены на карточках нет — она общая для всех игр и лежит в шапке страницы:
  .pq-page-head .pq-badge--accent  -> "3 000 ₸ с человека"
"""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://playquiz.kz"
SCHEDULE_URL = BASE_URL + "/schedule"
CARD_SELECTOR = "article.pq-game-row"


class PlayQuizParser(BaseParser):
    source_name = "Play Quiz"

    async def parse(self) -> list[QuizEvent]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                SCHEDULE_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; QuizScheduleBot/1.0)"},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        price_el = soup.select_one(".pq-page-head .pq-badge--accent")
        shared_price = " ".join(price_el.get_text(" ", strip=True).split()) if price_el else None

        events: list[QuizEvent] = []
        for card in soup.select(CARD_SELECTOR):
            event = self._parse_card(card, shared_price)
            if event:
                events.append(event)

        return events

    def _parse_card(self, card, shared_price: str | None) -> QuizEvent | None:
        title_el = card.select_one("h2.pq-game-row__name")
        when_el = card.select_one("p.pq-game-row__when")
        if not title_el or not when_el:
            return None

        where_el = when_el.select_one(".pq-game-row__where")
        venue, address = "уточняется", None
        if where_el:
            where_text = where_el.get_text(strip=True)
            if "," in where_text:
                venue, address = (p.strip() for p in where_text.split(",", 1))
            else:
                venue = where_text
            where_el.extract()  # убираем из дерева, чтобы не мешал парсингу даты

        date_text = when_el.get_text(" ", strip=True)
        try:
            event_date = extract_date(date_text)
        except DateParseError:
            logger.warning("Play Quiz: не удалось разобрать дату %r", date_text)
            return None

        event_time = extract_time(date_text)

        return QuizEvent(
            source=self.source_name,
            title=title_el.get_text(strip=True),
            event_date=event_date,
            event_time=event_time,
            venue=venue,
            address=address,
            price=shared_price,
            city="Астана",
            url=SCHEDULE_URL,
            raw_text=f"{title_el.get_text(strip=True)} | {date_text}",
        )
