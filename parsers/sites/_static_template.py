"""
ШАБЛОН парсера для статичных сайтов (сервер отдаёт готовый HTML,
без JS-дорисовки). Быстрее и надёжнее Playwright, где применимо.

Как проверить, подходит ли сайт под этот шаблон:
  curl -s https://<сайт> | grep -i "<дата или название квиза>"
Если строка находится — сайт статичный, можно использовать httpx.
Если нет (как оказалось с teztap.company и astana.quizplease.com,
я проверил это напрямую) — нужен Playwright, см. parsers/sites/chill.py.

Это НЕ рабочий парсер конкретного сайта, а копируемая заготовка:
скопируйте файл, переименуйте класс и поправьте SCHEDULE_URL + селекторы
под конкретный источник.
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

SCHEDULE_URL = "https://example.com/schedule"  # TODO: заменить
ITEM_SELECTOR = ".schedule-item"                # TODO: заменить по DevTools


class StaticSiteParserTemplate(BaseParser):
    source_name = "ИмяИсточника"  # TODO: заменить

    async def parse(self) -> list[QuizEvent]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(SCHEDULE_URL)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        events: list[QuizEvent] = []

        for item in soup.select(ITEM_SELECTOR):
            raw_text = item.get_text(separator=" ", strip=True)

            try:
                event_date = extract_date(raw_text)
            except DateParseError:
                continue

            events.append(
                QuizEvent(
                    source=self.source_name,
                    title=raw_text,  # TODO: выделить title отдельным селектором
                    event_date=event_date,
                    event_time=extract_time(raw_text),
                    venue="уточняется",  # TODO: отдельный селектор под площадку
                    city="Астана",
                    url=SCHEDULE_URL,
                    raw_text=raw_text,
                )
            )

        return events
