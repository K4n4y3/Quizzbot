from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def send_text(token: str, chat_ids: list[str], text: str) -> None:
    """Простое текстовое сообщение через Bot API — без aiogram, для скриптов."""
    async with httpx.AsyncClient(timeout=20) as client:
        for chat_id in chat_ids:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
            if not response.is_success:
                logger.error("Не удалось отправить сообщение в %s: %s", chat_id, response.text)


def parse_chat_ids(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]
