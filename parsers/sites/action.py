"""
Парсер tapter.one/action_kinoquiz_ast (Action Киноквиз).

Это не сайт квиза, а "линк-ин-био" страница (Tapter, аналог Linktree) —
список кнопок-ссылок. Полного расписания там нет, только кнопки вида
"Зарегистрироваться на квиз по КИНО 18+" с датой в подзаголовке; остальные
кнопки (фотоотчёты, расписание-картинкой в Instagram, корпоративы) —
не про конкретную игру, их пропускаем по префиксу заголовка.

Статичный HTML (проверено curl). Ни времени, ни площадки, ни цены на
странице нет вообще — только тема и дата ближайшей игры.

  <a class="btn-custom" href="...">
    <div class="btn-custom-title">Зарегистрироваться на квиз по КИНО 18+</div>
    <div class="btn-custom-subtitle">22 сентября (вт)</div>
  </a>
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

BASE_URL = "https://tapter.one/action_kinoquiz_ast"
_TITLE_PREFIX_RE = re.compile(r"^Зарегистрироваться на квиз\s*(по\s*)?", re.IGNORECASE)


class ActionKinoquizParser(BaseParser):
    source_name = "Action Киноквиз"

    async def parse(self) -> list[QuizEvent]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                BASE_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; QuizScheduleBot/1.0)"},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        events: list[QuizEvent] = []

        for btn in soup.select("a.btn-custom"):
            title_el = btn.select_one(".btn-custom-title")
            if not title_el or not title_el.get_text(strip=True).lower().startswith("зарегистрироваться"):
                continue
            event = self._parse_button(btn, title_el)
            if event:
                events.append(event)

        return events

    def _parse_button(self, btn, title_el) -> QuizEvent | None:
        raw_title = title_el.get_text(strip=True)
        subtitle_el = btn.select_one(".btn-custom-subtitle")
        raw_date = subtitle_el.get_text(strip=True) if subtitle_el else ""
        if not raw_date:
            return None

        try:
            event_date = extract_date(raw_date)
        except DateParseError:
            logger.warning("Action Киноквиз: не удалось разобрать дату %r", raw_date)
            return None

        title = _TITLE_PREFIX_RE.sub("", raw_title).strip().capitalize() or raw_title

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            venue="уточняется",
            city="Астана",
            url=BASE_URL,
            raw_text=f"{raw_title} | {raw_date}",
        )
