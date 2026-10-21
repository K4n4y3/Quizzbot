from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

from parsers.base import BaseParser
from parsers.browser import shared_browser
from storage.repository import EventRepository

logger = logging.getLogger(__name__)


async def fetch_all(
    parsers: list[BaseParser], max_concurrent: int = 1, *, with_timings: bool = False
):
    """
    Собирает данные со всех источников. Браузерные парсеры работают во
    вкладках одного общего Chromium и ограничены семафором — на сервере с
    1 ГБ памяти больше одной страницы одновременно держать рискованно
    (при 4 параллельных браузерах сервер зависал). Лёгкие httpx-парсеры
    почти не тратят память и идут параллельно без ограничения.
    Падение одного парсера не мешает остальным — см. BaseParser.fetch().
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    timings: dict[str, float] = {}

    async def _run(parser: BaseParser) -> list:
        if parser.uses_browser:
            async with semaphore:
                return await _timed(parser)
        return await _timed(parser)

    async def _timed(parser: BaseParser) -> list:
        started = time.perf_counter()
        events = await parser.fetch()
        timings[parser.source_name] = time.perf_counter() - started
        return events

    async with shared_browser():
        results = await asyncio.gather(*(_run(p) for p in parsers))
    return (results, timings) if with_timings else results


async def run_all_parsers(
    parsers: list[BaseParser],
    repo: EventRepository,
    max_concurrent: int = 1,
) -> None:
    """Обходит все источники и одним пакетом сохраняет собранное в БД."""
    logger.info(
        "Запускаю парсинг %d источников (браузерных — до %d одновременно)...",
        len(parsers),
        max_concurrent,
    )

    started = time.perf_counter()
    results = await fetch_all(parsers, max_concurrent)

    all_events = [event for events in results for event in events]
    inserted = await repo.save_many(all_events)

    # Снимок источника заменяем целиком, но только если парсер отработал
    # без ошибок и что-то нашёл: пустой результат при успехе чаще означает
    # поломку вёрстки, чем то, что игр действительно нет.
    stale = 0
    for parser, events in zip(parsers, results):
        if parser.last_ok and events:
            stale += await repo.delete_stale_for_source(parser.source_name, events)

    removed = await repo.delete_past()

    logger.info(
        "Парсинг завершён за %.0f с: всего найдено %d событий, новых сохранено %d, "
        "устаревших у источников удалено %d, прошедших удалено %d",
        time.perf_counter() - started,
        len(all_events),
        inserted,
        stale,
        removed,
    )


class ParseCoordinator:
    """
    Парсинг по запросу вместо фонового расписания: сайты дёргаются не по
    таймеру, а когда кто-то реально пользуется ботом (/today, /week,
    /post_today) — если бот молчит и час, и два, ни один сайт лишний раз
    не трогаем (это и есть основная причина отказаться от таймера — не
    жечь CPU/сеть впустую, когда ботом никто не пользуется).

    Два нюанса, которые пришлось учесть:
    - "На каждый чих — новый парсинг всех 15 сайтов" тоже не годится: если
      несколько человек одновременно нажмут /today, не должно получиться
      несколько параллельных прогонов всех источников разом. Поэтому
      результат считается свежим ещё `stale_after` минут после последнего
      успешного прогона — в этом окне следующие вызовы просто читают то,
      что уже есть в БД, вообще не трогая сайты.
    - `asyncio.Lock` гарантирует, что даже если несколько запросов пришли
      ОДНОВРЕМЕННО в момент, когда данные уже устарели, парсинг всё равно
      запустится один раз, а не параллельно по разу на каждый запрос —
      остальные просто дождутся результата первого.
    """

    def __init__(
        self,
        parsers: list[BaseParser],
        repo: EventRepository,
        *,
        max_concurrent: int = 4,
        stale_after_minutes: int = 60,
    ) -> None:
        self._parsers = parsers
        self._repo = repo
        self._max_concurrent = max_concurrent
        self._stale_after = timedelta(minutes=stale_after_minutes)
        self._lock = asyncio.Lock()
        self._last_run: datetime | None = None

    def is_stale(self) -> bool:
        """Быстрая проверка без блокировки — удобно решить, показывать ли "подождите"."""
        return self._last_run is None or (datetime.now() - self._last_run) >= self._stale_after

    async def ensure_fresh(self) -> bool:
        """
        Запускает парсинг всех источников, если данные устарели (или их
        никогда не было). Возвращает True, если парсинг реально произошёл.
        """
        async with self._lock:
            if self._last_run is not None and datetime.now() - self._last_run < self._stale_after:
                return False
            await run_all_parsers(self._parsers, self._repo, self._max_concurrent)
            self._last_run = datetime.now()
            return True
