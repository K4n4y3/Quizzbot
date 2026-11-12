import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parsers.base import BaseParser  # noqa: E402
from scheduler.health import check_health  # noqa: E402
from storage.db import init_db, make_engine, make_session_factory  # noqa: E402
from storage.repository import EventRepository  # noqa: E402


class Fake(BaseParser):
    def __init__(self, name: str, *, may_be_empty: bool = False) -> None:
        self.source_name, self.may_be_empty = name, may_be_empty

    async def parse(self):  # не вызывается — состояние задаём вручную
        return []

    def set(self, ok: bool, error: str | None = None) -> "Fake":
        self.last_ok, self.last_error = ok, error
        return self


async def run() -> None:
    engine = make_engine(":memory:")
    await init_db(engine)
    repo = EventRepository(make_session_factory(engine))
    site, empty_ok = Fake("Сайт"), Fake("Анонсы", may_be_empty=True)

    async def step(site_ok: bool, site_events: list) -> list[str]:
        return await check_health(
            repo, [site.set(site_ok, None if site_ok else "403 Forbidden"), empty_ok.set(True)],
            [site_events, []],
        )

    assert await step(False, []) == [], "разовый сбой — без оповещения"
    alerts = await step(False, [])
    assert len(alerts) == 1 and "Сайт" in alerts[0] and "403" in alerts[0], alerts
    assert await step(False, []) == [], "повторно о той же поломке не пишем"
    alerts = await step(True, ["игра"])
    assert len(alerts) == 1 and alerts[0].startswith("✅"), alerts
    assert await step(True, ["игра"]) == []

    # 0 игр без ошибки у обычного источника — тоже поломка.
    await step(True, [])
    alerts = await step(True, [])
    assert len(alerts) == 1 and "вёрстка" in alerts[0], alerts

    print("Тесты оповещений прошли успешно.")


if __name__ == "__main__":
    asyncio.run(run())
