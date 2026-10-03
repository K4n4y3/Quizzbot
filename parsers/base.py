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

    async def fetch(self) -> list[QuizEvent]:
        """
        Публичная точка входа. Оборачивает `parse()` так, чтобы падение
        ОДНОГО источника не роняло весь цикл парсинга остальных источников.
        """
        try:
            events = await self.parse()
        except Exception:
            logger.exception("Парсер %s упал с ошибкой", self.source_name)
            return []

        logger.info("Парсер %s вернул %d событий", self.source_name, len(events))
        return events

    @abstractmethod
    async def parse(self) -> list[QuizEvent]:
        """Собственно логика парсинга — реализуется в каждом наследнике."""
        raise NotImplementedError
