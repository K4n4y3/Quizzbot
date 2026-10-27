from __future__ import annotations

from datetime import date, timedelta
from html import escape
from itertools import groupby

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards import BTN_THEMES, BTN_TODAY, BTN_WEEK, main_menu_keyboard
from config import Config
from scheduler.jobs import ParseCoordinator
from storage.repository import EventRepository
from utils.clock import today_astana
from utils.merge import DisplayEvent, merge_mirrors
from utils.themes import ALL_THEMES, themes_of

router = Router()

_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

_THEME_DAYS = 14
_MAX_MESSAGE_LEN = 4000  # у Telegram лимит 4096, оставляем запас


def _format_day_header(d: date) -> str:
    return f"* {d.day} {_MONTHS_GENITIVE[d.month - 1]} ({_WEEKDAYS[d.weekday()]})"


def _format_event(e: DisplayEvent) -> str:
    time_str = e.event_time.strftime("%H:%M") if e.event_time else "время уточняется"
    title = escape(e.title)
    venue = escape(e.venue)
    source = escape(e.source)

    return f"{source} {time_str} — {title} | {venue}"


def _format_events_by_day(events: list[DisplayEvent]) -> str:
    """Группирует события по дате: заголовок дня, под ним — квизы этого дня
    с пустой строкой между каждым, чтобы список не сливался в сплошной текст."""
    blocks = []
    for day, day_events in groupby(events, key=lambda e: e.event_date):
        body = "\n\n".join(_format_event(e) for e in day_events)
        blocks.append(f"{_format_day_header(day)}\n\n{body}")
    return "\n\n".join(blocks)


async def _answer_chunked(message: Message, text: str) -> None:
    """Режет длинный ответ на части по строкам, не превышая лимит Telegram."""
    chunk = ""
    for line in text.split("\n"):
        candidate = f"{chunk}\n{line}" if chunk else line
        if len(candidate) > _MAX_MESSAGE_LEN and chunk:
            await message.answer(chunk)
            chunk = line
        else:
            chunk = candidate
    if chunk:
        await message.answer(chunk)


async def _ensure_fresh_with_notice(message: Message, coordinator: ParseCoordinator) -> None:
    """
    Парсинг запускается лениво, по факту обращения к боту (см.
    ParseCoordinator), а не по таймеру — так что первый после "затишья"
    вызов /today или /week может занять до ~20-30 секунд (15 сайтов,
    часть — через headless-браузер). Предупреждаем об этом, только если
    парсинг реально запустится (данные устарели), а не при каждом вызове.
    """
    if not coordinator.is_stale():
        return
    notice = await message.answer("⏳ Собираю свежее расписание с сайтов, секунду...")
    await coordinator.ensure_fresh()
    try:
        await notice.delete()
    except Exception:
        pass  # не критично, если не удалось убрать техническое сообщение


def register_schedule_handlers(
    router_: Router, repo: EventRepository, coordinator: ParseCoordinator, config: Config
) -> None:
    """
    Регистрирует хендлеры, которым нужен доступ к repo/coordinator/config.
    Вызывается один раз из bot/main.py после создания репозитория —
    так избегаем глобального состояния модуля.
    """

    def _is_admin(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in config.admin_user_ids

    @router_.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "Привет! Я собираю расписание квизов в Астане с разных площадок.\n\n"
            "Пользуйтесь кнопками ниже.",
            reply_markup=main_menu_keyboard(_is_admin(message)),
        )

    @router_.message(Command("today"))
    async def cmd_today(message: Message) -> None:
        await _ensure_fresh_with_notice(message, coordinator)

        today = today_astana()
        events = merge_mirrors(await repo.get_upcoming(from_date=today, to_date=today))
        if not events:
            await message.answer("На сегодня квизов не нашлось.")
            return
        text = "\n\n".join(_format_event(e) for e in events)
        await _answer_chunked(message, f"{_format_day_header(today)}\n\n{text}")

    @router_.message(Command("week"))
    async def cmd_week(message: Message) -> None:
        await _ensure_fresh_with_notice(message, coordinator)

        today = today_astana()
        events = merge_mirrors(
            await repo.get_upcoming(from_date=today, to_date=today + timedelta(days=7))
        )
        if not events:
            await message.answer("На ближайшую неделю квизов не нашлось.")
            return
        await _answer_chunked(message, _format_events_by_day(events))

    router_.message(F.text == BTN_TODAY)(cmd_today)
    router_.message(F.text == BTN_WEEK)(cmd_week)

    @router_.message(Command("themes"))
    async def cmd_themes(message: Message) -> None:
        buttons = [
            InlineKeyboardButton(text=name, callback_data=f"theme:{i}")
            for i, name in enumerate(ALL_THEMES)
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        await message.answer(
            "Выберите тему — покажу такие квизы на ближайшие "
            f"{_THEME_DAYS} дней по дням:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    router_.message(F.text == BTN_THEMES)(cmd_themes)

    @router_.callback_query(F.data.startswith("theme:"))
    async def cb_theme(callback: CallbackQuery) -> None:
        try:
            theme = ALL_THEMES[int((callback.data or "").split(":")[1])]
        except (IndexError, ValueError):
            await callback.answer("Некорректные данные кнопки.", show_alert=True)
            return
        await callback.answer()
        message = callback.message
        if message is None:
            return

        await _ensure_fresh_with_notice(message, coordinator)

        today = today_astana()
        events = merge_mirrors(
            await repo.get_upcoming(from_date=today, to_date=today + timedelta(days=_THEME_DAYS))
        )
        events = [e for e in events if theme in themes_of(e.title, e.source)]
        if not events:
            await message.answer(f"По теме «{theme}» на ближайшие {_THEME_DAYS} дней квизов не нашлось.")
            return
        await _answer_chunked(message, f"Тема: {theme}\n\n{_format_events_by_day(events)}")
