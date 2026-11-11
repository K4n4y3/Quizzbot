import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.handlers.admin import _OPT_OUT, poll_options  # noqa: E402
from utils.merge import DisplayEvent  # noqa: E402


def run() -> None:
    for n in range(1, 40):
        events = [DisplayEvent(f"Квиз {i}", "Тема", date(2026, 11, 11), time(20), "Бар") for i in range(n)]
        polls = poll_options(events)
        flat = [option for poll in polls for option in poll]
        assert flat.count(_OPT_OUT) == 1, f"{n}: 'без меня' должен быть ровно один раз"
        assert polls[-1][-1] == _OPT_OUT, f"{n}: 'без меня' — последний вариант последнего опроса"
        assert len(flat) == n + 1, f"{n}: потерялись варианты"
        sizes = [len(p) for p in polls]
        assert all(2 <= s <= 10 for s in sizes), f"{n}: в опросе от 2 до 10 вариантов, а не {sizes}"
        assert max(sizes) - min(sizes) <= 1, f"{n}: опросы должны быть поровну, а не {sizes}"
    print("Тесты опросов прошли успешно.")


if __name__ == "__main__":
    run()
