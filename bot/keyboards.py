from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_TODAY = "📅 Сегодня"
BTN_WEEK = "🗓 Неделя"
BTN_THEMES = "🎭 По темам"
BTN_ADD_EVENT = "➕ Добавить квиз"
BTN_BULK_ADD = "📥 Массово"
BTN_MY_EVENTS = "📋 Мои квизы"
BTN_POST_TODAY = "📤 Опубликовать сегодня"
BTN_CANCEL = "❌ Отмена"


def main_menu_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    """
    Постоянная клавиатура вместо ввода команд руками. Админские пункты
    (добавление квизов вручную, публикация опроса) видны только админу —
    остальным просто нет смысла их показывать.
    """
    rows = [
        [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_WEEK)],
        [KeyboardButton(text=BTN_THEMES)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADD_EVENT), KeyboardButton(text=BTN_BULK_ADD)])
        rows.append([KeyboardButton(text=BTN_MY_EVENTS), KeyboardButton(text=BTN_POST_TODAY)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)
