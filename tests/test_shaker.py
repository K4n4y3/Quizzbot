import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parsers.sites.shaker import ShakerQuizParser  # noqa: E402


def game(status: str, visibility: str = "Visible") -> dict:
    return {
        "id": "1", "name": "Тест", "event_time": "2026-11-21T17:00:00.000Z",
        "price": 3000, "status": status, "visibility": visibility,
    }


def run() -> None:
    parser = ShakerQuizParser()
    assert parser._parse_game(game("Publish"), None) is not None
    for status in ("Cancel", "Finish", "Draft"):
        assert parser._parse_game(game(status), None) is None, status
    assert parser._parse_game(game("Publish", "Hidden"), None) is None
    print("Тесты Shaker прошли успешно.")


if __name__ == "__main__":
    run()
