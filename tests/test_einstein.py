import sys
from datetime import date, time
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parsers.sites.einstein import EinsteinPartyParser  # noqa: E402

# Фрагмент реальной разметки /schedule (ноябрь 2026).
CARD = """
<div class="game-item">
  <div class="game-item__title">#547 ИГРА. 18+ ВСЁ ПРО КЕКС</div>
  <div class="game-item__date"><span>12 ноября</span><span>четверг</span><span>20:00</span></div>
  <div class="game-item__address">
    <span class="place">Garage music bar</span><span class="address">ул. КРАВЦОВА 6</span>
    <a href="https://www.google.com/maps?q=1,2">Где это?</a>
  </div>
  <div class="game-item__price">3500   ₸</div>
  <a href="/game/29670/register?mode=with_team">Регистрация</a>
</div>
"""


def run() -> None:
    card = BeautifulSoup(CARD, "html.parser").select_one(".game-item")
    event = EinsteinPartyParser()._parse_card(card)
    assert event is not None
    assert event.title == "#547 ИГРА. 18+ ВСЁ ПРО КЕКС"
    assert (event.event_date.month, event.event_date.day) == (11, 12)
    assert event.event_time == time(20, 0)
    assert (event.venue, event.address, event.price) == ("Garage music bar", "ул. КРАВЦОВА 6", "3500 ₸")
    assert event.url == "https://astana.albertparty.ru/game/29670"
    assert isinstance(event.event_date, date)
    print("Тесты Einstein прошли успешно.")


if __name__ == "__main__":
    run()
