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

    #: Пустое расписание у источника — норма (например, у Quizland бывает
    #: один анонс или ни одного). Для остальных 0 игр без ошибки — повод
    #: для оповещения: так выглядит сменившаяся вёрстка (см. scheduler/health.py).
    may_be_empty: bool = False

    #: Краткое описание ошибки последнего fetch() — для оповещений.
    last_error: str | None = None

    async def fetch(self) -> list[QuizEvent]:
        """
        Публичная точка входа. Оборачивает `parse()` так, чтобы падение
        ОДНОГО источника не роняло весь цикл парсинга остальных источников.
        """
        self.last_ok, self.last_error = False, None
        try:
            events = await self.parse()
        except Exception as e:
            logger.exception("Парсер %s упал с ошибкой", self.source_name)
            self.last_error = f"{type(e).__name__}: {e}"[:300]
            return []
        self.last_ok = True

        logger.info("Парсер %s вернул %d событий", self.source_name, len(events))
        return events

    @abstractmethod
    async def parse(self) -> list[QuizEvent]:
        """Собственно логика парсинга — реализуется в каждом наследнике."""
        raise NotImplementedError
