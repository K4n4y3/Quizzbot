from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from storage.db import EventRow

# Бренды одной франшизы с зеркальным расписанием (проверено 2026-10-01:
# даты, время, площадка и цены совпадают 1:1). Первый в списке даёт
# название для объединённой строки — у него нет "#524 ИГРА." в заголовке.
_MIRROR_SOURCES = ("WOW Quiz", "Einstein Party")


@dataclass
class DisplayEvent:
    source: str
    title: str
    event_date: date
    event_time: time | None
    venue: str


def _venue_key(venue: str) -> str:
    return " ".join(venue.lower().split())


def merge_mirrors(events: list[EventRow]) -> list[DisplayEvent]:
    """
    Склеивает в одну строку игры зеркальных брендов (Einstein Party / WOW
    Quiz), если совпали дата, время и площадка. Остальные источники не
    трогаем — склейка по одному только месту/времени ошибочно объединяла
    бы разные квизы в одном баре.
    """
    result: list[DisplayEvent] = []
    mirror_index: dict[tuple, int] = {}

    for e in events:
        display = DisplayEvent(e.source, e.title, e.event_date, e.event_time, e.venue)
        if e.source not in _MIRROR_SOURCES:
            result.append(display)
            continue

        key = (e.event_date, e.event_time, _venue_key(e.venue))
        idx = mirror_index.get(key)
        if idx is None:
            mirror_index[key] = len(result)
            result.append(display)
            continue

        existing = result[idx]
        if existing.source == e.source:
            result.append(display)  # два события одного бренда — не дубль
            continue
        existing.source = " / ".join(reversed(_MIRROR_SOURCES))
        if e.source == _MIRROR_SOURCES[0]:
            existing.title = e.title

    return result
