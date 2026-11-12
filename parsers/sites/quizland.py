"""
Парсер quizland.kz.

В отличие от остальных источников, этот сайт анонсирует ТОЛЬКО одну
ближайшую игру за раз (проверено вживую, 2026-09-23: в форме регистрации
всего один вариант выбора игры) — ни полного расписания, ни истории игр
на сайте нет. Ни время, ни площадка, ни цена нигде на сайте не указаны —
только дата и тема.

Статичный HTML (Tilda, без JS-рендеринга — проверено curl). Текст анонса
ищем по фразе "Ближайшая игра - ..." в тексте страницы, а не по CSS-классу:
у Tilda классы вида `tn-elem__<обфусцированный id>` — слишком хрупкие,
могут поменяться при любой правке дизайна в редакторе.
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date

logger = logging.getLogger(__name__)

BASE_URL = "https://quizland.kz/"

_ANNOUNCEMENT_RE = re.compile(r"Ближайшая игра\s*-\s*(?P<rest>[^\n]+)")


class QuizlandParser(BaseParser):
    source_name = "Quizland"
    may_be_empty = True  # на сайте один анонс ближайшей игры, иногда ни одного

    async def parse(self) -> list[QuizEvent]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                BASE_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; QuizScheduleBot/1.0)"},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        node = soup.find(string=re.compile("Ближайшая игра"))
        if not node:
            logger.info("Quizland: анонс ближайшей игры на странице не найден")
            return []

        # Берём текст только ближайшего содержащего тега, а не всей страницы —
        # иначе `rest` захватит всё до конца документа (после get_text()
        # переносов строк не остаётся, и "[^\n]+" не на чем остановиться).
        match = _ANNOUNCEMENT_RE.search(node.strip())
        if not match:
            logger.info("Quizland: не удалось разобрать текст анонса %r", node.strip())
            return []

        rest = match.group("rest").strip()
        try:
            event_date = extract_date(rest)
        except DateParseError:
            logger.warning("Quizland: не удалось разобрать дату из анонса %r", rest)
            return []

        # "24 Сентября - Кино & Музыка" -> название после даты и разделителя.
        title_match = re.search(r"-\s*(?P<title>.+)$", rest)
        title = title_match.group("title").strip() if title_match else rest

        return [
            QuizEvent(
                source=self.source_name,
                title=title,
                event_date=event_date,
                venue="уточняется",
                city="Астана",
                url=BASE_URL,
                raw_text=match.group(0),
            )
        ]
