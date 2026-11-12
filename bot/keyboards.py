from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_TODAY = "📅 Сегодня"
BTN_WEEK = "🗓 Неделя"
BTN_THEMES = "🎭 По темам"
BTN_ADMIN = "⚙️ Админ"
BTN_BACK = "⬅️ Назад"
BTN_ADD_EVENT = "➕ Добавить квиз"
BTN_BULK_ADD = "📥 Массово"
BTN_MY_EVENTS = "📋 Мои квизы"
BTN_POST_TODAY = "📤 Опубликовать сегодня"
BTN_REFRESH = "🔄 Обновить расписание"
BTN_CANCEL = "❌ Отмена"


def _keyboard(*rows: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in rows],
        resize_keyboard=True,
    )


def main_menu_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    """
    Главное меню. Админские действия убраны в отдельное меню за кнопкой
    "⚙️ Админ" — её видят только админы, остальным хватает трёх кнопок.
    """
    if is_admin:
        return _keyboard([BTN_TODAY, BTN_WEEK], [BTN_THEMES, BTN_ADMIN])
    return _keyboard([BTN_TODAY, BTN_WEEK], [BTN_THEMES])


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return _keyboard(
        [BTN_ADD_EVENT, BTN_BULK_ADD],
        [BTN_MY_EVENTS, BTN_POST_TODAY],
        [BTN_REFRESH],
        [BTN_BACK],
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return _keyboard([BTN_CANCEL])
