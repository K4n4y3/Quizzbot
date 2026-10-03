from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, time


@dataclass
class QuizEvent:
    """Единица расписания: один конкретный квиз в конкретном месте и времени."""

    source: str                  # напр. "Квиз, плиз!"
    title: str                   # напр. "Гарри Поттер: Фильмы (Лайт) №21"
    event_date: date
    venue: str                   # напр. "Бар Панаехали"
    event_time: time | None = None
    address: str | None = None
    price: str | None = None
    city: str = "Астана"
    url: str | None = None
    raw_text: str | None = None  # исходная строка — полезно для отладки парсера
    is_manual: bool = False       # добавлено админом вручную (Instagram-источники и т.п.)

    dedupe_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.dedupe_hash = self._make_hash()

    def _make_hash(self) -> str:
        """
        Хэш для дедупликации при повторных прогонах парсера.
        Намеренно НЕ включает price/url/raw_text — это то, что может
        измениться между парсингами одного и того же события,
        а не признак того, что это другое событие.
        """
        key = "|".join(
            [
                self.source.strip().lower(),
                self.title.strip().lower(),
                self.event_date.isoformat(),
                (self.event_time.isoformat() if self.event_time else ""),
                self.venue.strip().lower(),
                self.city.strip().lower(),
            ]
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
