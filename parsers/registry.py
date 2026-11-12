from __future__ import annotations

from parsers.base import BaseParser
from parsers.sites.chill import ChillQuizParser
from parsers.sites.detequiz import DetequizParser
from parsers.sites.einstein import EinsteinPartyParser
from parsers.sites.mohito import MohitoQuizParser
from parsers.sites.mozgo import MozgoQuizParser
from parsers.sites.peace import PeaceQuizParser
from parsers.sites.playquiz import PlayQuizParser
from parsers.sites.quizland import QuizlandParser
from parsers.sites.quizplease import QuizPleaseParser
from parsers.sites.shaker import ShakerQuizParser
from parsers.sites.smuzi import SmuziQuizParser
from parsers.sites.wow import WowQuizParser


def build_parsers() -> list[BaseParser]:
    """
    Список активных парсеров. Action, Teztap и Whiz Quiz сознательно не
    парсятся: их игры админ добавляет вручную (на сайтах нет времени/места
    или данных слишком мало).
    """
    return [
        QuizPleaseParser(),
        EinsteinPartyParser(),
        ShakerQuizParser(),
        SmuziQuizParser(),
        WowQuizParser(),
        PeaceQuizParser(),
        QuizlandParser(),
        MozgoQuizParser(),
        PlayQuizParser(),
        ChillQuizParser(),
        DetequizParser(),
        MohitoQuizParser(),
    ]
