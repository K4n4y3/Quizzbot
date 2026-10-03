from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from parsers.base import BaseParser
from storage.repository import EventRepository

logger = logging.getLogger(__name__)


async def run_all_parsers(
    parsers: list[BaseParser],
    repo: EventRepository,
    max_concurrent: int = 4,
) -> None:
    """
    Запускает все парсеры ПАРАЛЛЕЛЬНО (это независимые сетевые запросы к
    разным сайтам), затем одним пакетом сохраняет всё, что удалось собрать.
    Падение одного парсера не мешает остальным — см. BaseParser.fetch().

    Параллелизм ограничен семафором: часть парсеров (JS-сайты) поднимают
    настоящий headless-браузер через Playwright, и если запускать их все
    разом без лимита, на слабой машине (типичный случай — ноутбук, а не
    сервер) несколько браузеров одновременно начинают конкурировать за
    CPU/RAM, и у части парсеров просто истекает таймаут навигации
    (это не гипотетический риск — воспроизведено на практике при первом
    прогоне 15 источников все разом: один из Playwright-парсеров словил
    Timeout на networkidle, хотя по отдельности отрабатывает нормально).
    """
    logger.info("Запускаю парсинг %d источников (до %d одновременно)...", len(parsers), max_concurrent)

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _fetch_bounded(parser: BaseParser) -> list:
        async with semaphore:
            return await parser.fetch()

    results = await asyncio.gather(*(_fetch_bounded(p) for p in parsers))

    all_events = [event for events in results for event in events]
    inserted = await repo.save_many(all_events)
    removed = await repo.delete_past()

    logger.info(
        "Парсинг завершён: всего найдено %d событий, новых сохранено %d, "
        "прошедших удалено %d",
        len(all_events),
        inserted,
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
