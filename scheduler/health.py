"""
Оповещения о поломке источников.

Источник считается сломанным, если парсер упал с ошибкой или (если для него
это не норма) вернул 0 игр — так выглядит сменившаяся вёрстка сайта.
Оповещаем, когда сбой повторился FAIL_STREAK_TO_ALERT обновлений подряд
(разовый таймаут сайта — не повод писать), и один раз — когда источник
снова заработал. В промежутке не дублируем, чтобы не слать сообщение
каждые 3 часа.
"""

from __future__ import annotations

from parsers.base import BaseParser
from storage.db import SourceHealth
from storage.repository import EventRepository

FAIL_STREAK_TO_ALERT = 2


def _failure(parser: BaseParser, events: list) -> str | None:
    if not parser.last_ok:
        return parser.last_error or "ошибка без описания"
    if not events and not parser.may_be_empty:
        return "0 игр без ошибки — возможно, сменилась вёрстка сайта"
    return None


async def check_health(
    repo: EventRepository, parsers: list[BaseParser], results: list[list]
) -> list[str]:
    """Обновляет состояние источников и возвращает тексты оповещений."""
    known = await repo.get_health()
    updated: list[SourceHealth] = []
    alerts: list[str] = []

    for parser, events in zip(parsers, results):
        row = known.get(parser.source_name) or SourceHealth(
            source=parser.source_name, fail_streak=0, alerted=False
        )
        problem = _failure(parser, events)
        if problem:
            row.fail_streak += 1
            if row.fail_streak >= FAIL_STREAK_TO_ALERT and not row.alerted:
                alerts.append(
                    f"⚠️ {parser.source_name}: не обновляется {row.fail_streak} раза подряд.\n{problem}"
                )
                row.alerted = True
        else:
            if row.alerted:
                alerts.append(f"✅ {parser.source_name} снова работает ({len(events)} игр).")
            row.fail_streak, row.alerted = 0, False
        updated.append(row)

    await repo.save_health(updated)
    return alerts
