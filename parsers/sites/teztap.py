"""
Парсер teztap.company (Астана).

Сайт собран на Tilda: расписание НЕ отдаётся в статичном HTML — даты
рендерятся в JS-рантайме Tilda и живут в DOM в виде скрытых (display:none)
чекбоксов внутри попапа регистрации на игру. Проверено напрямую:
`curl` не находит текст расписания в исходном HTML, поэтому нужен реальный
браузер (Playwright), но КЛИКАТЬ по попапу не обязательно — чекбоксы
присутствуют в DOM сразу после отрисовки JS, просто скрыты через CSS.
Playwright спокойно читает атрибут `value` у скрытых input.

Реальная структура (проверено в DevTools, 2026-09-23):
  - Все попапы городов — `div.t-popup`, по одному на город, различаются
    только текстом. Попап Астаны ищем по тексту "Астана қаласындағы"
    (Playwright text-selector), а не по индексу — порядок попапов в DOM
    не документирован и может измениться.
  - Внутри попапа блок выбора даты — `.t-input-group[data-field-name="Data"]`,
    а сами даты — чекбоксы `input[type=checkbox]` с value вида:
      "22 қыркүйек,19:30- Ән мен Әнші: Қазақстан, 4000 тг, Пинта, Әуезов 8"
    Формат value: "<день> <месяц қаз.>,<HH:MM>- <title>, <price>, <venue>, <address>"
"""

from __future__ import annotations

import logging
import re

from parsers.browser import goto, open_page, wait_for_items

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

PAGE_URL = "https://teztap.company/"
ASTANA_POPUP_TEXT = "Астана қаласындағы"
DATE_CHECKBOX_SELECTOR = '.t-input-group[data-field-name="Data"] input[type="checkbox"]'

# "22 қыркүйек,19:30- Ән мен Әнші: Қазақстан, 4000 тг, Пинта, Әуезов 8"
# -> заголовок / цена / площадка / адрес после даты и разделителя "-".
_AFTER_DATE_RE = re.compile(r"^\s*\d{1,2}\s+\S+,\d{1,2}:\d{2}\s*-\s*(?P<rest>.+)$")


class TeztapParser(BaseParser):
    source_name = "Teztap"
    uses_browser = True

    async def parse(self) -> list[QuizEvent]:
        raw_values: list[str] = []

        async with open_page() as page:
            await goto(page, PAGE_URL)

            popup = page.locator("div.t-popup", has_text=ASTANA_POPUP_TEXT)
            checkboxes = popup.locator(DATE_CHECKBOX_SELECTOR)
            # Элементы скрыты (display:none) до клика по попапу, поэтому
            # ждём именно attached, а не дефолтный visible.
            count = await wait_for_items(checkboxes, timeout=15_000)

            for i in range(count):
                value = await checkboxes.nth(i).get_attribute("value")
                if value:
                    raw_values.append(value)

        events: list[QuizEvent] = []
        for raw_text in raw_values:
            event = self._parse_item(raw_text)
            if event:
                events.append(event)

        return events

    def _parse_item(self, raw_text: str) -> QuizEvent | None:
        # Дату/время ищем ТОЛЬКО в префиксе до title, а не по всей строке —
        # иначе extract_date может подхватить случайное "20xx" из названия
        # квиза (напр. тема "2000-е") как год.
        match = _AFTER_DATE_RE.match(raw_text)
        date_source = raw_text[: match.start("rest")] if match else raw_text

        try:
            event_date = extract_date(date_source)
        except DateParseError:
            logger.warning("Teztap: не удалось найти дату в %r", raw_text)
            return None

        event_time = extract_time(date_source)

        title, price, venue, address = raw_text.strip(), None, "уточняется", None
        if match:
            parts = [p.strip() for p in match.group("rest").split(",")]
            if len(parts) >= 4:
                title = ",".join(parts[:-3]).strip()
                price, venue, address = parts[-3], parts[-2], parts[-1]

        return QuizEvent(
            source=self.source_name,
            title=title,
            event_date=event_date,
            event_time=event_time,
            venue=venue,
            address=address,
            price=price,
            city="Астана",
            url=PAGE_URL,
            raw_text=raw_text,
        )
