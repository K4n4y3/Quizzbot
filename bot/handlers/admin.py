"""
Постинг расписания на сегодня в Telegram-канал в виде нативного опроса.

Доступно только администраторам (config.admin_user_ids) командой /post_today.
Сама публикация происходит только по нажатию инлайн-кнопки под превью —
команда сама по себе ничего никуда не постит, только показывает, что
получится.

У опросов Telegram есть жёсткие ограничения (Bot API 10.4): до 12 вариантов
ответа, до 100 символов на вариант, до 300 символов в вопросе. Последний
вариант всегда "сегодня без меня", так что в один опрос помещается 11
квизов; если больше — делим поровну на несколько опросов (см. poll_options).
"""

from __future__ import annotations

import logging
from datetime import date, time
from html import escape

import httpx

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputPollOption,
    Message,
)

from bot.handlers.schedule import ensure_fresh_with_notice
from bot.keyboards import (
    BTN_ADD_EVENT,
    BTN_BULK_ADD,
    BTN_CANCEL,
    BTN_MY_EVENTS,
    BTN_POST_TODAY,
    BTN_REFRESH,
    cancel_keyboard,
    main_menu_keyboard,
)
from config import Config
from models.event import QuizEvent
from scheduler.jobs import ParseCoordinator
from storage.repository import EventRepository
from utils.clock import MONTHS_GENITIVE_RU, WEEKDAYS_RU, today_astana
from utils.date_parser import DateParseError, extract_date, extract_time
from utils.merge import DisplayEvent, merge_mirrors

logger = logging.getLogger(__name__)

router = Router()

_MAX_OPTIONS_PER_POLL = 12  # лимит Telegram (Bot API 10.4: 1–12 вариантов)
_OPT_OUT = "сегодня без меня ❌"
_MAX_OPTION_LEN = 100
_MAX_QUESTION_LEN = 300


class AddEventStates(StatesGroup):
    """
    Пошаговый диалог добавления квиза вручную (Instagram-источники без
    сайта — см. README). Состояние живёт в памяти (aiogram MemoryStorage
    по умолчанию) — этого достаточно, диалог короткий и ведёт его один
    админ, переживать перезапуск процесса ему не нужно.
    """

    source = State()
    date = State()
    time = State()
    title = State()
    venue = State()
    confirm = State()


class BulkAddStates(StatesGroup):
    """
    Массовое добавление — админ одним сообщением (или .txt файлом)
    присылает список квизов, по одной строке на квиз, в формате
    "Источник | Дата время | Название | Место". Так проще заносить сразу
    несколько Instagram-источников, чем по одному через пошаговый диалог.
    """

    waiting = State()


def _poll_question(d: date, part: int, total_parts: int) -> str:
    header = f"🗓 {d.day} {MONTHS_GENITIVE_RU[d.month - 1]}, {WEEKDAYS_RU[d.weekday()]} - сегодня я иду..."
    if total_parts > 1:
        header += f" ({part}/{total_parts})"
    return header[:_MAX_QUESTION_LEN]


def _poll_option(e: DisplayEvent) -> str:
    """
    "Организатор время (бар, адрес) — Тема игры". В вариантах опроса
    Telegram не поддерживает жирный шрифт — только обычный текст. Если не
    влезает в лимит 100 символов, сначала жертвуем адресом, потом
    обрезаем тему.
    """
    text = f"{e.source} {e.time_text} ({e.place_text}) — {e.title}"
    if len(text) > _MAX_OPTION_LEN:
        text = f"{e.source} {e.time_text} ({e.venue_text}) — {e.title}"
    if len(text) > _MAX_OPTION_LEN:
        text = text[: _MAX_OPTION_LEN - 1] + "…"
    return text


async def send_quiz_poll(bot: Bot, chat_id: str, question: str, options: list[str]) -> None:
    # У бота по умолчанию HTML-разметка, и aiogram применяет её и к опросу:
    # символ "<" в названии квиза сломал бы отправку. Опрос — простой текст.
    await bot.send_poll(
        chat_id=chat_id,
        question=question,
        question_parse_mode=None,
        options=[InputPollOption(text=o, text_parse_mode=None) for o in options],
        is_anonymous=True,
        allows_multiple_answers=True,
    )


