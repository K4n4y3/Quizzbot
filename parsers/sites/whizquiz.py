"""
Парсер whizquiz.tilda.ws (Whiz Quiz).

Сайт-визитка на Tilda с выбором города через попап регистрации (похоже на
teztap.py), но здесь расписание конкретного города не предрендерено в
скрытом DOM заранее — форма заполняется JS только ПОСЛЕ клика по городу
(проверено: без клика чекбоксов с играми нет). Поэтому Playwright тут
обязательно кликает по кнопке "Астана" перед чтением формы.

Внутри открывшегося попапа даты игр — радиокнопки с говорящим именем
`name="Астана"` (сайт называет radio-группу по имени города):
  <input type="radio" name="Астана"
         value="27 сентября (воскресенье) Отчаянные Домохозяйки (лучшее за 6 лет)">

Времени игр на сайте нигде не указано (все — "воскресенье", без часов).
Площадка тоже нигде не указана. Цена зависит от "пояса" команды (система
скидок за лояльность) — берём цену для новичков/без пояса, первый вариант
в группе `name="Пояс:"`.
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import async_playwright

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://whizquiz.tilda.ws/"
CITY_BUTTON_SELECTOR = '[href="#popup:myform1"]'
GAME_RADIO_SELECTOR = 'input[type="radio"][name="Астана"]'
PRICE_RADIO_SELECTOR = 'input[type="radio"][name="Пояс:"]'

_PRICE_RE = re.compile(r"\(([^)]+)\)\s*$")
# "27 сентября (воскресенье) Отчаянные Домохозяйки (лучшее за 6 лет)"
# -> date_part = день+месяц+день недели, title = хвост. Дату достаём ТОЛЬКО
# из date_part — иначе extract_date подхватывает случайное "20xx" из
# названия квиза (напр. "Тусич под хиты 2003-2004") как год.
_DATE_PREFIX_RE = re.compile(r"^\s*(?P<date_part>\d{1,2}\s+\S+\s*\([^)]*\))\s*(?P<title>.+)$")


class WhizQuizParser(BaseParser):
    source_name = "Whiz Quiz"

    async def parse(self) -> list[QuizEvent]:
        raw_values: list[str] = []
        price: str | None = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(BASE_URL, wait_until="networkidle")
                await page.click(CITY_BUTTON_SELECTOR)

                games = page.locator(GAME_RADIO_SELECTOR)
                await games.first.wait_for(state="attached", timeout=15_000)

                count = await games.count()
                for i in range(count):
                    value = await games.nth(i).get_attribute("value")
                    if value:
                        raw_values.append(value)

                price_radios = page.locator(PRICE_RADIO_SELECTOR)
                if await price_radios.count():
                    raw_price = await price_radios.first.get_attribute("value")
                    match = _PRICE_RE.search(raw_price or "")
                    price = match.group(1).strip() if match else raw_price
            finally:
                await browser.close()

        events: list[QuizEvent] = []
        for raw_text in raw_values:
            event = self._parse_item(raw_text, price)
            if event:
                events.append(event)

        return events

    def _parse_item(self, raw_text: str, price: str | None) -> QuizEvent | None:
        match = _DATE_PREFIX_RE.match(raw_text)
        date_source = match.group("date_part") if match else raw_text
        title = match.group("title").strip() if match else raw_text

        try:
            event_date = extract_date(date_source)
        except DateParseError:
            logger.warning("Whiz Quiz: не удалось найти дату в %r", raw_text)
            return None

        event_time = extract_time(date_source)

        return QuizEvent(
            source=self.source_name,
            title=title or raw_text,
            event_date=event_date,
            event_time=event_time,
            venue="уточняется",
            price=price,
            city="Астана",
            url=BASE_URL,
            raw_text=raw_text,
        )
