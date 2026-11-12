"""
Парсер astana.albertparty.ru (Einstein Party).

Статичный HTML, браузер не нужен. В ноябре 2026 сайт сменил дизайн; полное
расписание — на /schedule, каждая игра в блоке `.game-item`:
  .game-item__title           — "#547 ИГРА. 18+ ВСЁ ПРО КЕКС"
  .game-item__date            — "12 ноября", "четверг", "20:00" (год не указан)
  .game-item__address .place  — площадка, `.address` — адрес
  .game-item__price           — "3500 ₸"
  ссылка /game/<id>/register  — id игры для ссылки на страницу
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://astana.albertparty.ru"
SCHEDULE_URL = BASE_URL + "/schedule"
CARD_SELECTOR = ".game-item"
_GAME_ID_RE = re.compile(r"/game/(\d+)")


class EinsteinPartyParser(BaseParser):
    source_name = "Einstein Party"

    async def parse(self) -> list[QuizEvent]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                SCHEDULE_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; QuizScheduleBot/1.0)"},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(CARD_SELECTOR)
        if not cards:
            # Пустой результат без ошибки выглядел бы как "игр нет" — а это
            # скорее снова сменилась вёрстка. Пусть будет видно в логе.
            raise ValueError("Einstein Party: на /schedule нет карточек .game-item — сменилась вёрстка?")
        return [event for event in map(self._parse_card, cards) if event]

    @staticmethod
    def _text(card, selector: str) -> str:
        el = card.select_one(selector)
        return " ".join(el.get_text(" ", strip=True).split()) if el else ""

    def _parse_card(self, card) -> QuizEvent | None:
        title = self._text(card, ".game-item__title")
        date_text = self._text(card, ".game-item__date")
        if not title or not date_text:
            return None
        try:
            event_date = extract_date(date_text)
        except DateParseError:
            logger.warning("Einstein Party: не удалось разобрать дату %r", date_text)
            return None

        link = card.find("a", href=_GAME_ID_RE)
        game_id = _GAME_ID_RE.search(link["href"]).group(1) if link else None

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=extract_time(date_text),
            venue=self._text(card, ".game-item__address .place") or "уточняется",
            address=self._text(card, ".game-item__address .address") or None,
            price=self._text(card, ".game-item__price") or None,
            city="Астана",
            url=f"{BASE_URL}/game/{game_id}" if game_id else SCHEDULE_URL,
            raw_text=f"{title} | {date_text}",
        )
