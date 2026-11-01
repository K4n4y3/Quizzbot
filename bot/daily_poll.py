"""
Ежедневный опрос "сегодня я иду..." в канал — без превью, сразу публикация.

Вызывается ботом по адресу /cron/daily-poll (его в нужное время дёргает
cron-job.org: расписание GitHub Actions для этого слишком неточное — запуски
опаздывают на час или пропадают) и вручную из GitHub Actions.
"""

from __future__ import annotations

import logging

from aiogram import Bot

from bot.handlers.admin import _MAX_OPTIONS_PER_POLL, _OPT_OUT, _chunk, _poll_option, _poll_question
from storage.repository import EventRepository
from utils.clock import today_astana
from utils.merge import merge_mirrors

logger = logging.getLogger(__name__)


async def post_daily_poll(bot: Bot, repo: EventRepository, channel_id: str, *, force: bool = False) -> str:
    """Публикует опрос на сегодня. Возвращает короткий итог для лога/ответа."""
    today = today_astana()
    if not force and await repo.poll_posted(today):
        return f"опрос за {today} уже опубликован — пропускаю"

    events = merge_mirrors(await repo.get_upcoming(from_date=today, to_date=today))
    if not events:
        return f"на {today} квизов нет — опрос не публикую"

    chunks = _chunk(events, _MAX_OPTIONS_PER_POLL)
    for i, chunk in enumerate(chunks, start=1):
        await bot.send_poll(
            chat_id=channel_id,
            question=_poll_question(today, i, len(chunks)),
            options=[_poll_option(e) for e in chunk] + [_OPT_OUT],
            is_anonymous=True,
            allows_multiple_answers=True,
        )
    await repo.mark_poll_posted(today)
    result = f"опубликовано опросов: {len(chunks)} (квизов: {len(events)}) в {channel_id}"
    logger.info("Ежедневный опрос: %s", result)
    return result
