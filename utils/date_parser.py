"""
Парсинг дат и времени из текста расписаний квизов.

Источники пишут дату по-разному:
    "22 қыркүйек, 19:30"
    "24 сентября 20:00"
    "23 сентября, среда в 20:00"
    "24 сен (четверг), 20:00"
    "**22 сентября, вторник** — ... в 20:00"
    "27 сентября (воскресенье), 17:30"
    "22 сентября (вторник), 20:00 — ... — 3 000 KZT/чел"

Общее у всех форматов: <день> <месяц словом> ... <часы>:<минуты>.
День недели и разделители (запятая/тире/скобки) варьируются и игнорируются —
мы вычисляем день недели сами по итоговой дате, а не доверяем тексту источника
(там встречаются опечатки в днях недели).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from utils.clock import today_astana

# Родительный падеж — так месяцы стоят после числа: "22 сентября"
_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    # сокращения, встречающиеся в источниках: "24 сен (четверг)"
    "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "июн": 6, "июл": 7, "авг": 8,
    # detequiz.com пишет 4-буквенное сокращение с точкой: "27 сент., 17:00"
    "сент": 9,
}

_KK_MONTHS = {
    "қаңтар": 1, "ақпан": 2, "наурыз": 3, "сәуір": 4,
    "мамыр": 5, "маусым": 6, "шілде": 7, "тамыз": 8,
    "қыркүйек": 9, "қазан": 10, "қараша": 11, "желтоқсан": 12,
}

_ALL_MONTHS = {**_RU_MONTHS, **_KK_MONTHS}

# Самый длинный вариант месяца проверяется первым (иначе "сен" сматчится
# внутри "сентября" раньше, чем полное слово — неважно для значения,
# но важно для корректного вычисления длины совпадения).
_MONTH_PATTERN = "|".join(sorted(_ALL_MONTHS.keys(), key=len, reverse=True))

_DATE_RE = re.compile(
    rf"(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_PATTERN})\b",
    re.IGNORECASE | re.UNICODE,
)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Не \b: если время впритык к кириллице без пробела ("20:00Стоимость"),
# \b не сработает — Python считает кириллицу словесным символом, границы
# между "0" и "С" нет. (?<!\d)/(?!\d) не матчится только на другие цифры.
_TIME_RE = re.compile(r"(?<!\d)(?P<hour>\d{1,2}):(?P<minute>\d{2})(?!\d)")


class DateParseError(ValueError):
    """Не удалось найти дату (день+месяц) в строке."""


def strip_markdown(text: str) -> str:
    """Убирает **bold** и лишние пробелы — источники иногда выделяют дату жирным."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_date(text: str, *, today: date | None = None) -> date:
    """
    Находит первую пару "день + месяц" в тексте и возвращает date.

    Год в исходном тексте почти никогда не указан, поэтому он вычисляется:
    берём текущий год; если получившаяся дата "в прошлом" более чем на
    60 дней относительно `today`, считаем, что речь о следующем годе
    (актуально для расписаний, парсящихся на стыке декабря/января).
    Если год указан явно (напр. "22 сентября 2026") — используется он.

    Ограничение: логика только "толкает вперёд" (декабрь -> следующий год),
    но никогда не откатывает назад. Для парсинга расписаний на ближайшие
    недели (наш случай) этого достаточно; для парсинга архивных/прошедших
    страниц эвристику нужно будет расширить.
    """
    text = strip_markdown(text)
    match = _DATE_RE.search(text)
    if not match:
        raise DateParseError(f"Не найдена дата (день+месяц) в строке: {text!r}")

    day = int(match.group("day"))
    month = _ALL_MONTHS[match.group("month").lower()]

    today = today or today_astana()

    year_match = _YEAR_RE.search(text)
    if year_match:
        year = int(year_match.group(1))
    else:
        year = today.year
        try:
            candidate = date(year, month, day)
        except ValueError as e:
            raise DateParseError(f"Некорректная дата {day}.{month}.{year}: {text!r}") from e
        if candidate < today - timedelta(days=60):
            year += 1

    try:
        return date(year, month, day)
    except ValueError as e:
        raise DateParseError(f"Некорректная дата {day}.{month}.{year}: {text!r}") from e


def extract_time(text: str) -> time | None:
    """Находит первое HH:MM в строке (время начала игры). None, если не найдено."""
    match = _TIME_RE.search(text)
    if not match:
        return None
    hour, minute = int(match.group("hour")), int(match.group("minute"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def parse_event_datetime(text: str, *, today: date | None = None) -> tuple[date, time | None]:
    """Удобный шорткат: вернуть (дата, время|None) одним вызовом."""
    return extract_date(text, today=today), extract_time(text)
