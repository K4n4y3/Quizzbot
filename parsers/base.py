from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from models.event import QuizEvent

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """
    Общий контракт для всех парсеров источников.

    Каждый парсер отвечает за ОДИН источник (один сайт или один
    Telegram-канал) и ничего не знает о хранилище — он только
    возвращает список QuizEvent. Сохранение и дедупликация — забота
    вызывающего кода (scheduler/jobs.py), не парсера.
    """

    #: Человекочитаемое имя источника — попадает в QuizEvent.source
    #: и в логи. Обязательно к переопределению в наследнике.
    source_name: str = "unknown"

    #: True, если последний fetch() отработал без исключения. Нужно, чтобы
    #: отличить "сайт реально пуст" от "парсер упал" при чистке устаревших
    #: записей источника (см. scheduler/jobs.py).
    last_ok: bool = False

    #: Парсер открывает страницу в общем Chromium (parsers/browser.py).
    #: Такие парсеры ограничены по параллельности, httpx-парсеры — нет.
    uses_browser: bool = False

    async def fetch(self) -> list[QuizEvent]:
        """
        Публичная точка входа. Оборачивает `parse()` так, чтобы падение
        ОДНОГО источника не роняло весь цикл парсинга остальных источников.
        """
        self.last_ok = False
        try:
            events = await self.parse()
        except Exception:
            logger.exception("Парсер %s упал с ошибкой", self.source_name)
            return []
        self.last_ok = True

        logger.info("Парсер %s вернул %d событий", self.source_name, len(events))
        return events

    @abstractmethod
    async def parse(self) -> list[QuizEvent]:
        """Собственно логика парсинга — реализуется в каждом наследнике."""
        raise NotImplementedError
