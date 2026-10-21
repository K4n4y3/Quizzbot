import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.date_parser import DateParseError, extract_date, extract_time  # noqa: E402

# Дата "сегодня", относительно которой считаем год для дат без года.
TODAY = date(2026, 9, 23)

# (сырая строка из файла, ожидаемая дата, ожидаемое время)
CASES = [
    ("22 қыркүйек, 19:30 — Ән мен Әнші: Қазақстан | 4000 тг, Пинта, Әуезов 8",
     date(2026, 9, 22), time(19, 30)),
    ("24 қыркүйек, 19:30 — Классика | 3000 тг, Draft, Ташенов 27",
     date(2026, 9, 24), time(19, 30)),
    ("22 сентября 19:30 - Последнее дело, Pinta, Акмешит 9/1",
     date(2026, 9, 22), time(19, 30)),
    ("24 сентября 20:00 - Проливая свет, Pinta, Ауэзова 8",
     date(2026, 9, 24), time(20, 0)),
    ("22 сентября, Вторник — [новички] #794 | Harat's Irish Pub Expo (пр. Мангилик Ел, 55 В2.4) в 20:00",
     date(2026, 9, 22), time(20, 0)),
    ("26 сентября, суббота, 17:00 — Угадай футбол (Garage music bar, ул. Кравцова 6)",
     date(2026, 9, 26), time(17, 0)),
    ("24 сен (четверг), 20:00 — К-поп (Noir.astana, ул. Алимхан Ермеков, 1/1)",
     date(2026, 9, 24), time(20, 0)),
    ("**22 сентября, вторник** — #520 Игра. Угадай мелодию: 18+ Русские песни. Стоимость: 3000 ₸.",
     date(2026, 9, 22), time(0, 0) if False else None),  # времени в этой строке нет
    ("**23 сентября, среда в 20:00** — Квиз №026: Сумерки VS Дневники Вампира | Harat's Irish Pub (ул. А. Токпанова, 10)",
     date(2026, 9, 23), time(20, 0)),
    ("**22 сентября, вторник** — Угадай фильм №15 | Бар Панаехали (ул. Кенесары, 4) в 20:00 — 3 000 KZT/чел",
     date(2026, 9, 22), time(20, 0)),
    ("27 сентября (воскресенье) 19:00 — Квиз по сериалу «Отчаянные домохозяйки» (Астана, «Garage», Кравцова 6)",
     date(2026, 9, 27), time(19, 0)),
    ("30 сентября, среда, 20:00 — Великолепный век №1 (GARAGE, Александра Кравцова, 6)",
     date(2026, 9, 30), time(20, 0)),
    # Время впритык к кириллице без пробела (реальный случай с peacequizastana.kz) —
    # \b тут не сработал бы, т.к. "0" и "С" оба считаются словесными символами.
    ("24 сентября (четверг) | 20:00Стоимость участия: 3500тг/чел",
     date(2026, 9, 24), time(20, 0)),
    # 4-буквенное сокращение месяца с точкой (реальный случай с detequiz.com).
    ("вс, 27 сент., 17:00",
     date(2026, 9, 27), time(17, 0)),
    ("вс, 1 нояб., 17:00",
     date(2026, 11, 1), time(17, 0)),
]


def run() -> None:
    failures = []
    for raw, expected_date, expected_time in CASES:
        try:
            got_date = extract_date(raw, today=TODAY)
            got_time = extract_time(raw)
        except DateParseError as e:
            failures.append(f"FAIL (exception {e}) on: {raw}")
            continue
        if got_date != expected_date:
            failures.append(f"FAIL date: got {got_date}, expected {expected_date} | {raw}")
        if expected_time is not None and got_time != expected_time:
            failures.append(f"FAIL time: got {got_time}, expected {expected_time} | {raw}")

    # Проверка year-rollover: дата в январе, парсим в декабре предыдущего года
    # (типичный случай — расписание на начало января парсится в конце декабря).
    rollover2 = extract_date("15 қаңтар, 19:00", today=date(2026, 12, 20))
    if rollover2 != date(2027, 1, 15):
        failures.append(f"FAIL year-rollover-forward: got {rollover2}")

    # Явный год должен побеждать эвристику.
    explicit = extract_date("15 сентября 2027, 19:00", today=TODAY)
    if explicit != date(2027, 9, 15):
        failures.append(f"FAIL explicit year: got {explicit}")

    if failures:
        print(f"\n{len(failures)} ТЕСТОВ ПРОВАЛЕНО:\n")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    else:
        print(f"Все {len(CASES) + 3} тестов прошли успешно.")


if __name__ == "__main__":
    run()