def poll_options(events: list[DisplayEvent]) -> list[list[str]]:
    """
    Варианты для опросов на день. Обычно это один опрос. Если всё не влезает
    (больше 11 квизов), делим поровну, а "без меня" ставим один раз —
    последним вариантом последнего опроса.
    """
    options = [_poll_option(e) for e in events] + [_OPT_OUT]
    parts = -(-len(options) // _MAX_OPTIONS_PER_POLL)
    size, extra = divmod(len(options), parts)
    polls, start = [], 0
    for i in range(parts):
        end = start + size + (1 if i < extra else 0)
        polls.append(options[start:end])
        start = end
    return polls


async def dispatch_scrape(config: Config, notify_chat_id: int) -> str | None:
    """Запускает workflow обновления расписания в GitHub. None — успех, иначе текст ошибки."""
    url = f"https://api.github.com/repos/{config.github_repo}/actions/workflows/scrape.yml/dispatches"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {config.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": "main", "inputs": {"notify_chat_id": str(notify_chat_id)}},
        )
    if response.status_code == 204:
        return None
    logger.error("GitHub не запустил обновление: %s %s", response.status_code, response.text)
    return f"GitHub ответил {response.status_code}"


def register_admin_handlers(
    router_: Router, repo: EventRepository, config: Config, coordinator: ParseCoordinator | None
) -> None:
    """Регистрирует хендлеры, которым нужен доступ к repo/config/coordinator."""

    def _is_admin(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in config.admin_user_ids

    @router_.message(Command("post_today"))
    async def cmd_post_today(message: Message) -> None:
        if not config.admin_user_ids:
            await message.answer(
                "Команда не настроена: задайте ADMIN_USER_ID в .env, чтобы ей пользоваться."
            )
            return
        if not _is_admin(message):
            return  # молча игнорируем чужих — это не публичная команда

        if not config.channel_id:
            await message.answer("Команда не настроена: задайте CHANNEL_ID в .env.")
            return

        await ensure_fresh_with_notice(message, coordinator)

        today = today_astana()
        events = merge_mirrors(await repo.get_upcoming(from_date=today, to_date=today))
        if not events:
            await message.answer("На сегодня квизов не нашлось — постить нечего.")
            return

        polls = poll_options(events)

        for i, options in enumerate(polls, start=1):
            question = _poll_question(today, i, len(polls))
            preview = "\n".join(f"☐ {escape(o)}" for o in options)
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📤 Опубликовать в канал",
                            callback_data=f"postpoll:{today.isoformat()}:{i - 1}",
                        )
                    ]
                ]
            )
            await message.answer(
                f"<b>Опрос {i}/{len(polls)}</b>\n<b>{escape(question)}</b>\n\n{preview}",
                reply_markup=keyboard,
            )

    router_.message(F.text == BTN_POST_TODAY)(cmd_post_today)

    @router_.message(Command("refresh"))
    async def cmd_refresh(message: Message) -> None:
        if not _is_admin(message):
            return
        if config.github_token:
            error = await dispatch_scrape(config, message.chat.id)
            if error:
                await message.answer(f"Не удалось запустить обновление: {escape(error)}")
            else:
                await message.answer("🔄 Запустил обновление расписания. Займёт 1–2 минуты, итог пришлю сюда.")
            return
        if coordinator is not None:  # локальный запуск: бот парсит сам
            await message.answer("⏳ Обновляю расписание, это займёт около минуты...")
            result = await coordinator.ensure_fresh(force=True)
            await message.answer(
                f"🔄 Расписание обновлено за {result.seconds:.0f} с: найдено игр {result.found}, "
                f"новых {result.inserted}."
            )
            return
        await message.answer("Кнопка не настроена: задайте GH_DISPATCH_TOKEN в настройках хостинга.")

    router_.message(F.text == BTN_REFRESH)(cmd_refresh)

    @router_.callback_query(F.data.startswith("postpoll:"))
    async def cb_post_poll(callback: CallbackQuery, bot: Bot) -> None:
        if callback.from_user.id not in config.admin_user_ids:
            await callback.answer("Только для администратора.", show_alert=True)
            return
        if not config.channel_id:
            await callback.answer("CHANNEL_ID не настроен в .env.", show_alert=True)
            return

        try:
            _, date_str, chunk_str = (callback.data or "").split(":")
            target_date = date.fromisoformat(date_str)
            chunk_index = int(chunk_str)
        except ValueError:
            await callback.answer("Некорректные данные кнопки.", show_alert=True)
            return

        events = merge_mirrors(await repo.get_upcoming(from_date=target_date, to_date=target_date))
        polls = poll_options(events) if events else []
        if chunk_index >= len(polls):
            await callback.answer(
                "Расписание на сегодня уже изменилось, эта кнопка устарела.", show_alert=True
            )
            return

        question = _poll_question(target_date, chunk_index + 1, len(polls))
        options = polls[chunk_index]

        try:
            await send_quiz_poll(bot, config.channel_id, question, options)
        except Exception:
            logger.exception("Не удалось опубликовать опрос в канал %s", config.channel_id)
            await callback.answer(
                "Не получилось опубликовать — проверьте, что бот добавлен в канал "
                "администратором с правом постить сообщения.",
                show_alert=True,
            )
            return

        await callback.answer("Опубликовано ✅")
        try:
            if callback.message is not None:
                await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass  # чисто косметика (убрать кнопку) — не критично, если не вышло

    # --- Добавление квиза вручную (Instagram-источники без сайта) ---

    @router_.message(F.text == BTN_ADD_EVENT)
    async def add_event_start(message: Message, state: FSMContext) -> None:
        if not _is_admin(message):
            return
        await state.set_state(AddEventStates.source)
        await message.answer(
            "Добавляем квиз вручную (например, из Instagram).\n\n"
            "Название источника? Например: Talqyla",
            reply_markup=cancel_keyboard(),
        )

    router_.message(Command("add_event"))(add_event_start)

    @router_.message(F.text == BTN_CANCEL, StateFilter(AddEventStates))
    async def add_event_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Добавление отменено.", reply_markup=main_menu_keyboard(_is_admin(message)))

    router_.message(Command("cancel"), StateFilter(AddEventStates))(add_event_cancel)
    router_.message(F.text == BTN_CANCEL, StateFilter(BulkAddStates))(add_event_cancel)
    router_.message(Command("cancel"), StateFilter(BulkAddStates))(add_event_cancel)

    @router_.message(AddEventStates.source)
    async def add_event_source(message: Message, state: FSMContext) -> None:
        source = (message.text or "").strip()
        if not source:
            await message.answer("Пустое название не подойдёт — введите название источника.")
            return
        await state.update_data(source=source)
        await state.set_state(AddEventStates.date)
        await message.answer("Дата квиза? Например: 2 октября или 02.10.2026")

    @router_.message(AddEventStates.date)
    async def add_event_date(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        try:
            event_date = extract_date(text)
        except DateParseError:
            await message.answer(
                'Не понял дату. Укажите в формате "2 октября" или "02.10.2026" — попробуйте ещё раз.'
            )
            return
        await state.update_data(event_date=event_date.isoformat())
        await state.set_state(AddEventStates.time)
        await message.answer('Время начала? Например: 20:00 (или "-", если не знаете)')

    @router_.message(AddEventStates.time)
    async def add_event_time(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        event_time = None
        if text != "-":
            event_time = extract_time(text)
            if event_time is None:
                await message.answer('Не понял время. Формат ЧЧ:ММ, например 20:00, или "-", если неизвестно.')
                return
        await state.update_data(event_time=event_time.isoformat() if event_time else None)
        await state.set_state(AddEventStates.title)
        await message.answer("Название квиза?")

    @router_.message(AddEventStates.title)
    async def add_event_title(message: Message, state: FSMContext) -> None:
        title = (message.text or "").strip()
        if not title:
            await message.answer("Пустое название не подойдёт — введите название квиза.")
            return
        await state.update_data(title=title)
        await state.set_state(AddEventStates.venue)
        await message.answer("Место проведения (бар/площадка)?")

    @router_.message(AddEventStates.venue)
    async def add_event_venue(message: Message, state: FSMContext) -> None:
        venue = (message.text or "").strip()
        if not venue:
            await message.answer("Пустое место не подойдёт — введите площадку.")
            return
        await state.update_data(venue=venue)
        await state.set_state(AddEventStates.confirm)

        data = await state.get_data()
        event_date = date.fromisoformat(data["event_date"])
        time_str = data["event_time"] or "время уточняется"
        summary = (
            "Проверьте перед сохранением:\n\n"
            f"Источник: {escape(data['source'])}\n"
            f"Дата: {event_date.strftime('%d.%m.%Y')}\n"
            f"Время: {time_str}\n"
            f"Название: {escape(data['title'])}\n"
            f"Место: {escape(venue)}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Сохранить", callback_data="addevent:confirm"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="addevent:cancel"),
                ]
            ]
        )
        await message.answer(summary, reply_markup=keyboard)

    @router_.callback_query(F.data == "addevent:confirm")
    async def cb_add_event_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.from_user.id not in config.admin_user_ids:
            await callback.answer("Только для администратора.", show_alert=True)
            return
        data = await state.get_data()
        if not data:
            await callback.answer("Сессия добавления устарела, начните заново.", show_alert=True)
            return

        event = QuizEvent(
            source=data["source"],
            title=data["title"],
            event_date=date.fromisoformat(data["event_date"]),
            venue=data["venue"],
            event_time=time.fromisoformat(data["event_time"]) if data["event_time"] else None,
            city=config.default_city,
            is_manual=True,
        )
        await repo.save_many([event])
        await state.clear()

        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Добавлено ✅")
        if callback.message is not None:
            await callback.message.answer(
                "Квиз добавлен в расписание.", reply_markup=main_menu_keyboard(True)
            )

    @router_.callback_query(F.data == "addevent:cancel")
    async def cb_add_event_confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Отменено")
        if callback.message is not None:
            await callback.message.answer("Добавление отменено.", reply_markup=main_menu_keyboard(True))

    # --- Массовое добавление списком (текст или .txt файл) ---

    @router_.message(F.text == BTN_BULK_ADD)
    async def bulk_add_start(message: Message, state: FSMContext) -> None:
        if not _is_admin(message):
            return
        await state.set_state(BulkAddStates.waiting)
        await message.answer(
            "Пришлите список квизов — по одной строке на квиз, поля через "
            '"|":\n\n'
            "Источник | Дата время | Название | Место\n\n"
            "Например:\n"
            "Talqyla | 2 октября 20:00 | Мемы №5 | Бар Chester\n"
            "Alibi | 5 окт 19:30 | Кино 2000-х | Craft bar\n\n"
            "Можно прислать обычным сообщением (несколько строк) или .txt файлом.",
            reply_markup=cancel_keyboard(),
        )

    router_.message(Command("bulk_add"))(bulk_add_start)

    async def _process_bulk_text(message: Message, state: FSMContext, text: str) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            await message.answer("Пустой список — нечего добавлять.")
            return

        events: list[QuizEvent] = []
        errors: list[str] = []
        for i, line in enumerate(lines, start=1):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 4:
                errors.append(f'{i}: ожидалось 4 поля через "|", получено {len(parts)}')
                continue
            source, when, title, venue = parts
            if not source or not title or not venue:
                errors.append(f"{i}: пустое обязательное поле")
                continue
            try:
                event_date = extract_date(when)
            except DateParseError:
                errors.append(f'{i}: не понял дату в "{escape(when)}"')
                continue
            events.append(
                QuizEvent(
                    source=source,
                    title=title,
                    event_date=event_date,
                    venue=venue,
                    event_time=extract_time(when),
                    city=config.default_city,
                    is_manual=True,
                )
            )

        inserted = await repo.save_many(events) if events else 0
        await state.clear()

        summary = f"Обработано строк: {len(lines)}. Добавлено новых: {inserted}."
        skipped_dupes = len(events) - inserted
        if skipped_dupes:
            summary += f" ({skipped_dupes} — уже были добавлены ранее, пропущены как дубликаты)"
        if errors:
            summary += "\n\nНе удалось разобрать:\n" + "\n".join(errors[:15])
            if len(errors) > 15:
                summary += f"\n...и ещё {len(errors) - 15}"

        await message.answer(summary, reply_markup=main_menu_keyboard(True))

    @router_.message(BulkAddStates.waiting, F.document)
    async def bulk_add_file(message: Message, state: FSMContext, bot: Bot) -> None:
        document = message.document
        if document.file_size and document.file_size > 200_000:
            await message.answer("Файл слишком большой (лимит ~200KB для текстового списка).")
            return
        buf = await bot.download(document.file_id)
        if buf is None:
            await message.answer("Не получилось скачать файл, попробуйте ещё раз.")
            return
        try:
            text = buf.read().decode("utf-8")
        except UnicodeDecodeError:
            await message.answer(
                "Не получилось прочитать файл — убедитесь, что это текст в кодировке UTF-8."
            )
            return
        await _process_bulk_text(message, state, text)

    @router_.message(BulkAddStates.waiting, F.text)
    async def bulk_add_text(message: Message, state: FSMContext) -> None:
        await _process_bulk_text(message, state, message.text or "")

    # --- Просмотр и удаление вручную добавленных квизов ---

    @router_.message(F.text == BTN_MY_EVENTS)
    async def list_manual_events(message: Message) -> None:
        if not _is_admin(message):
            return
        events = await repo.get_manual_upcoming()
        if not events:
            await message.answer("Вручную добавленных квизов пока нет.")
            return
        for e in events:
            time_str = e.event_time.strftime("%H:%M") if e.event_time else "время уточняется"
            text = (
                f"{e.event_date.strftime('%d.%m')} {time_str} — {escape(e.source)}: "
                f"{escape(e.title)} | {escape(e.venue)}"
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delmanual:{e.id}")]]
            )
            await message.answer(text, reply_markup=keyboard)

    router_.message(Command("my_events"))(list_manual_events)

    @router_.callback_query(F.data.startswith("delmanual:"))
    async def cb_delete_manual(callback: CallbackQuery) -> None:
        if callback.from_user.id not in config.admin_user_ids:
            await callback.answer("Только для администратора.", show_alert=True)
            return
        try:
            event_id = int((callback.data or "").split(":")[1])
        except (IndexError, ValueError):
            await callback.answer("Некорректные данные кнопки.", show_alert=True)
            return

        deleted = await repo.delete_manual(event_id)
        if not deleted:
            await callback.answer("Уже удалено или не найдено.", show_alert=True)
            return

        await callback.answer("Удалено")
        if callback.message is not None:
            try:
                await callback.message.delete()
            except Exception:
                pass  # не критично, если не удалось убрать сообщение из списка
