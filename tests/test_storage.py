import asyncio
import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.event import QuizEvent  # noqa: E402
from storage.db import init_db, make_engine, make_session_factory  # noqa: E402
from storage.repository import EventRepository  # noqa: E402


async def run() -> None:
    engine = make_engine(":memory:")
    await init_db(engine)
    session_factory = make_session_factory(engine)
    repo = EventRepository(session_factory)

    ev1 = QuizEvent(
        source="Квиз, плиз!",
        title="[новички] #794",
        event_date=date(2026, 9, 22),
        event_time=time(20, 0),
        venue="Harat's Irish Pub Expo",
        city="Астана",
    )
    ev2 = QuizEvent(
        source="Шейкер",
        title="Кино #1",
        event_date=date(2026, 9, 24),
        event_time=time(20, 0),
        venue="Garage Music Bar",
        city="Астана",
    )
    # Дубликат ev1 — как будто парсер прогнали второй раз
    ev1_dup = QuizEvent(
        source="Квиз, плиз!",
        title="[новички] #794",
        event_date=date(2026, 9, 22),
        event_time=time(20, 0),
        venue="Harat's Irish Pub Expo",
        city="Астана",
    )

    assert ev1.dedupe_hash == ev1_dup.dedupe_hash, "Одинаковые события должны давать одинаковый хэш"
    assert ev1.dedupe_hash != ev2.dedupe_hash, "Разные события не должны давать одинаковый хэш"

    inserted_first = await repo.save_many([ev1, ev2])
    assert inserted_first == 2, f"Ожидали 2 новые записи, получили {inserted_first}"

    inserted_second = await repo.save_many([ev1_dup, ev2])
    assert inserted_second == 0, f"Дубликаты не должны вставляться повторно, получили {inserted_second}"

    upcoming = await repo.get_upcoming(from_date=date(2026, 9, 1))
    assert len(upcoming) == 2, f"Ожидали 2 события в выборке, получили {len(upcoming)}"

    upcoming_filtered = await repo.get_upcoming(from_date=date(2026, 9, 23))
    assert len(upcoming_filtered) == 1, "Фильтр по дате должен отсечь событие 22 сентября"
    assert upcoming_filtered[0].title == "Кино #1"

    removed = await repo.delete_past(before=date(2026, 9, 23))
    assert removed == 1, f"Ожидали удалить 1 прошедшее событие (22 сентября), удалили {removed}"

    remaining = await repo.get_upcoming(from_date=date(2026, 9, 1))
    assert len(remaining) == 1, "После очистки должно остаться только будущее событие"
    assert remaining[0].title == "Кино #1"

    # Игру переименовали на сайте: старая запись источника должна уйти,
    # запись другого источника и ручная запись — остаться.
    def make(source: str, title: str, manual: bool = False) -> QuizEvent:
        return QuizEvent(
            source=source, title=title, event_date=date(2026, 10, 6),
            event_time=time(20, 0), venue="Garage", is_manual=manual,
        )

    old, renamed = make("Einstein Party", "#527 старое"), make("Einstein Party", "#527 новое")
    other, manual = make("WOW Quiz", "чужая"), make("Einstein Party", "ручная", manual=True)
    await repo.save_many([old, other, manual])
    await repo.save_many([renamed])
    stale = await repo.delete_stale_for_source("Einstein Party", [renamed], today=date(2026, 10, 1))
    assert stale == 1, f"Должна уйти только старая версия, ушло {stale}"
    titles = {e.title for e in await repo.get_upcoming(from_date=date(2026, 10, 1))}
    assert titles == {"#527 новое", "чужая", "ручная"}, titles

    # Сайт убрал уже начавшуюся сегодняшнюю игру — в боте она должна остаться.
    started = make("Play Quiz", "MARVEL / DC")
    await repo.save_many([started])
    stale = await repo.delete_stale_for_source("Play Quiz", [make("Play Quiz", "другая")], today=date(2026, 10, 6))
    assert stale == 0, "Сегодняшняя игра не должна удаляться очисткой по сайту"

    print("Все тесты storage прошли успешно.")


if __name__ == "__main__":
    asyncio.run(run())
