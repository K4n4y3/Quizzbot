"""
Парсер ast.mzgb.net (MozgoQuiz).

Vue-приложение, расписание рендерится клиентским JS (curl не находит ни
одной карточки в исходном HTML — проверено), поэтому Playwright. На
главной сейчас только 2 ближайшие игры — отдельной страницы "все игры"
на сайте нет (проверено вживую), это весь список.

У карточек нет стабильных семантических классов (Tailwind, много
одноразовых `text-[20px]`-подобных), кроме `.venue` на площадке/адресе —
поэтому ориентируемся на структуру, а не на конкретные имена классов:

  div.p-6.bg-white                  — панель карточки
    p.font-semibold                  — название (первый такой элемент)
    div.flex.flex-col.gap-4 > div    — три строки: [дата, площадка+адрес, цена]
      строка 0: <p>дата и время</p>
      строка 1: <div><p class="venue">площадка</p><p class="venue">адрес</p></div>
      строка 2: <p>цена</p>
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright

from models.event import QuizEvent
from parsers.base import BaseParser
from utils.date_parser import DateParseError, extract_date, extract_time

logger = logging.getLogger(__name__)

BASE_URL = "https://ast.mzgb.net/"
PANEL_SELECTOR = "div.p-6.bg-white"


class MozgoQuizParser(BaseParser):
    source_name = "MozgoQuiz"

    async def parse(self) -> list[QuizEvent]:
        cards_data: list[dict] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(BASE_URL, wait_until="networkidle")
                panels = page.locator(PANEL_SELECTOR)
                await panels.first.wait_for(state="attached", timeout=15_000)

                count = await panels.count()
                for i in range(count):
                    panel = panels.nth(i)
                    rows = panel.locator("div.flex.flex-col.gap-4 > div")
                    if await rows.count() < 3:
                        continue

                    title = await panel.locator("p.font-semibold").first.text_content()
                    raw_date = await rows.nth(0).locator("p").first.text_content()
                    venue_ps = rows.nth(1).locator("p.venue")
                    venue = await venue_ps.nth(0).text_content() if await venue_ps.count() > 0 else None
                    address = await venue_ps.nth(1).text_content() if await venue_ps.count() > 1 else None
                    price = await rows.nth(2).locator("p").first.text_content()

                    cards_data.append(
                        {
                            "title": (title or "").strip(),
                            "raw_date": (raw_date or "").strip(),
                            "venue": (venue or "").strip(),
                            "address": (address or "").strip(),
                            "price": (price or "").strip(),
                        }
                    )
            finally:
                await browser.close()

        events: list[QuizEvent] = []
        for data in cards_data:
            event = self._parse_card(data)
            if event:
                events.append(event)

        return events

    def _parse_card(self, data: dict) -> QuizEvent | None:
        if not data["title"] or not data["raw_date"]:
            return None

        try:
            event_date = extract_date(data["raw_date"])
        except DateParseError:
            logger.warning("MozgoQuiz: не удалось разобрать дату %r", data["raw_date"])
            return None

        event_time = extract_time(data["raw_date"])

        return QuizEvent(
            source=self.source_name,
            title=data["title"],
            event_date=event_date,
            event_time=event_time,
            venue=data["venue"] or "уточняется",
            address=data["address"] or None,
            price=data["price"] or None,
            city="Астана",
            url=BASE_URL,
            raw_text=f"{data['title']} | {data['raw_date']}",
        )
